from __future__ import annotations

import uuid

import pytest
from unittest import mock

import temporalio.worker
from temporalio import activity
from temporalio.testing import WorkflowEnvironment
from temporalio.worker import Worker

from posthog.temporal.session_replay.surfacing_scoring_sweep.constants import WORKFLOW_NAME
from posthog.temporal.session_replay.surfacing_scoring_sweep.types import (
    ChunkResult,
    ChunkSpec,
    ListChunksResult,
    ScoreSessionsBatchInputs,
    ScoreSessionsBatchResult,
)
from posthog.temporal.session_replay.surfacing_scoring_sweep.workflow import ScoreSessionsBatchWorkflow, _summarize


def _plan(chunks: list[ChunkSpec], *, estimated: int = 0) -> ListChunksResult:
    return ListChunksResult(chunks=chunks, estimated_unscored_sessions=estimated)


def _chunk(chunk_id: int, *, of_chunks: int = 4) -> ChunkSpec:
    return ChunkSpec(chunk_id=chunk_id, of_chunks=of_chunks, chunk_size=10, lookback_days=7)


def _as_batch_result(result: ScoreSessionsBatchResult | dict[str, int]) -> ScoreSessionsBatchResult:
    if isinstance(result, ScoreSessionsBatchResult):
        return result
    return ScoreSessionsBatchResult(**result)


class TestSummarize:
    def test_aggregates_scored_and_failed_chunks(self) -> None:
        chunks = [_chunk(0), _chunk(1), _chunk(2)]
        results: list[ChunkResult | BaseException] = [
            ChunkResult(chunk_id=0, scored=3, fetched=4),
            RuntimeError("ch timeout"),
            ChunkResult(chunk_id=2, scored=7, fetched=9),
        ]
        with (
            mock.patch("posthog.temporal.session_replay.surfacing_scoring_sweep.workflow.workflow.logger"),
            mock.patch(
                "posthog.temporal.session_replay.surfacing_scoring_sweep.workflow.record_tick_summary",
            ) as mock_record_tick_summary,
        ):
            summary = _summarize(chunks, results)
        assert summary == ScoreSessionsBatchResult(
            total_scored=10, total_fetched=13, chunks_dispatched=3, chunks_failed=1
        )
        mock_record_tick_summary.assert_called_once_with(total_scored=10, total_fetched=13, chunks_failed=1)

    def test_record_tick_summary_noops_when_tick_has_no_positive_counts(self) -> None:
        chunks = [_chunk(0), _chunk(1)]
        results: list[ChunkResult | BaseException] = [
            ChunkResult(chunk_id=0, scored=0, fetched=0),
            ChunkResult(chunk_id=1, scored=0, fetched=0),
        ]
        with (
            mock.patch("posthog.temporal.session_replay.surfacing_scoring_sweep.workflow.workflow.logger"),
            mock.patch(
                "posthog.temporal.session_replay.surfacing_scoring_sweep.workflow.record_tick_summary",
            ) as mock_record_tick_summary,
        ):
            summary = _summarize(chunks, results)
        assert summary == ScoreSessionsBatchResult(
            total_scored=0, total_fetched=0, chunks_dispatched=2, chunks_failed=0
        )
        mock_record_tick_summary.assert_called_once_with(total_scored=0, total_fetched=0, chunks_failed=0)


class TestParseInputs:
    # inputs_optional lets the workflow start with no inputs; "{}" still parses.
    @pytest.mark.parametrize("inputs", [[], ["{}"]])
    def test_parse_inputs_returns_default(self, inputs: list[str]) -> None:
        assert ScoreSessionsBatchWorkflow.parse_inputs(inputs) == ScoreSessionsBatchInputs()


@pytest.mark.asyncio
async def test_workflow_noop_when_plan_has_no_chunks() -> None:
    @activity.defn(name="list_chunks_activity")
    async def list_chunks_empty(_inputs: ScoreSessionsBatchInputs) -> ListChunksResult:
        return _plan([])

    task_queue = str(uuid.uuid4())
    async with await WorkflowEnvironment.start_time_skipping() as env:
        async with Worker(
            env.client,
            task_queue=task_queue,
            workflows=[ScoreSessionsBatchWorkflow],
            activities=[list_chunks_empty],
            workflow_runner=temporalio.worker.UnsandboxedWorkflowRunner(),
        ):
            result = await env.client.execute_workflow(
                WORKFLOW_NAME,
                ScoreSessionsBatchInputs(),
                id=str(uuid.uuid4()),
                task_queue=task_queue,
            )

    parsed = _as_batch_result(result)
    assert parsed.total_scored == 0
    assert parsed.chunks_dispatched == 0
    assert parsed.chunks_failed == 0


@pytest.mark.asyncio
async def test_workflow_fans_out_chunks_and_aggregates_scores() -> None:
    chunks = [_chunk(i) for i in range(4)]

    @activity.defn(name="list_chunks_activity")
    async def list_chunks_mocked(_inputs: ScoreSessionsBatchInputs) -> ListChunksResult:
        return _plan(chunks, estimated=40)

    @activity.defn(name="score_chunk_activity")
    async def score_chunk_mocked(spec: ChunkSpec) -> ChunkResult:
        return ChunkResult(chunk_id=spec.chunk_id, scored=spec.chunk_id + 1, fetched=(spec.chunk_id + 1) * 2)

    task_queue = str(uuid.uuid4())
    async with await WorkflowEnvironment.start_time_skipping() as env:
        async with Worker(
            env.client,
            task_queue=task_queue,
            workflows=[ScoreSessionsBatchWorkflow],
            activities=[list_chunks_mocked, score_chunk_mocked],
            workflow_runner=temporalio.worker.UnsandboxedWorkflowRunner(),
        ):
            result = await env.client.execute_workflow(
                WORKFLOW_NAME,
                ScoreSessionsBatchInputs(),
                id=str(uuid.uuid4()),
                task_queue=task_queue,
            )

    parsed = _as_batch_result(result)
    assert parsed.chunks_dispatched == 4
    assert parsed.chunks_failed == 0
    assert parsed.total_scored == 1 + 2 + 3 + 4
    assert parsed.total_fetched == (1 + 2 + 3 + 4) * 2


@pytest.mark.asyncio
async def test_workflow_tolerates_partial_chunk_failures() -> None:
    chunks = [_chunk(i) for i in range(3)]

    @activity.defn(name="list_chunks_activity")
    async def list_chunks_mocked(_inputs: ScoreSessionsBatchInputs) -> ListChunksResult:
        return _plan(chunks)

    @activity.defn(name="score_chunk_activity")
    async def score_chunk_one_fails(spec: ChunkSpec) -> ChunkResult:
        if spec.chunk_id == 1:
            raise RuntimeError("slow shard")
        return ChunkResult(chunk_id=spec.chunk_id, scored=5)

    task_queue = str(uuid.uuid4())
    async with await WorkflowEnvironment.start_time_skipping() as env:
        async with Worker(
            env.client,
            task_queue=task_queue,
            workflows=[ScoreSessionsBatchWorkflow],
            activities=[list_chunks_mocked, score_chunk_one_fails],
            workflow_runner=temporalio.worker.UnsandboxedWorkflowRunner(),
        ):
            result = await env.client.execute_workflow(
                WORKFLOW_NAME,
                ScoreSessionsBatchInputs(),
                id=str(uuid.uuid4()),
                task_queue=task_queue,
            )

    parsed = _as_batch_result(result)
    assert parsed.chunks_dispatched == 3
    assert parsed.chunks_failed == 1
    assert parsed.total_scored == 10


@pytest.mark.asyncio
async def test_workflow_survives_empty_chunk_results() -> None:
    chunks = [_chunk(0), _chunk(1)]

    @activity.defn(name="list_chunks_activity")
    async def list_chunks_mocked(_inputs: ScoreSessionsBatchInputs) -> ListChunksResult:
        return _plan(chunks)

    @activity.defn(name="score_chunk_activity")
    async def score_chunk_empty(spec: ChunkSpec) -> ChunkResult:
        return ChunkResult(chunk_id=spec.chunk_id, scored=0)

    task_queue = str(uuid.uuid4())
    async with await WorkflowEnvironment.start_time_skipping() as env:
        async with Worker(
            env.client,
            task_queue=task_queue,
            workflows=[ScoreSessionsBatchWorkflow],
            activities=[list_chunks_mocked, score_chunk_empty],
            workflow_runner=temporalio.worker.UnsandboxedWorkflowRunner(),
        ):
            result = await env.client.execute_workflow(
                WORKFLOW_NAME,
                ScoreSessionsBatchInputs(),
                id=str(uuid.uuid4()),
                task_queue=task_queue,
            )

    parsed = _as_batch_result(result)
    assert parsed.total_scored == 0
    assert parsed.chunks_failed == 0
    assert parsed.chunks_dispatched == 2
