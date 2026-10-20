import logging
from datetime import timedelta
from typing import TypedDict

import pytest

from temporalio import activity
from temporalio.client import WorkflowFailureError
from temporalio.exceptions import ApplicationError
from temporalio.testing import WorkflowEnvironment
from temporalio.worker import UnsandboxedWorkflowRunner, Worker

from posthog.temporal.common.base import PostHogWorkflow

from products.business_knowledge.backend.temporal.coordinator import (
    _CLASSIFY_CHUNK_SIZE,
    _CLASSIFY_DRAIN_MAX_CHUNKS,
    _EMBED_CHUNK_SIZE,
    BusinessKnowledgeIngestSourceWorkflow,
    BusinessKnowledgeRefreshCoordinatorWorkflowV2,
    BusinessKnowledgeRefreshSourceWorkflow,
    IngestSourceInputs,
    RefreshSourceInputs,
    ReleaseFailedSourceInputs,
)


class _ClassifyStub(TypedDict):
    classified: int
    unsafe: int
    scanned: int
    tried_ids: list[str]


@pytest.mark.asyncio
async def test_coordinator_keeps_taking_index_chunks_until_the_queue_is_short() -> None:
    # A wedged workflow task retries forever at INFO. Fail the run instead.
    logging.getLogger("temporalio.activity").setLevel(logging.INFO)
    logging.getLogger("temporalio.workflow").setLevel(logging.INFO)

    classify_script: list[_ClassifyStub] = [
        {
            "classified": _CLASSIFY_CHUNK_SIZE,
            "unsafe": 1,
            "scanned": _CLASSIFY_CHUNK_SIZE,
            "tried_ids": ["doc-1"],
        },
        {
            "classified": _CLASSIFY_CHUNK_SIZE,
            "unsafe": 0,
            "scanned": _CLASSIFY_CHUNK_SIZE,
            "tried_ids": ["doc-2"],
        },
        {"classified": 3, "unsafe": 0, "scanned": 3, "tried_ids": ["doc-3"]},
    ]
    embed_script = [
        {
            "documents_embedded": _EMBED_CHUNK_SIZE,
            "chunks_emitted": _EMBED_CHUNK_SIZE * 2,
            "scanned": _EMBED_CHUNK_SIZE,
        },
        {"documents_embedded": 0, "chunks_emitted": 0, "scanned": _EMBED_CHUNK_SIZE},
    ]
    calls: list[str] = []
    classify_excludes: list[list[str]] = []

    @activity.defn(name="sweep_tombstoned_documents_activity")
    async def sweep() -> int:
        return 0

    @activity.defn(name="list_due_refresh_sources_activity")
    async def list_due() -> list[tuple[int, str, str]]:
        return []

    @activity.defn(name="classify_pending_documents_activity")
    async def classify(exclude_ids: list[str]) -> _ClassifyStub:
        calls.append("classify")
        classify_excludes.append(exclude_ids)
        if classify_script:
            return classify_script.pop(0)
        return {"classified": 0, "unsafe": 0, "scanned": 0, "tried_ids": []}

    @activity.defn(name="reconcile_embeddings_activity")
    async def reconcile() -> dict[str, int]:
        return {"reconciled": 0, "re_nulled": 0}

    @activity.defn(name="emit_pending_embeddings_activity")
    async def emit() -> dict[str, int]:
        calls.append("emit")
        if embed_script:
            return embed_script.pop(0)
        return {"documents_embedded": 0, "chunks_emitted": 0, "scanned": 0}

    @activity.defn(name="refresh_aging_embeddings_activity")
    async def refresh_aging() -> dict[str, int]:
        return {"documents_refreshed": 0, "chunks_reemitted": 0}

    async with await WorkflowEnvironment.start_time_skipping() as environment:
        async with Worker(
            environment.client,
            task_queue="bk-refresh-coordinator-test",
            workflows=[BusinessKnowledgeRefreshCoordinatorWorkflowV2],
            activities=[sweep, list_due, classify, reconcile, emit, refresh_aging],
            workflow_runner=UnsandboxedWorkflowRunner(),
        ):
            result = await environment.client.execute_workflow(
                BusinessKnowledgeRefreshCoordinatorWorkflowV2.run,
                id="bk-refresh-coordinator-drain-test",
                task_queue="bk-refresh-coordinator-test",
                execution_timeout=timedelta(minutes=2),
            )

    assert calls == ["classify", "emit", "classify", "emit", "classify"]
    assert classify_excludes == [[], ["doc-1"], ["doc-1", "doc-2"]]
    assert result["documents_classified"] == _CLASSIFY_CHUNK_SIZE * 2 + 3
    assert result["documents_unsafe"] == 1
    assert result["documents_embedded"] == _EMBED_CHUNK_SIZE
    assert result["chunks_emitted"] == _EMBED_CHUNK_SIZE * 2


@pytest.mark.asyncio
async def test_index_drain_stops_at_the_chunk_ceiling() -> None:
    logging.getLogger("temporalio.activity").setLevel(logging.INFO)
    logging.getLogger("temporalio.workflow").setLevel(logging.INFO)

    classify_calls = 0
    embed_calls = 0

    @activity.defn(name="sweep_tombstoned_documents_activity")
    async def sweep() -> int:
        return 0

    @activity.defn(name="list_due_refresh_sources_activity")
    async def list_due() -> list[tuple[int, str, str]]:
        return []

    @activity.defn(name="classify_pending_documents_activity")
    async def classify(_exclude_ids: list[str]) -> _ClassifyStub:
        nonlocal classify_calls
        classify_calls += 1
        return {
            "classified": _CLASSIFY_CHUNK_SIZE,
            "unsafe": 0,
            "scanned": _CLASSIFY_CHUNK_SIZE,
            "tried_ids": [f"doc-{classify_calls}"],
        }

    @activity.defn(name="reconcile_embeddings_activity")
    async def reconcile() -> dict[str, int]:
        return {"reconciled": 0, "re_nulled": 0}

    @activity.defn(name="emit_pending_embeddings_activity")
    async def emit() -> dict[str, int]:
        nonlocal embed_calls
        embed_calls += 1
        return {
            "documents_embedded": _EMBED_CHUNK_SIZE,
            "chunks_emitted": _EMBED_CHUNK_SIZE,
            "scanned": _EMBED_CHUNK_SIZE,
        }

    @activity.defn(name="refresh_aging_embeddings_activity")
    async def refresh_aging() -> dict[str, int]:
        return {"documents_refreshed": 0, "chunks_reemitted": 0}

    async with await WorkflowEnvironment.start_time_skipping() as environment:
        async with Worker(
            environment.client,
            task_queue="bk-refresh-coordinator-ceiling-test",
            workflows=[BusinessKnowledgeRefreshCoordinatorWorkflowV2],
            activities=[sweep, list_due, classify, reconcile, emit, refresh_aging],
            workflow_runner=UnsandboxedWorkflowRunner(),
        ):
            result = await environment.client.execute_workflow(
                BusinessKnowledgeRefreshCoordinatorWorkflowV2.run,
                id="bk-refresh-coordinator-ceiling-test",
                task_queue="bk-refresh-coordinator-ceiling-test",
                execution_timeout=timedelta(minutes=2),
            )

    assert classify_calls == _CLASSIFY_DRAIN_MAX_CHUNKS
    assert embed_calls == _CLASSIFY_DRAIN_MAX_CHUNKS
    assert result["documents_classified"] == _CLASSIFY_CHUNK_SIZE * _CLASSIFY_DRAIN_MAX_CHUNKS
    assert result["documents_embedded"] == _EMBED_CHUNK_SIZE * _CLASSIFY_DRAIN_MAX_CHUNKS


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "workflow_class, inputs, failing_activity_name, expected_discard_documents",
    [
        (
            BusinessKnowledgeRefreshSourceWorkflow,
            RefreshSourceInputs(team_id=1, source_id="source-1", claim_id="claim-1"),
            "execute_refresh_knowledge_source_activity",
            False,
        ),
        (
            BusinessKnowledgeIngestSourceWorkflow,
            IngestSourceInputs(team_id=1, source_id="source-1", claim_id="claim-1"),
            "ingest_knowledge_source_activity",
            True,
        ),
    ],
)
async def test_source_workflow_releases_the_source_when_its_activity_fails(
    workflow_class: type[PostHogWorkflow],
    inputs: RefreshSourceInputs | IngestSourceInputs,
    failing_activity_name: str,
    expected_discard_documents: bool,
) -> None:
    logging.getLogger("temporalio.activity").setLevel(logging.INFO)
    logging.getLogger("temporalio.workflow").setLevel(logging.INFO)

    released: list[ReleaseFailedSourceInputs] = []

    @activity.defn(name=failing_activity_name)
    async def failing(_inputs: RefreshSourceInputs) -> dict[str, str]:
        raise ApplicationError("text fields cannot contain NUL (0x00) bytes", non_retryable=True)

    @activity.defn(name="release_failed_source_activity")
    async def release(released_inputs: ReleaseFailedSourceInputs) -> None:
        released.append(released_inputs)

    async with await WorkflowEnvironment.start_time_skipping() as environment:
        async with Worker(
            environment.client,
            task_queue="bk-source-release-test",
            workflows=[workflow_class],
            activities=[failing, release],
            workflow_runner=UnsandboxedWorkflowRunner(),
        ):
            with pytest.raises(WorkflowFailureError):
                await environment.client.execute_workflow(
                    workflow_class.get_name(),
                    inputs,
                    id="bk-source-release-test",
                    task_queue="bk-source-release-test",
                    execution_timeout=timedelta(minutes=2),
                )

    assert released == [
        ReleaseFailedSourceInputs(
            team_id=1, source_id="source-1", discard_documents=expected_discard_documents, claim_id="claim-1"
        )
    ]


@pytest.mark.asyncio
async def test_coordinator_releases_only_the_source_whose_refresh_failed() -> None:
    logging.getLogger("temporalio.activity").setLevel(logging.INFO)
    logging.getLogger("temporalio.workflow").setLevel(logging.INFO)

    released: list[ReleaseFailedSourceInputs] = []
    execute_attempts_by_source_id: dict[str, int] = {}
    claim_ids_by_source_id: dict[str, str | None] = {}

    @activity.defn(name="sweep_tombstoned_documents_activity")
    async def sweep() -> int:
        return 0

    @activity.defn(name="list_due_refresh_sources_activity")
    async def list_due() -> list[tuple[int, str, str]]:
        return [(1, "broken", "broken.example.com"), (1, "healthy", "healthy.example.com")]

    @activity.defn(name="claim_refresh_source_activity")
    async def claim(inputs: RefreshSourceInputs) -> dict[str, str]:
        claim_ids_by_source_id[inputs.source_id] = inputs.claim_id
        return {"status": "ok"}

    @activity.defn(name="execute_refresh_knowledge_source_activity")
    async def execute(inputs: RefreshSourceInputs) -> dict[str, str]:
        execute_attempts_by_source_id[inputs.source_id] = execute_attempts_by_source_id.get(inputs.source_id, 0) + 1
        if inputs.source_id == "broken":
            raise ApplicationError("text fields cannot contain NUL (0x00) bytes")
        return {"status": "ok"}

    @activity.defn(name="release_failed_source_activity")
    async def release(released_inputs: ReleaseFailedSourceInputs) -> None:
        released.append(released_inputs)

    @activity.defn(name="classify_pending_documents_activity")
    async def classify(_exclude_ids: list[str]) -> _ClassifyStub:
        return {"classified": 0, "unsafe": 0, "scanned": 0, "tried_ids": []}

    @activity.defn(name="reconcile_embeddings_activity")
    async def reconcile() -> dict[str, int]:
        return {"reconciled": 0, "re_nulled": 0}

    @activity.defn(name="emit_pending_embeddings_activity")
    async def emit() -> dict[str, int]:
        return {"documents_embedded": 0, "chunks_emitted": 0, "scanned": 0}

    @activity.defn(name="refresh_aging_embeddings_activity")
    async def refresh_aging() -> dict[str, int]:
        return {"documents_refreshed": 0, "chunks_reemitted": 0}

    async with await WorkflowEnvironment.start_time_skipping() as environment:
        async with Worker(
            environment.client,
            task_queue="bk-refresh-coordinator-release-test",
            workflows=[BusinessKnowledgeRefreshCoordinatorWorkflowV2],
            activities=[sweep, list_due, claim, execute, release, classify, reconcile, emit, refresh_aging],
            workflow_runner=UnsandboxedWorkflowRunner(),
        ):
            result = await environment.client.execute_workflow(
                BusinessKnowledgeRefreshCoordinatorWorkflowV2.run,
                id="bk-refresh-coordinator-release-test",
                task_queue="bk-refresh-coordinator-release-test",
                execution_timeout=timedelta(minutes=2),
            )

    assert released == [
        ReleaseFailedSourceInputs(
            team_id=1, source_id="broken", discard_documents=False, claim_id=claim_ids_by_source_id["broken"]
        )
    ]
    assert claim_ids_by_source_id["broken"] is not None
    assert claim_ids_by_source_id["broken"] != claim_ids_by_source_id["healthy"]
    assert execute_attempts_by_source_id == {"broken": 2, "healthy": 1}
    assert result["sources_failed"] == 1
    assert result["sources_refreshed"] == 1
