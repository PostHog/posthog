import logging
from datetime import timedelta

import pytest

from temporalio import activity
from temporalio.testing import WorkflowEnvironment
from temporalio.worker import UnsandboxedWorkflowRunner, Worker

from products.business_knowledge.backend.temporal.coordinator import (
    _CLASSIFY_CHUNK_SIZE,
    _EMBED_CHUNK_SIZE,
    BusinessKnowledgeRefreshCoordinatorWorkflowV2,
)


@pytest.mark.asyncio
async def test_coordinator_keeps_taking_index_chunks_until_the_queue_is_short() -> None:
    # A wedged workflow task retries forever at INFO. Fail the run instead.
    logging.getLogger("temporalio.activity").setLevel(logging.INFO)
    logging.getLogger("temporalio.workflow").setLevel(logging.INFO)

    classify_script = [
        {"classified": _CLASSIFY_CHUNK_SIZE, "unsafe": 1, "scanned": _CLASSIFY_CHUNK_SIZE},
        {"classified": _CLASSIFY_CHUNK_SIZE, "unsafe": 0, "scanned": _CLASSIFY_CHUNK_SIZE},
        {"classified": 3, "unsafe": 0, "scanned": 3},
    ]
    # Second emit chunk is full but stamps nothing, so the run must not spin on it.
    embed_script = [
        {
            "documents_embedded": _EMBED_CHUNK_SIZE,
            "chunks_emitted": _EMBED_CHUNK_SIZE * 2,
            "scanned": _EMBED_CHUNK_SIZE,
        },
        {"documents_embedded": 0, "chunks_emitted": 0, "scanned": _EMBED_CHUNK_SIZE},
    ]
    calls: list[str] = []

    @activity.defn(name="sweep_tombstoned_documents_activity")
    async def sweep() -> int:
        return 0

    @activity.defn(name="list_due_refresh_sources_activity")
    async def list_due() -> list[tuple[int, str, str]]:
        return []

    @activity.defn(name="classify_pending_documents_activity")
    async def classify() -> dict[str, int]:
        calls.append("classify")
        if classify_script:
            return classify_script.pop(0)
        return {"classified": 0, "unsafe": 0, "scanned": 0}

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

    assert calls == ["classify", "emit", "classify", "emit", "classify", "emit"]
    assert result["documents_classified"] == _CLASSIFY_CHUNK_SIZE * 2 + 3
    assert result["documents_unsafe"] == 1
    assert result["documents_embedded"] == _EMBED_CHUNK_SIZE
    assert result["chunks_emitted"] == _EMBED_CHUNK_SIZE * 2
