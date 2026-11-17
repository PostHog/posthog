import json
import uuid
from datetime import timedelta
from itertools import cycle
from typing import Annotated, Any

import pytest
from unittest.mock import patch

from django.conf import settings
from django.utils import timezone

import pytest_asyncio
from asgiref.sync import sync_to_async
from azure.ai.inference.aio import EmbeddingsClient
from azure.ai.inference.models import EmbeddingItem, EmbeddingsResult, EmbeddingsUsage
from azure.core.credentials import AzureKeyCredential
from azure.core.exceptions import HttpResponseError as AzureHttpResponseError
from pydantic import BaseModel, PlainValidator
from temporalio import activity
from temporalio.client import WorkflowFailureError
from temporalio.testing import WorkflowEnvironment
from temporalio.worker import UnsandboxedWorkflowRunner, Worker

from posthog.clickhouse.client import sync_execute
from posthog.models.ai.pg_embeddings import TRUNCATE_PG_EMBEDDINGS_TABLE_SQL
from posthog.temporal.ai.sync_vectors import (
    BatchEmbedAndSyncActionsInputs,
    BatchEmbedAndSyncActionsOutputs,
    BatchSummarizeActionsInputs,
    EmbeddingVersion,
    GetApproximateActionsCountInputs,
    SyncVectorsInputs,
    SyncVectorsWorkflow,
    batch_embed_actions,
    batch_embed_and_sync_actions,
    batch_summarize_actions,
    get_approximate_actions_count,
    sync_action_vectors,
)
from posthog.temporal.common.clickhouse import get_client

from products.actions.backend.facade.contracts import Action
from products.actions.backend.facade.testing import acreate_action, aget_action_ai_state, delete_action


@pytest.fixture(autouse=True)
def cleanup():
    yield

    try:
        sync_execute(TRUNCATE_PG_EMBEDDINGS_TABLE_SQL())
    except:
        pass


ACTION_FIELDS: tuple[dict[str, Any], ...] = (
    {
        "name": "Completed onboarding",
        "description": "Filters users who successfully completed onboarding",
        "steps_json": [{"event": "onboarding completed"}],
    },
    {
        "name": "Requested a quote",
        "description": "Display users who wanted to purchase the product",
        "steps_json": [{"href": "/subscribe", "href_matching": "exact", "event": "pressed button"}],
    },
    {
        "name": "Interacted with the assistant",
        "description": "Cohort of events when users interacted with the AI assistant",
        "steps_json": [{"event": "message sent"}, {"url": "/chat", "event": "$pageview"}],
    },
)


async def _plant_actions(team, fields: list[dict[str, Any]]) -> list[Action]:
    # One at a time, so ids ascend in the order given.
    return [await acreate_action(team=team, **action_fields) for action_fields in fields]


async def _remove_actions(actions: list[Action]) -> None:
    for action in actions:
        await sync_to_async(delete_action)(action)


@pytest_asyncio.fixture
async def actions(ateam):
    planted = await _plant_actions(ateam, list(ACTION_FIELDS))
    yield planted
    await _remove_actions(planted)


@pytest_asyncio.fixture
async def summarized_actions(ateam):
    dt = timezone.now()
    summaries = ["Test summary 1", "Test summary 2", "Test summary 3"]
    planted = await _plant_actions(
        ateam,
        [
            {**action_fields, "last_summarized_at": dt, "summary": summary}
            for action_fields, summary in zip(ACTION_FIELDS, summaries)
        ],
    )
    yield planted
    await _remove_actions(planted)


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


def _wrap_embeddings_response(embeddings: list[list[float]]) -> EmbeddingsResult:
    return EmbeddingsResult(
        id="test",
        model="test",
        usage=EmbeddingsUsage(prompt_tokens=1, total_tokens=1),
        data=[EmbeddingItem(embedding=embedding, index=index) for index, embedding in enumerate(embeddings)],
    )


@pytest.fixture
def azure_mock():
    with patch(
        "posthog.temporal.ai.sync_vectors.get_async_azure_embeddings_client",
        side_effect=lambda: EmbeddingsClient(
            endpoint="https://test.services.ai.azure.com/models", credential=AzureKeyCredential("test")
        ),
    ) as mock:
        yield mock


def _query_pg_embeddings() -> list[tuple]:
    return sync_execute("SELECT * FROM pg_embeddings ORDER BY id")


@pytest.mark.django_db
@pytest.mark.asyncio
async def test_get_approximate_actions_count(actions):
    res = await get_approximate_actions_count(GetApproximateActionsCountInputs(start_dt=timezone.now().isoformat()))
    assert res == 3


@pytest.mark.django_db
@pytest.mark.asyncio
async def test_basic_batch_summarization(azure_mock, actions):
    with (
        patch("posthog.temporal.ai.sync_vectors.abatch_summarize_actions") as summarize_mock,
    ):
        summarize_mock.return_value = ["Test1"]

        start_dt = timezone.now()
        await batch_summarize_actions(
            BatchSummarizeActionsInputs(offset=0, batch_size=1, start_dt=start_dt.isoformat())
        )
        assert summarize_mock.call_count == 1

        updated_state = await aget_action_ai_state(actions[0])
        assert updated_state.summary == "Test1"
        assert updated_state.last_summarized_at == start_dt
        assert updated_state.embedding_last_synced_at is None

        for action in actions[1:]:
            state = await aget_action_ai_state(action)
            assert state.summary is None
            assert state.last_summarized_at is None
            assert state.embedding_last_synced_at is None

        summarize_mock.return_value = ["Test2", "Test3"]

        await batch_summarize_actions(
            BatchSummarizeActionsInputs(offset=1, batch_size=10, start_dt=start_dt.isoformat())
        )
        assert summarize_mock.call_count == 2
        expected_texts = ["Test1", "Test2", "Test3"]

        for action, expected_text in zip(actions, expected_texts):
            state = await aget_action_ai_state(action)
            assert state.summary == expected_text
            assert state.last_summarized_at == start_dt
            assert state.embedding_last_synced_at is None


@pytest.mark.django_db
@pytest.mark.asyncio
async def test_batch_summarize_with_errors(azure_mock, actions: list[Action], ateam):
    with (
        patch("posthog.temporal.ai.sync_vectors.abatch_summarize_actions") as summarize_mock,
    ):
        summarize_mock.return_value = ["Test1", "Test2", ValueError()]

        start_dt = timezone.now()
        await batch_summarize_actions(
            BatchSummarizeActionsInputs(offset=0, batch_size=96, start_dt=start_dt.isoformat())
        )
        updated_actions = [await aget_action_ai_state(action) for action in actions]
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

        updated_actions = [await aget_action_ai_state(action) for action in actions]
        assert len(updated_actions) == 3
        assert ("Test1", "Test2", "Test3") == tuple(action.summary for action in updated_actions)
        assert [start_dt, start_dt, new_start_dt] == [action.last_summarized_at for action in updated_actions]


@pytest.mark.django_db
@pytest.mark.asyncio
async def test_batch_embedding(azure_mock, actions):
    with (
        patch("azure.ai.inference.aio.EmbeddingsClient.embed") as embeddings_mock,
    ):
        # batch_size=1, one call
        embeddings_mock.return_value = _wrap_embeddings_response([[0.12, 0.054]])

        res = await batch_embed_actions([{"summary": "Test1"}], batch_size=1)
        assert embeddings_mock.call_count == 1
        assert res == [({"summary": "Test1"}, [0.12, 0.054])]

        embeddings_mock.reset_mock()

        # batch_size=2, one call
        embeddings_mock.return_value = _wrap_embeddings_response([[0.1, 0.7], [0.8, 0.6663]])

        res = await batch_embed_actions([{"summary": "Test2"}, {"summary": "Test3"}], batch_size=2)
        assert embeddings_mock.call_count == 1
        assert res == [({"summary": "Test2"}, [0.1, 0.7]), ({"summary": "Test3"}, [0.8, 0.6663])]

        embeddings_mock.reset_mock()

        # batch_size=2, two parallel calls
        embeddings_mock.return_value = _wrap_embeddings_response([[0.12, 0.054], [0.1, 0.7]])

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
async def test_batch_embedding_with_errors(azure_mock, actions: list[Action]):
    with patch("azure.ai.inference.aio.EmbeddingsClient.embed") as embeddings_mock:
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
                raise AzureHttpResponseError
            return _wrap_embeddings_response([[0.12, 0.054]])

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
async def test_clickhouse_sync_single_batch(summarized_actions, summarized_actions_with_embeddings, ateam):
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
            assert (await aget_action_ai_state(action)).embedding_last_synced_at == start_dt

        with patch("posthog.temporal.common.clickhouse.ClickHouseClient.execute_query") as mock:
            await sync_action_vectors(client, summarized_actions_with_embeddings, 10, start_dt)
            assert mock.call_count == 1


@pytest.mark.django_db
@pytest.mark.asyncio
async def test_clickhouse_sync_multiple_batches(summarized_actions, summarized_actions_with_embeddings, ateam):
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
            assert (await aget_action_ai_state(action)).embedding_last_synced_at == start_dt

        with patch("posthog.temporal.common.clickhouse.ClickHouseClient.execute_query") as mock:
            await sync_action_vectors(client, summarized_actions_with_embeddings, 1, start_dt)
            assert mock.call_count == 3


@pytest.mark.django_db
@pytest.mark.asyncio
async def test_batch_embed_and_sync_actions(azure_mock, summarized_actions, ateam):
    start_dt = timezone.now()
    embeddings = [[0.12, 0.054], [0.1, 0.7], [0.8, 0.6663]]
    with (
        patch("azure.ai.inference.aio.EmbeddingsClient.embed") as embeddings_mock,
        patch("temporalio.activity.heartbeat"),
    ):
        embeddings_mock.return_value = _wrap_embeddings_response(embeddings)
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

        with patch("temporalio.activity.heartbeat"):
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
async def test_batch_embed_and_sync_actions_in_batches(azure_mock, summarized_actions, ateam):
    start_dt = timezone.now()
    embeddings = [[0.12, 0.054]]

    with (
        patch("azure.ai.inference.aio.EmbeddingsClient.embed") as embeddings_mock,
        patch("temporalio.activity.heartbeat"),
    ):
        embeddings_mock.return_value = _wrap_embeddings_response(embeddings)
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
async def test_batch_embed_and_sync_actions_filters_out_actions(azure_mock, ateam):
    start_dt = timezone.now()
    embeddings = [[0.1, 0.1], [0.2, 0.2], [0.3, 0.3]]

    # Create actions with different last_summarized_at values
    actions = await _plant_actions(
        ateam,
        [
            {
                "name": "Before start 1",
                "last_summarized_at": start_dt - timedelta(days=1),
                "summary": "Test1",
            },  # Should be included
            {
                "name": "Before start 2",
                "last_summarized_at": start_dt - timedelta(days=1),
                "embedding_last_synced_at": start_dt - timedelta(days=2),
                "summary": "Test2",
            },  # Should be included
            {"name": "At start", "last_summarized_at": start_dt, "summary": "Test3"},  # Should be included
            {
                "name": "After start",
                "last_summarized_at": start_dt + timedelta(days=1),
                "summary": "Test4",
            },  # Should not be included
        ],
    )

    with (
        patch("azure.ai.inference.aio.EmbeddingsClient.embed") as embeddings_mock,
        patch("temporalio.activity.heartbeat"),
    ):
        embeddings_mock.return_value = _wrap_embeddings_response(embeddings)
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
async def test_batch_embed_and_sync_actions_filters_out_actions_with_no_summary(ateam):
    start_dt = timezone.now()

    # Create actions with different last_summarized_at values
    await _plant_actions(
        ateam, [{"name": "Before start 1", "last_summarized_at": start_dt - timedelta(days=1)}]
    )  # Has no summary, so it is never embedded

    with patch("temporalio.activity.heartbeat"):
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


async def _create_actions_with_embedding_version(ateam, start_dt) -> list[Action]:
    # Create actions with different last_summarized_at values
    return await _plant_actions(
        ateam,
        [
            {
                "name": "Before start 1",
                "last_summarized_at": start_dt - timedelta(days=1),
                "embedding_last_synced_at": start_dt - timedelta(hours=8),  # shouldn't be included by time filters
                "summary": "Test1",
                "embedding_version": None,
            },  # Should be included
            {
                "name": "Before start 2",
                "last_summarized_at": start_dt - timedelta(days=1),
                "embedding_last_synced_at": start_dt - timedelta(hours=8),  # shouldn't be included by time filters
                "summary": "Test2",
                "embedding_version": 1,
            },  # Should be included
            {
                "name": "Before start 2",
                "last_summarized_at": start_dt - timedelta(days=1),
                "embedding_last_synced_at": start_dt - timedelta(days=2),
                "summary": "Test2",
                "embedding_version": 2,  # Should not be included by the version filter
            },  # Should be included
        ],
    )


@pytest.mark.django_db
@pytest.mark.asyncio
async def test_batch_embed_and_sync_actions_embedding_version(azure_mock, ateam):
    start_dt = timezone.now()
    embeddings = [[0.1, 0.1], [0.2, 0.2], [0.3, 0.3]]

    actions = await _create_actions_with_embedding_version(ateam, start_dt)

    with (
        patch("azure.ai.inference.aio.EmbeddingsClient.embed") as embeddings_mock,
        patch("temporalio.activity.heartbeat"),
    ):
        embeddings_mock.return_value = _wrap_embeddings_response(embeddings)

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
        assert {
            action.properties["embedding_version"] if action.properties else None for action in parse_records(rows)
        } == {2}

        for action in actions:
            assert (await aget_action_ai_state(action)).embedding_version == 2


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


@patch("azure.ai.inference.aio.EmbeddingsClient.embed")
@pytest.mark.django_db
@pytest.mark.asyncio
async def test_updates_embedding_version(embeddings_mock, azure_mock, ateam):
    start_dt = timezone.now()
    actions = await _create_actions_with_embedding_version(ateam, start_dt)

    async with await WorkflowEnvironment.start_time_skipping() as activity_environment:
        embeddings_mock.return_value = _wrap_embeddings_response([[0.1, 0.1], [0.2, 0.2], [0.3, 0.3]])

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
                SyncVectorsInputs(
                    start_dt=start_dt.isoformat(),
                    delay_between_batches=0,
                    embedding_versions=EmbeddingVersion(actions=2),
                ),
                id=str(uuid.uuid4()),
                task_queue=settings.TEMPORAL_TASK_QUEUE,
            )

            rows = _query_pg_embeddings()
            assert len(rows) == 3
            assert {str(actions[0].id), str(actions[1].id), str(actions[2].id)} == {
                action.id for action in parse_records(rows)
            }

            for action in actions:
                assert (await aget_action_ai_state(action)).embedding_version == 2


@pytest.mark.asyncio
async def test_workflow_not_retried_on_authentication_error():
    """Test that the workflow fails immediately on ClientAuthenticationError without retries."""
    call_count = [0, 0, 0]

    @activity.defn(name="get_approximate_actions_count")
    async def get_approximate_actions_count_mocked(inputs: GetApproximateActionsCountInputs) -> int:
        call_count[0] += 1
        return 0  # No actions to summarize

    @activity.defn(name="batch_summarize_actions")
    async def batch_summarize_actions_mocked(inputs: BatchSummarizeActionsInputs) -> None:
        call_count[1] += 1

    @activity.defn(name="batch_embed_and_sync_actions")
    async def batch_embed_and_sync_actions_mocked(
        inputs: BatchEmbedAndSyncActionsInputs,
    ) -> BatchEmbedAndSyncActionsOutputs:
        call_count[2] += 1
        # Raise ClientAuthenticationError which should not be retried
        from azure.core.exceptions import ClientAuthenticationError

        raise ClientAuthenticationError("Authentication failed")

    async with await WorkflowEnvironment.start_time_skipping() as activity_environment:
        async with Worker(
            activity_environment.client,
            task_queue=settings.TEMPORAL_TASK_QUEUE,
            workflows=[SyncVectorsWorkflow],
            activities=[
                get_approximate_actions_count_mocked,
                batch_summarize_actions_mocked,
                batch_embed_and_sync_actions_mocked,
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

            # Should be called only once (no retries) due to non_retryable_error_types
            assert call_count == [1, 0, 1]


@pytest.mark.asyncio
async def test_workflow_retried_on_rate_limit_error():
    """Test that the workflow retries on rate limit HttpResponseError (429)."""
    call_count = [0, 0, 0]

    @activity.defn(name="get_approximate_actions_count")
    async def get_approximate_actions_count_mocked(inputs: GetApproximateActionsCountInputs) -> int:
        call_count[0] += 1
        return 0  # No actions to summarize

    @activity.defn(name="batch_summarize_actions")
    async def batch_summarize_actions_mocked(inputs: BatchSummarizeActionsInputs) -> None:
        call_count[1] += 1

    @activity.defn(name="batch_embed_and_sync_actions")
    async def batch_embed_and_sync_actions_mocked(
        inputs: BatchEmbedAndSyncActionsInputs,
    ) -> BatchEmbedAndSyncActionsOutputs:
        call_count[2] += 1
        if call_count[2] < 3:
            # Raise rate limit error which should be retried
            from azure.core.exceptions import HttpResponseError

            response = type("MockResponse", (), {"status_code": 429})()
            raise HttpResponseError(response=response)
        return BatchEmbedAndSyncActionsOutputs(has_more=False)

    async with await WorkflowEnvironment.start_time_skipping() as activity_environment:
        async with Worker(
            activity_environment.client,
            task_queue=settings.TEMPORAL_TASK_QUEUE,
            workflows=[SyncVectorsWorkflow],
            activities=[
                get_approximate_actions_count_mocked,
                batch_summarize_actions_mocked,
                batch_embed_and_sync_actions_mocked,
            ],
            workflow_runner=UnsandboxedWorkflowRunner(),
        ):
            await activity_environment.client.execute_workflow(
                SyncVectorsWorkflow.run,
                SyncVectorsInputs(start_dt=timezone.now().isoformat(), delay_between_batches=0),
                id=str(uuid.uuid4()),
                task_queue=settings.TEMPORAL_TASK_QUEUE,
            )

            # Should be retried 3 times (due to retry policy with maximum_attempts=3)
            assert call_count == [1, 0, 3]


@pytest.mark.django_db
@pytest.mark.asyncio
async def test_heartbeat_called_during_embedding_process(azure_mock, summarized_actions, ateam):
    """Test that heartbeat is called during the batch_embed_and_sync_actions activity."""
    start_dt = timezone.now()
    embeddings = [[0.12, 0.054], [0.1, 0.7], [0.8, 0.6663]]

    with (
        patch("azure.ai.inference.aio.EmbeddingsClient.embed") as embeddings_mock,
        patch("temporalio.activity.heartbeat") as heartbeat_mock,
    ):
        embeddings_mock.return_value = _wrap_embeddings_response(embeddings)

        await batch_embed_and_sync_actions(
            BatchEmbedAndSyncActionsInputs(
                start_dt=start_dt.isoformat(),
                insert_batch_size=10,
                embeddings_batch_size=10,
                max_parallel_requests=4,
            )
        )

        # Heartbeat should be called at least twice:
        # 1. At the start of the embedding loop
        # 2. Before syncing vectors
        assert heartbeat_mock.call_count >= 2


@pytest.mark.django_db
@pytest.mark.asyncio
async def test_heartbeat_called_multiple_times_with_large_batch(azure_mock, ateam):
    """Test that heartbeat is called multiple times when processing larger batches."""
    start_dt = timezone.now()

    # Create more actions to process multiple iterations
    await _plant_actions(
        ateam,
        [
            {
                "name": f"Action {i}",
                "description": f"Description {i}",
                "last_summarized_at": start_dt - timedelta(days=1),
                "summary": f"Summary {i}",
                "steps_json": [{"event": f"event_{i}"}],
            }
            for i in range(10)
        ],
    )

    embeddings = [[0.1, 0.1] for _ in range(10)]

    with (
        patch("azure.ai.inference.aio.EmbeddingsClient.embed") as embeddings_mock,
        patch("temporalio.activity.heartbeat") as heartbeat_mock,
    ):
        embeddings_mock.return_value = _wrap_embeddings_response(embeddings)

        await batch_embed_and_sync_actions(
            BatchEmbedAndSyncActionsInputs(
                start_dt=start_dt.isoformat(),
                insert_batch_size=5,  # Small batch size to trigger multiple iterations
                embeddings_batch_size=2,
                max_parallel_requests=2,
            )
        )

        # With a small insert_batch_size and multiple actions, we should see more heartbeat calls
        # as the loop iterates multiple times (at least 3: one per iteration + one before sync)
        assert heartbeat_mock.call_count >= 3


@pytest.mark.django_db
@pytest.mark.asyncio
async def test_heartbeat_called_even_when_no_actions(ateam):
    """Test that heartbeat is called once even when there are no actions to process."""
    start_dt = timezone.now()

    with patch("temporalio.activity.heartbeat") as heartbeat_mock:
        result = await batch_embed_and_sync_actions(
            BatchEmbedAndSyncActionsInputs(
                start_dt=start_dt.isoformat(),
                insert_batch_size=10,
                embeddings_batch_size=10,
                max_parallel_requests=4,
            )
        )

        # Heartbeat is called once at the start of the loop even when no actions exist
        assert heartbeat_mock.call_count == 1
        assert result.has_more is False


@pytest.mark.django_db
@pytest.mark.asyncio
async def test_heartbeat_called_before_sync_when_actions_exist(azure_mock, summarized_actions, ateam):
    """Test that heartbeat is specifically called before the sync_action_vectors call."""
    start_dt = timezone.now()
    embeddings = [[0.12, 0.054]]

    with (
        patch("azure.ai.inference.aio.EmbeddingsClient.embed") as embeddings_mock,
        patch("temporalio.activity.heartbeat") as heartbeat_mock,
        patch("posthog.temporal.ai.sync_vectors.sync_action_vectors") as sync_mock,
    ):
        embeddings_mock.return_value = _wrap_embeddings_response(embeddings)
        sync_mock.return_value = None

        await batch_embed_and_sync_actions(
            BatchEmbedAndSyncActionsInputs(
                start_dt=start_dt.isoformat(),
                insert_batch_size=10,
                embeddings_batch_size=10,
                max_parallel_requests=4,
            )
        )

        # Verify sync was called
        assert sync_mock.call_count == 1

        # Verify heartbeat was called at least once before sync
        assert heartbeat_mock.call_count >= 1
