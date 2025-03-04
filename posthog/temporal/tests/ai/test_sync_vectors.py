import json
from datetime import timedelta
from unittest.mock import patch

import cohere
import pytest
import pytest_asyncio
from cohere import EmbeddingsByTypeEmbedResponse
from django.utils import timezone

from posthog.clickhouse.client import sync_execute
from posthog.models import Action
from posthog.temporal.ai.sync_vectors import (
    GetApproximateActionsCountInputs,
    RetrieveActionsInputs,
    SyncActionVectorsForTeamInputs,
    batch_summarize_and_embed_actions,
    get_actions_qs,
    get_approximate_actions_count,
    sync_action_vectors_for_team,
)


@pytest.fixture
def action_models(ateam):
    return (
        Action(
            team=ateam,
            name="Completed onboarding",
            description="Filters users who successfully completed onboarding",
            steps_json=[{"event": "onboarding completed"}],
        ),
        Action(
            team=ateam,
            name="Requested a quote",
            description="Display users who wanted to purchase the product",
            steps_json=[{"href": "/subscribe", "href_matching": "exact", "event": "pressed button"}],
        ),
        Action(
            team=ateam,
            name="Interacted with the assistant",
            description="Cohort of events when users interacted with the AI assistant",
            steps_json=[{"event": "message sent"}, {"url": "/chat", "event": "$pageview"}],
        ),
    )


@pytest_asyncio.fixture
async def actions(action_models, ateam):
    await Action.objects.abulk_create(actions)

    yield actions

    await Action.objects.filter(team=ateam).adelete()


@pytest_asyncio.fixture
async def summarized_actions(action_models, ateam):
    dt = timezone.now()
    embeddings = [[0.12, 0.054], [0.1, 0.7], [0.8, 0.6663]]
    summaries = ["Test summary 1", "Test summary 2", "Test summary 3"]
    for action, embedding, summary in zip(action_models, embeddings, summaries):
        action.last_summarized_at = dt
        action.summary = summary
        action.embedding = embedding
    await Action.objects.abulk_create(action_models)
    yield action_models
    await Action.objects.filter(team=ateam).adelete()


@pytest.fixture
def mock_flag(ateam):
    with patch(
        "posthog.temporal.ai.sync_vectors._get_orgs_from_the_feature_flag", return_value=[str(ateam.organization.id)]
    ) as mock:
        yield mock


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_get_actions_qs(mock_flag, actions):
    qs = await get_actions_qs(timezone.now())
    assert await qs.acount() == 3
    qs = await get_actions_qs(timezone.now(), 0, 1)
    assert await qs.acount() == 1
    qs = await get_actions_qs(timezone.now() - timedelta(days=1))
    assert await qs.acount() == 0

    dt = timezone.now()
    action = actions[0]
    action.last_summarized_at = dt + timedelta(seconds=1)
    await action.asave()

    qs = await get_actions_qs(dt + timedelta(seconds=2))
    assert await qs.acount() == 2


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_get_approximate_actions_count(mock_flag, actions):
    res = await get_approximate_actions_count(GetApproximateActionsCountInputs(start_dt=timezone.now().isoformat()))
    assert res == 3


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_batch_summarize_and_embed_actions(mock_flag, actions: tuple[Action]):
    with (
        patch("posthog.temporal.ai.sync_vectors.get_cohere_client", return_value=cohere.AsyncClientV2(api_key="test")),
        patch("posthog.temporal.ai.sync_vectors.abatch_summarize_actions") as summarize_mock,
        patch("cohere.AsyncClientV2.embed") as embeddings_mock,
    ):
        summarize_mock.return_value = ["Test1"]
        embeddings_mock.return_value = EmbeddingsByTypeEmbedResponse(
            embeddings={"float_": [[0.12, 0.054]]},
            id="test",
            texts=["Test1"],
        )

        start_dt = timezone.now()
        await batch_summarize_and_embed_actions(
            RetrieveActionsInputs(offset=0, batch_size=1, start_dt=start_dt.isoformat())
        )
        assert summarize_mock.call_count == 1

        updated_action = actions[0]
        await updated_action.arefresh_from_db()
        assert updated_action.summary == "Test1"
        assert updated_action.last_summarized_at == start_dt
        assert updated_action.embedding_last_synced_at is None
        assert updated_action.embedding == [0.12, 0.054]

        for action in actions[1:]:
            await action.arefresh_from_db()
            assert action.summary is None
            assert action.last_summarized_at is None
            assert action.embedding is None
            assert action.embedding_last_synced_at is None

        summarize_mock.return_value = ["Test2", "Test3"]
        embeddings_mock.return_value = EmbeddingsByTypeEmbedResponse(
            embeddings={"float_": [[0.1, 0.7], [0.8, 0.6663]]},
            id="test",
            texts=["Test2", "Test3"],
        )

        await batch_summarize_and_embed_actions(
            RetrieveActionsInputs(offset=1, batch_size=10, start_dt=start_dt.isoformat())
        )
        assert summarize_mock.call_count == 2
        expected_embeddings = ([0.12, 0.054], [0.1, 0.7], [0.8, 0.6663])
        expected_texts = ["Test1", "Test2", "Test3"]

        for action, expected_embedding, expected_text in zip(actions, expected_embeddings, expected_texts):
            await action.arefresh_from_db()
            assert action.summary == expected_text
            assert action.last_summarized_at == start_dt
            assert action.embedding == expected_embedding
            assert action.embedding_last_synced_at is None


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_batch_summarize_in_a_single_batch(mock_flag, actions: tuple[Action]):
    embeddings = [[0.12, 0.054], [0.1, 0.7], [0.8, 0.6663]]
    texts = ["Test1", "Test2", "Test3"]

    with (
        patch("posthog.temporal.ai.sync_vectors.abatch_summarize_actions", return_value=texts),
        patch(
            "cohere.AsyncClientV2.embed",
            return_value=EmbeddingsByTypeEmbedResponse(
                embeddings={"float_": embeddings},
                id="test",
                texts=texts,
            ),
        ),
        patch("posthog.temporal.ai.sync_vectors.get_cohere_client", return_value=cohere.AsyncClientV2(api_key="test")),
    ):
        start_dt = timezone.now()
        await batch_summarize_and_embed_actions(
            RetrieveActionsInputs(offset=0, batch_size=96, start_dt=start_dt.isoformat())
        )
        updated_actions = [action async for action in Action.objects.all()]
        assert len(updated_actions) == 3
        for action, expected_embedding, expected_text in zip(updated_actions, embeddings, texts):
            assert action.summary == expected_text
            assert action.last_summarized_at == start_dt
            assert action.embedding == expected_embedding
            assert action.embedding_last_synced_at is None


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_batch_summarize_with_errors(mock_flag, actions: tuple[Action]):
    embeddings = [[0.12, 0.054], [0.1, 0.7], [0.2, 0.7]]

    with (
        patch("posthog.temporal.ai.sync_vectors.abatch_summarize_actions") as summarize_mock,
        patch("cohere.AsyncClientV2.embed") as embed_mock,
        patch("posthog.temporal.ai.sync_vectors.get_cohere_client", return_value=cohere.AsyncClientV2(api_key="test")),
    ):
        summarize_mock.return_value = ["Test1", "Test2", ValueError()]
        embed_mock.return_value = EmbeddingsByTypeEmbedResponse(
            embeddings={"float_": embeddings[:2]},
            id="test",
            texts=["Test1", "Test2"],
        )

        start_dt = timezone.now()
        await batch_summarize_and_embed_actions(
            RetrieveActionsInputs(offset=0, batch_size=96, start_dt=start_dt.isoformat())
        )
        updated_actions = [action async for action in Action.objects.order_by("id").all()]
        assert len(updated_actions) == 3
        assert updated_actions[0].summary == "Test1"
        assert updated_actions[1].summary == "Test2"
        assert updated_actions[2].summary is None

        assert updated_actions[0].last_summarized_at == start_dt
        assert updated_actions[1].last_summarized_at == start_dt
        assert updated_actions[2].last_summarized_at is None

        assert updated_actions[0].embedding == embeddings[0]
        assert updated_actions[1].embedding == embeddings[1]
        assert updated_actions[2].embedding is None

        assert updated_actions[0].embedding_last_synced_at is None
        assert updated_actions[1].embedding_last_synced_at is None
        assert updated_actions[2].embedding_last_synced_at is None

        # Next batch must summarize exactly a single action
        summarize_mock.return_value = ["Test3"]
        embed_mock.return_value = EmbeddingsByTypeEmbedResponse(
            embeddings={"float_": [embeddings[2]]},
            id="test",
            texts=["Test3"],
        )
        summarize_mock.reset_mock()

        new_start_dt = timezone.now()
        await batch_summarize_and_embed_actions(
            RetrieveActionsInputs(offset=0, batch_size=96, start_dt=new_start_dt.isoformat())
        )
        assert summarize_mock.call_count == 1
        assert len(summarize_mock.call_args[0][0]) == 1

        updated_actions = [action async for action in Action.objects.order_by("id").all()]
        assert len(updated_actions) == 3
        assert ("Test1", "Test2", "Test3") == tuple(action.summary for action in updated_actions)
        assert embeddings == [action.embedding for action in updated_actions]
        assert [start_dt, start_dt, new_start_dt] == [action.last_summarized_at for action in updated_actions]


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_sync_action_vectors_for_team_valid_inputs(mock_flag, summarized_actions, ateam):
    """Test that sync_action_vectors_for_team handles valid inputs correctly."""
    start_dt = timezone.now()
    result = await sync_action_vectors_for_team(
        SyncActionVectorsForTeamInputs(batch_size=10, start_dt=start_dt.isoformat())
    )
    assert result.has_more is False

    embeddings = sync_execute("SELECT * FROM pg_embeddings ORDER BY id")
    assert len(embeddings) == 3

    expected_result = [
        (
            "action",
            ateam.id,
            str(action.id),
            action.embedding,
            action.summary,
            json.dumps({"name": action.name, "description": action.description}),
            start_dt.replace(microsecond=0),
            0,
        )
        for action in summarized_actions
    ]
    assert expected_result == embeddings
