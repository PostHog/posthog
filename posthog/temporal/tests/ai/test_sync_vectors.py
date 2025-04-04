import json
import uuid
from datetime import timedelta
from itertools import cycle
from typing import Annotated, Any
from unittest.mock import patch

import cohere
import pytest
import pytest_asyncio
from cohere import EmbeddingsByTypeEmbedResponse
from django.conf import settings
from django.utils import timezone
from pydantic import BaseModel, PlainValidator
from temporalio import activity
from temporalio.client import WorkflowFailureError
from temporalio.testing import WorkflowEnvironment
from temporalio.worker import UnsandboxedWorkflowRunner, Worker

from posthog.clickhouse.client import sync_execute
from posthog.models import Action
from posthog.models.ai.pg_embeddings import TRUNCATE_PG_EMBEDDINGS_TABLE_SQL
from posthog.temporal.ai.sync_vectors import (
    BatchEmbedAndSyncActionsInputs,
    BatchEmbedAndSyncActionsOutputs,
    BatchSummarizeActionsInputs,
    GetApproximateActionsCountInputs,
    SyncVectorsInputs,
    SyncVectorsWorkflow,
    batch_embed_actions,
    batch_embed_and_sync_actions,
    batch_summarize_actions,
    get_actions_qs,
    get_approximate_actions_count,
    sync_action_vectors,
)
from posthog.temporal.common.clickhouse import get_client


@pytest.fixture(autouse=True)
def cleanup():
    yield
    sync_execute(TRUNCATE_PG_EMBEDDINGS_TABLE_SQL())


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
    await Action.objects.abulk_create(action_models)
    yield action_models
    await Action.objects.filter(team=ateam).adelete()


@pytest_asyncio.fixture
async def summarized_actions(action_models, ateam):
    dt = timezone.now()
    summaries = ["Test summary 1", "Test summary 2", "Test summary 3"]
    for action, summary in zip(action_models, summaries):
        action.last_summarized_at = dt
        action.summary = summary

    await Action.objects.abulk_create(action_models)
    yield action_models
    await Action.objects.filter(team=ateam).adelete()


@pytest.fixture
def summarized_actions_with_embeddings(summarized_actions) -> list[tuple[dict[str, Any], list[float]]]:
    embeddings = [[0.1, 0.2], [0.2, 0.1], [0.5, 0.9]]
    return [
        (
            {
                "id": action.id,
                "summary": action.summary,
                "team_id": action.team_id,
                "name": action.name,
                "description": action.description,
                "deleted": action.deleted,
            },
            embedding,
        )
        for action, embedding in zip(summarized_actions, embeddings)
    ]


@pytest.fixture
def mock_flag(ateam):
    with patch(
        "posthog.temporal.ai.sync_vectors._get_orgs_from_the_feature_flag", return_value=[str(ateam.organization.id)]
    ) as mock:
        yield mock


@pytest.fixture
def cohere_mock():
    with patch(
        "posthog.temporal.ai.sync_vectors.get_async_cohere_client", return_value=cohere.AsyncClientV2(api_key="test")
    ) as mock:
        yield mock


def _query_pg_embeddings() -> list[tuple]:
    return sync_execute("SELECT * FROM pg_embeddings ORDER BY id")


@pytest.mark.django_db
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


@pytest.mark.django_db
@pytest.mark.asyncio
async def test_get_actions_qs_with_deleted_actions(mock_flag, actions):
    start_dt = timezone.now()

    # Never summarized and deleted
    action_1, action_2, action_3 = actions
    action_1.deleted = True
    await action_1.asave()

    # Updated after last summarization
    action_2.updated_at = start_dt - timedelta(hours=1)
    action_2.last_summarized_at = start_dt - timedelta(hours=2)
    await action_2.asave()

    # Deleted but updated after last summarization
    action_3.updated_at = start_dt - timedelta(hours=2)
    action_3.last_summarized_at = start_dt - timedelta(hours=1)
    action_3.deleted = True
    await action_3.asave()

    qs = await get_actions_qs(start_dt + timedelta(hours=1))
    assert await qs.acount() == 2
    assert {a async for a in qs.values_list("id", flat=True)} == {action_2.id, action_3.id}


@pytest.mark.django_db
@pytest.mark.asyncio
async def test_get_actions_qs_with_unapproved_organization(mock_flag, aorganization):
    aorganization.is_ai_data_processing_approved = False
    await aorganization.asave()
    qs = await get_actions_qs(timezone.now())
    assert await qs.acount() == 0


@pytest.mark.django_db
@pytest.mark.asyncio
async def test_get_approximate_actions_count(mock_flag, actions):
    res = await get_approximate_actions_count(GetApproximateActionsCountInputs(start_dt=timezone.now().isoformat()))
    assert res == 3


@pytest.mark.django_db
@pytest.mark.asyncio
async def test_basic_batch_summarization(mock_flag, cohere_mock, actions):
    with (
        patch("posthog.temporal.ai.sync_vectors.abatch_summarize_actions") as summarize_mock,
    ):
        summarize_mock.return_value = ["Test1"]

        start_dt = timezone.now()
        await batch_summarize_actions(
            BatchSummarizeActionsInputs(offset=0, batch_size=1, start_dt=start_dt.isoformat())
        )
        assert summarize_mock.call_count == 1

        updated_action = actions[0]
        await updated_action.arefresh_from_db()
        assert updated_action.summary == "Test1"
        assert updated_action.last_summarized_at == start_dt
        assert updated_action.embedding_last_synced_at is None

        for action in actions[1:]:
            await action.arefresh_from_db()
            assert action.summary is None
            assert action.last_summarized_at is None
            assert action.embedding_last_synced_at is None

        summarize_mock.return_value = ["Test2", "Test3"]

        await batch_summarize_actions(
            BatchSummarizeActionsInputs(offset=1, batch_size=10, start_dt=start_dt.isoformat())
        )
        assert summarize_mock.call_count == 2
        expected_texts = ["Test1", "Test2", "Test3"]

        for action, expected_text in zip(actions, expected_texts):
            await action.arefresh_from_db()
            assert action.summary == expected_text
            assert action.last_summarized_at == start_dt
            assert action.embedding_last_synced_at is None


@pytest.mark.django_db
@pytest.mark.asyncio
async def test_batch_summarize_with_errors(mock_flag, cohere_mock, actions: tuple[Action], ateam):
    with (
        patch("posthog.temporal.ai.sync_vectors.abatch_summarize_actions") as summarize_mock,
    ):
        summarize_mock.return_value = ["Test1", "Test2", ValueError()]

        start_dt = timezone.now()
        await batch_summarize_actions(
            BatchSummarizeActionsInputs(offset=0, batch_size=96, start_dt=start_dt.isoformat())
        )
        updated_actions = [action async for action in Action.objects.filter(team=ateam).order_by("id")]
        assert len(updated_actions) == 3
        assert updated_actions[0].summary == "Test1"
        assert updated_actions[1].summary == "Test2"
        assert updated_actions[2].summary is None

        assert updated_actions[0].last_summarized_at == start_dt
        assert updated_actions[1].last_summarized_at == start_dt
        assert updated_actions[2].last_summarized_at is None

        assert updated_actions[0].embedding_last_synced_at is None
        assert updated_actions[1].embedding_last_synced_at is None
        assert updated_actions[2].embedding_last_synced_at is None

        # Next batch must summarize exactly a single action
        summarize_mock.return_value = ["Test3"]
        summarize_mock.reset_mock()

        new_start_dt = timezone.now()
        await batch_summarize_actions(
            BatchSummarizeActionsInputs(offset=0, batch_size=96, start_dt=new_start_dt.isoformat())
        )
        assert summarize_mock.call_count == 1
        assert len(summarize_mock.call_args[0][0]) == 1

        updated_actions = [action async for action in Action.objects.filter(team=ateam).order_by("id")]
        assert len(updated_actions) == 3
        assert ("Test1", "Test2", "Test3") == tuple(action.summary for action in updated_actions)
        assert [start_dt, start_dt, new_start_dt] == [action.last_summarized_at for action in updated_actions]


@pytest.mark.django_db
@pytest.mark.asyncio
async def test_batch_embedding(mock_flag, cohere_mock, actions):
    with (
        patch("cohere.AsyncClientV2.embed") as embeddings_mock,
    ):
        # batch_size=1, one call
        embeddings_mock.return_value = EmbeddingsByTypeEmbedResponse(
            embeddings={"float_": [[0.12, 0.054]]},
            id="test",
            texts=["Test1"],
        )

        res = await batch_embed_actions([{"summary": "Test1"}], batch_size=1)
        assert embeddings_mock.call_count == 1
        assert res == [({"summary": "Test1"}, [0.12, 0.054])]

        embeddings_mock.reset_mock()

        # batch_size=2, one call
        embeddings_mock.return_value = EmbeddingsByTypeEmbedResponse(
            embeddings={"float_": [[0.1, 0.7], [0.8, 0.6663]]},
            id="test",
            texts=["Test2", "Test3"],
        )

        res = await batch_embed_actions([{"summary": "Test2"}, {"summary": "Test3"}], batch_size=2)
        assert embeddings_mock.call_count == 1
        assert res == [({"summary": "Test2"}, [0.1, 0.7]), ({"summary": "Test3"}, [0.8, 0.6663])]

        embeddings_mock.reset_mock()

        # batch_size=2, two parallel calls
        embeddings_mock.return_value = EmbeddingsByTypeEmbedResponse(
            embeddings={"float_": [[0.12, 0.054], [0.1, 0.7]]},
            id="test",
            texts=["Test1", "Test2", "Test3"],
        )

        res = await batch_embed_actions(
            [{"summary": "Test1"}, {"summary": "Test2"}, {"summary": "Test3"}], batch_size=2
        )
        assert embeddings_mock.call_count == 2
        assert res == [
            ({"summary": "Test1"}, [0.12, 0.054]),
            ({"summary": "Test2"}, [0.1, 0.7]),
            ({"summary": "Test3"}, [0.12, 0.054]),
        ]


@pytest.mark.django_db
@pytest.mark.asyncio
async def test_batch_embedding_with_errors(cohere_mock, mock_flag, actions: tuple[Action]):
    with patch("cohere.AsyncClientV2.embed") as embeddings_mock:
        # batch_size=1, one call
        embeddings_mock.side_effect = ValueError("Test error")

        res = await batch_embed_actions([{"summary": "Test1"}], batch_size=1)
        assert embeddings_mock.call_count == 1
        assert res == []

        call_count = 0

        def side_effect(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 2:
                raise ValueError("Test error")
            return EmbeddingsByTypeEmbedResponse(
                embeddings={"float_": [[0.12, 0.054]]},
                id="test",
                texts=["Test1"],
            )

        embeddings_mock.reset_mock()
        embeddings_mock.side_effect = side_effect

        res = await batch_embed_actions(
            [{"summary": "Test1"}, {"summary": "Test2"}, {"summary": "Test3"}], batch_size=2
        )
        assert embeddings_mock.call_count == 2
        assert res == [({"summary": "Test1"}, [0.12, 0.054])]


class PgEmbeddingRecord(BaseModel):
    domain: str
    team_id: int
    id: str
    embedding: Annotated[list[float], PlainValidator(lambda x: [round(val, 5) for val in x])]
    summary: str
    properties: dict | None
    is_deleted: int


def parse_records(rows: list[tuple]) -> list[PgEmbeddingRecord]:
    return [
        PgEmbeddingRecord(
            domain=t[0],
            team_id=t[1],
            id=str(t[2]),
            embedding=t[3],
            summary=t[4],
            properties=json.loads(t[5]) if t[5] else None,
            is_deleted=t[7],
        )
        for t in rows
    ]


@pytest.mark.django_db
@pytest.mark.asyncio
async def test_clickhouse_sync_single_batch(mock_flag, summarized_actions, summarized_actions_with_embeddings, ateam):
    start_dt = timezone.now()
    async with get_client() as client:
        await sync_action_vectors(client, summarized_actions_with_embeddings, 10, start_dt)

        embeddings = _query_pg_embeddings()
        assert len(embeddings) == 3

        expected_result = [
            PgEmbeddingRecord(
                domain="action",
                team_id=ateam.id,
                id=str(action["id"]),
                embedding=embedding,
                summary=action["summary"],
                properties={"name": action["name"], "description": action["description"]},
                is_deleted=0,
            )
            for action, embedding in summarized_actions_with_embeddings
        ]
        assert expected_result == parse_records(embeddings)

        for action in summarized_actions:
            await action.arefresh_from_db()
            assert action.embedding_last_synced_at == start_dt

        with patch("posthog.temporal.common.clickhouse.ClickHouseClient.execute_query") as mock:
            await sync_action_vectors(client, summarized_actions_with_embeddings, 10, start_dt)
            assert mock.call_count == 1


@pytest.mark.django_db
@pytest.mark.asyncio
async def test_clickhouse_sync_multiple_batches(
    mock_flag, summarized_actions, summarized_actions_with_embeddings, ateam
):
    start_dt = timezone.now()
    async with get_client() as client:
        await sync_action_vectors(client, summarized_actions_with_embeddings, 1, start_dt)

        embeddings = _query_pg_embeddings()
        assert len(embeddings) == 3

        expected_result = [
            PgEmbeddingRecord(
                domain="action",
                team_id=ateam.id,
                id=str(action["id"]),
                embedding=embedding,
                summary=action["summary"],
                properties={"name": action["name"], "description": action["description"]},
                is_deleted=0,
            )
            for action, embedding in summarized_actions_with_embeddings
        ]
        assert expected_result == parse_records(embeddings)

        for action in summarized_actions:
            await action.arefresh_from_db()
            assert action.embedding_last_synced_at == start_dt

        with patch("posthog.temporal.common.clickhouse.ClickHouseClient.execute_query") as mock:
            await sync_action_vectors(client, summarized_actions_with_embeddings, 1, start_dt)
            assert mock.call_count == 3


@pytest.mark.django_db
@pytest.mark.asyncio
async def test_batch_embed_and_sync_actions(cohere_mock, mock_flag, summarized_actions, ateam):
    start_dt = timezone.now()
    embeddings = [[0.12, 0.054], [0.1, 0.7], [0.8, 0.6663]]
    with patch("cohere.AsyncClientV2.embed") as embeddings_mock:
        embeddings_mock.return_value = EmbeddingsByTypeEmbedResponse(
            embeddings={"float_": embeddings},
            id="test",
            texts=["Test1", "Test2", "Test3"],
        )
        result = await batch_embed_and_sync_actions(
            BatchEmbedAndSyncActionsInputs(
                start_dt=start_dt.isoformat(),
                insert_batch_size=10,
                embeddings_batch_size=10,
                max_parallel_requests=4,
            )
        )
        assert result.has_more is True

        rows = _query_pg_embeddings()
        assert len(rows) == 3

        expected_result = [
            PgEmbeddingRecord(
                domain="action",
                team_id=ateam.id,
                id=str(action.id),
                embedding=embedding,
                summary=action.summary,
                properties={"name": action.name, "description": action.description},
                is_deleted=0,
            )
            for action, embedding in zip(summarized_actions, embeddings)
        ]
        assert expected_result == parse_records(rows)

        result = await batch_embed_and_sync_actions(
            BatchEmbedAndSyncActionsInputs(
                start_dt=start_dt.isoformat(),
                insert_batch_size=10,
                embeddings_batch_size=10,
                max_parallel_requests=4,
            )
        )
        assert result.has_more is False
        rows = _query_pg_embeddings()
        assert len(rows) == 3


@pytest.mark.django_db
@pytest.mark.asyncio
async def test_batch_embed_and_sync_actions_in_batches(cohere_mock, mock_flag, summarized_actions, ateam):
    start_dt = timezone.now()
    embeddings = [[0.12, 0.054]]

    with patch("cohere.AsyncClientV2.embed") as embeddings_mock:
        embeddings_mock.return_value = EmbeddingsByTypeEmbedResponse(
            embeddings={"float_": embeddings},
            id="test",
            texts=["Test1", "Test2", "Test3"],
        )
        result = await batch_embed_and_sync_actions(
            BatchEmbedAndSyncActionsInputs(
                start_dt=start_dt.isoformat(),
                insert_batch_size=1,
                embeddings_batch_size=1,
                max_parallel_requests=2,
            )
        )
        assert result.has_more is True

        rows = _query_pg_embeddings()
        assert len(rows) == 2

        result = await batch_embed_and_sync_actions(
            BatchEmbedAndSyncActionsInputs(
                start_dt=start_dt.isoformat(),
                insert_batch_size=1,
                embeddings_batch_size=1,
                max_parallel_requests=2,
            )
        )
        assert result.has_more is True

        rows = _query_pg_embeddings()
        assert len(rows) == 3

        result = await batch_embed_and_sync_actions(
            BatchEmbedAndSyncActionsInputs(
                start_dt=start_dt.isoformat(),
                insert_batch_size=1,
                embeddings_batch_size=1,
                max_parallel_requests=2,
            )
        )
        assert result.has_more is False

        expected_result = [
            PgEmbeddingRecord(
                domain="action",
                team_id=ateam.id,
                id=str(action.id),
                embedding=embedding,
                summary=action.summary,
                properties={"name": action.name, "description": action.description},
                is_deleted=0,
            )
            for action, embedding in zip(summarized_actions, cycle(embeddings))
        ]

        rows = _query_pg_embeddings()
        assert len(rows) == 3
        assert expected_result == parse_records(rows)


@pytest.mark.django_db
@pytest.mark.asyncio
async def test_batch_embed_and_sync_actions_filters_out_actions(cohere_mock, mock_flag, ateam):
    start_dt = timezone.now()
    embeddings = [[0.1, 0.1], [0.2, 0.2], [0.3, 0.3]]

    # Create actions with different last_summarized_at values
    actions = [
        Action(
            team=ateam, name="Before start 1", last_summarized_at=start_dt - timedelta(days=1), summary="Test1"
        ),  # Should be included
        Action(
            team=ateam,
            name="Before start 2",
            last_summarized_at=start_dt - timedelta(days=1),
            embedding_last_synced_at=start_dt - timedelta(days=2),
            summary="Test2",
        ),  # Should be included
        Action(team=ateam, name="At start", last_summarized_at=start_dt, summary="Test3"),  # Should be included
        Action(
            team=ateam, name="After start", last_summarized_at=start_dt + timedelta(days=1), summary="Test4"
        ),  # Should not be included
    ]
    await Action.objects.abulk_create(actions)

    with patch("cohere.AsyncClientV2.embed") as embeddings_mock:
        embeddings_mock.return_value = EmbeddingsByTypeEmbedResponse(
            embeddings={"float_": embeddings},
            id="test",
            texts=["Test1", "Test2", "Test3"],
        )
        for expected_has_more in (True, False):
            result = await batch_embed_and_sync_actions(
                BatchEmbedAndSyncActionsInputs(
                    start_dt=start_dt.isoformat(),
                    insert_batch_size=1000,
                    embeddings_batch_size=96,
                    max_parallel_requests=4,
                )
            )
            assert result.has_more is expected_has_more

        rows = _query_pg_embeddings()
        assert len(rows) == 3

        assert {str(actions[0].id), str(actions[1].id), str(actions[2].id)} == {
            action.id for action in parse_records(rows)
        }


@pytest.mark.django_db
@pytest.mark.asyncio
async def test_batch_embed_and_sync_actions_filters_out_actions_with_no_summary(mock_flag, ateam):
    start_dt = timezone.now()

    # Create actions with different last_summarized_at values
    actions = [
        Action(
            team=ateam, name="Before start 1", last_summarized_at=start_dt - timedelta(days=1)
        ),  # Should be included
    ]
    await Action.objects.abulk_create(actions)

    result = await batch_embed_and_sync_actions(
        BatchEmbedAndSyncActionsInputs(
            start_dt=start_dt.isoformat(),
            insert_batch_size=1000,
            embeddings_batch_size=96,
            max_parallel_requests=4,
        )
    )
    assert result.has_more is False
    rows = _query_pg_embeddings()
    assert len(rows) == 0


async def _create_actions_with_embedding_version(ateam, start_dt):
    # Create actions with different last_summarized_at values
    actions = [
        Action(
            team=ateam,
            name="Before start 1",
            last_summarized_at=start_dt - timedelta(days=1),
            embedding_last_synced_at=start_dt - timedelta(hours=8),  # shouldn't be included by time filters
            summary="Test1",
            embedding_version=None,
        ),  # Should be included
        Action(
            team=ateam,
            name="Before start 2",
            last_summarized_at=start_dt - timedelta(days=1),
            embedding_last_synced_at=start_dt - timedelta(hours=8),  # shouldn't be included by time filters
            summary="Test2",
            embedding_version=1,
        ),  # Should be included
        Action(
            team=ateam,
            name="Before start 2",
            last_summarized_at=start_dt - timedelta(days=1),
            embedding_last_synced_at=start_dt - timedelta(days=2),
            summary="Test2",
            embedding_version=2,  # Should not be included by the version filter
        ),  # Should be included
    ]
    await Action.objects.abulk_create(actions)
    return actions


@pytest.mark.django_db
@pytest.mark.asyncio
async def test_batch_embed_and_sync_actions_embedding_version(cohere_mock, mock_flag, ateam):
    start_dt = timezone.now()
    embeddings = [[0.1, 0.1], [0.2, 0.2], [0.3, 0.3]]

    actions = await _create_actions_with_embedding_version(ateam, start_dt)

    with patch("cohere.AsyncClientV2.embed") as embeddings_mock:
        embeddings_mock.return_value = EmbeddingsByTypeEmbedResponse(
            embeddings={"float_": embeddings},
            id="test",
            texts=["Test1", "Test2", "Test3"],
        )

        for expected_has_more in (True, False):
            result = await batch_embed_and_sync_actions(
                BatchEmbedAndSyncActionsInputs(
                    start_dt=start_dt.isoformat(),
                    insert_batch_size=1000,
                    embeddings_batch_size=96,
                    max_parallel_requests=4,
                    embedding_version=2,
                )
            )
            assert result.has_more is expected_has_more

        rows = _query_pg_embeddings()
        assert len(rows) == 3

        assert {str(actions[0].id), str(actions[1].id), str(actions[2].id)} == {
            action.id for action in parse_records(rows)
        }


@pytest.mark.asyncio
async def test_actions_basic_workflow():
    call_count = [0, 0, 0]

    @activity.defn(name="get_approximate_actions_count")
    async def get_approximate_actions_count_mocked(inputs: GetApproximateActionsCountInputs) -> int:
        call_count[0] += 1
        return 3

    @activity.defn(name="batch_summarize_actions")
    async def batch_summarize_and_embed_actions_mocked(inputs: BatchSummarizeActionsInputs) -> None:
        call_count[1] += 1

    @activity.defn(name="batch_embed_and_sync_actions")
    async def sync_action_vectors_for_team_mocked(
        inputs: BatchEmbedAndSyncActionsInputs,
    ) -> BatchEmbedAndSyncActionsOutputs:
        call_count[2] += 1
        if call_count[2] == 4 or inputs.insert_batch_size != 1:
            return BatchEmbedAndSyncActionsOutputs(has_more=False)
        else:
            return BatchEmbedAndSyncActionsOutputs(has_more=True)

    async with await WorkflowEnvironment.start_time_skipping() as activity_environment:
        async with Worker(
            activity_environment.client,
            task_queue=settings.TEMPORAL_TASK_QUEUE,
            workflows=[SyncVectorsWorkflow],
            activities=[
                get_approximate_actions_count_mocked,
                batch_summarize_and_embed_actions_mocked,
                sync_action_vectors_for_team_mocked,
            ],
            workflow_runner=UnsandboxedWorkflowRunner(),
        ):
            await activity_environment.client.execute_workflow(
                SyncVectorsWorkflow.run,
                SyncVectorsInputs(start_dt=timezone.now().isoformat(), delay_between_batches=0),
                id=str(uuid.uuid4()),
                task_queue=settings.TEMPORAL_TASK_QUEUE,
            )
            assert call_count == [1, 1, 1]

            call_count = [0, 0, 0]
            await activity_environment.client.execute_workflow(
                SyncVectorsWorkflow.run,
                SyncVectorsInputs(
                    start_dt=timezone.now().isoformat(),
                    summarize_batch_size=1,
                    embed_batch_size=1,
                    insert_batch_size=1,
                    delay_between_batches=0,
                ),
                id=str(uuid.uuid4()),
                task_queue=settings.TEMPORAL_TASK_QUEUE,
            )
            assert call_count == [1, 3, 4]


@pytest.mark.asyncio
async def test_actions_workflow_retries_on_errors():
    call_count = [0, 0, 0]

    @activity.defn(name="get_approximate_actions_count")
    async def get_approximate_actions_count_mocked(inputs: GetApproximateActionsCountInputs) -> int:
        call_count[0] += 1
        if call_count[0] < 3:
            raise Exception("Test error")
        return 3

    @activity.defn(name="batch_summarize_actions")
    async def batch_summarize_and_embed_actions_mocked(inputs: BatchSummarizeActionsInputs) -> None:
        call_count[1] += 1
        if call_count[1] < 3:
            raise Exception("Test error")

    @activity.defn(name="batch_embed_and_sync_actions")
    async def sync_action_vectors_for_team_mocked(
        inputs: BatchEmbedAndSyncActionsInputs,
    ) -> BatchEmbedAndSyncActionsOutputs:
        call_count[2] += 1
        if call_count[2] < 3:
            raise Exception("Test error")
        return BatchEmbedAndSyncActionsOutputs(has_more=False)

    async with await WorkflowEnvironment.start_time_skipping() as activity_environment:
        async with Worker(
            activity_environment.client,
            task_queue=settings.TEMPORAL_TASK_QUEUE,
            workflows=[SyncVectorsWorkflow],
            activities=[
                get_approximate_actions_count_mocked,
                batch_summarize_and_embed_actions_mocked,
                sync_action_vectors_for_team_mocked,
            ],
            workflow_runner=UnsandboxedWorkflowRunner(),
        ):
            await activity_environment.client.execute_workflow(
                SyncVectorsWorkflow.run,
                SyncVectorsInputs(start_dt=timezone.now().isoformat(), delay_between_batches=0),
                id=str(uuid.uuid4()),
                task_queue=settings.TEMPORAL_TASK_QUEUE,
            )
            assert call_count == [3, 3, 3]


@pytest.mark.asyncio
async def test_actions_workflow_cancels():
    call_count = [0, 0, 0]

    @activity.defn(name="get_approximate_actions_count")
    async def get_approximate_actions_count_mocked(inputs: GetApproximateActionsCountInputs) -> int:
        call_count[0] += 1
        raise Exception("Test error")

    @activity.defn(name="batch_summarize_actions")
    async def batch_summarize_and_embed_actions_mocked(inputs: BatchSummarizeActionsInputs) -> None:
        pass

    @activity.defn(name="batch_embed_and_sync_actions")
    async def sync_action_vectors_for_team_mocked(
        inputs: BatchEmbedAndSyncActionsInputs,
    ) -> BatchEmbedAndSyncActionsOutputs:
        return BatchEmbedAndSyncActionsOutputs(has_more=False)

    async with await WorkflowEnvironment.start_time_skipping() as activity_environment:
        async with Worker(
            activity_environment.client,
            task_queue=settings.TEMPORAL_TASK_QUEUE,
            workflows=[SyncVectorsWorkflow],
            activities=[
                get_approximate_actions_count_mocked,
                batch_summarize_and_embed_actions_mocked,
                sync_action_vectors_for_team_mocked,
            ],
            workflow_runner=UnsandboxedWorkflowRunner(),
        ):
            with pytest.raises(WorkflowFailureError):
                await activity_environment.client.execute_workflow(
                    SyncVectorsWorkflow.run,
                    SyncVectorsInputs(start_dt=timezone.now().isoformat(), delay_between_batches=0),
                    id=str(uuid.uuid4()),
                    task_queue=settings.TEMPORAL_TASK_QUEUE,
                )
            assert call_count == [3, 0, 0]


@patch("cohere.AsyncClientV2.embed")
@pytest.mark.django_db
@pytest.mark.asyncio
async def test_updates_embedding_version(embeddings_mock, cohere_mock, ateam):
    start_dt = timezone.now()
    actions = await _create_actions_with_embedding_version(ateam, start_dt)

    async with await WorkflowEnvironment.start_time_skipping() as activity_environment:
        embeddings_mock.return_value = EmbeddingsByTypeEmbedResponse(
            embeddings={"float_": [[0.1, 0.1], [0.2, 0.2], [0.3, 0.3]]},
            id="test",
            texts=["Test1", "Test2", "Test3"],
        )

        async with Worker(
            activity_environment.client,
            task_queue=settings.TEMPORAL_TASK_QUEUE,
            workflows=[SyncVectorsWorkflow],
            activities=[
                get_approximate_actions_count,
                batch_summarize_actions,
                batch_embed_and_sync_actions,
            ],
            workflow_runner=UnsandboxedWorkflowRunner(),
        ):
            await activity_environment.client.execute_workflow(
                SyncVectorsWorkflow.run,
                SyncVectorsInputs(start_dt=start_dt.isoformat(), delay_between_batches=0, embedding_version=2),
                id=str(uuid.uuid4()),
                task_queue=settings.TEMPORAL_TASK_QUEUE,
            )

            rows = _query_pg_embeddings()
            assert len(rows) == 3
            assert {str(actions[0].id), str(actions[1].id), str(actions[2].id)} == {
                action.id for action in parse_records(rows)
            }

            for action in actions:
                await action.arefresh_from_db()
                assert action.embedding_version == 2
