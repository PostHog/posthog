import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from temporalio.exceptions import ApplicationError

from posthog.temporal.session_replay.session_summary.types.inputs import SingleSessionSummaryInputs
from posthog.temporal.session_replay.session_summary_group.workflow import SummarizeSessionGroupWorkflow

WORKFLOW_MODULE = "posthog.temporal.session_replay.session_summary_group.workflow"


def _input(session_id: str) -> SingleSessionSummaryInputs:
    return SingleSessionSummaryInputs(
        session_id=session_id,
        user_id=1,
        team_id=1,
        redis_key_base="test",
        model_to_use="test-model",
    )


def _patch_workflow_logger():
    return patch(f"{WORKFLOW_MODULE}.temporalio.workflow.logger", new=MagicMock())


@pytest.mark.asyncio
async def test_run_summary_returns_none_on_success():
    workflow = SummarizeSessionGroupWorkflow()
    workflow._total_sessions = 1

    with (
        _patch_workflow_logger(),
        patch(f"{WORKFLOW_MODULE}.ensure_llm_single_session_summary", new=AsyncMock(return_value=None)),
    ):
        result = await workflow._run_summary(_input("sess-1"))

    assert result is None
    assert workflow._session_statuses["sess-1"] == "summarized"
    assert workflow._processed_single_summaries == 1


@pytest.mark.asyncio
async def test_run_summary_returns_exception_on_failure():
    workflow = SummarizeSessionGroupWorkflow()

    err = RuntimeError("LLM call failed")
    with (
        _patch_workflow_logger(),
        patch(f"{WORKFLOW_MODULE}.ensure_llm_single_session_summary", new=AsyncMock(side_effect=err)),
    ):
        result = await workflow._run_summary(_input("sess-1"))

    assert result is err
    assert workflow._session_statuses["sess-1"] == "failed"
    assert workflow._processed_single_summaries == 0


@pytest.mark.asyncio
async def test_run_summaries_isolates_per_session_failures_when_above_threshold():
    workflow = SummarizeSessionGroupWorkflow()
    workflow._total_sessions = 4

    inputs = [_input(f"sess-{i}") for i in range(4)]
    # 3 succeed, 1 fails — ratio = 0.75 > FAILED_SESSION_SUMMARIES_MIN_RATIO (0.5)
    side_effects = [None, RuntimeError("boom"), None, None]

    with (
        _patch_workflow_logger(),
        patch(
            f"{WORKFLOW_MODULE}.ensure_llm_single_session_summary",
            new=AsyncMock(side_effect=side_effects),
        ),
    ):
        result = await workflow._run_summaries(inputs)

    assert len(result) == 3
    assert {r.session_id for r in result} == {"sess-0", "sess-2", "sess-3"}
    assert workflow._session_statuses["sess-1"] == "failed"


@pytest.mark.asyncio
async def test_run_summaries_raises_when_too_many_fail():
    workflow = SummarizeSessionGroupWorkflow()
    workflow._total_sessions = 4

    inputs = [_input(f"sess-{i}") for i in range(4)]
    # 1 succeeds, 3 fail — ratio = 0.25 < FAILED_SESSION_SUMMARIES_MIN_RATIO (0.5)
    side_effects = [
        None,
        RuntimeError("a"),
        RuntimeError("b"),
        RuntimeError("c"),
    ]

    with (
        _patch_workflow_logger(),
        patch(
            f"{WORKFLOW_MODULE}.ensure_llm_single_session_summary",
            new=AsyncMock(side_effect=side_effects),
        ),
    ):
        with pytest.raises(ApplicationError, match="Too many sessions failed to summarize"):
            await workflow._run_summaries(inputs)


@pytest.mark.asyncio
async def test_run_summaries_raises_on_empty_input():
    workflow = SummarizeSessionGroupWorkflow()
    with _patch_workflow_logger():
        with pytest.raises(ApplicationError, match="No sessions to summarize"):
            await workflow._run_summaries([])


@pytest.mark.asyncio
async def test_run_patterns_extraction_chunk_returns_exception_on_failure():
    workflow = SummarizeSessionGroupWorkflow()
    workflow._total_sessions = 3

    err = RuntimeError("activity retries exhausted")
    chunk_inputs = MagicMock()
    chunk_inputs.single_session_summaries_inputs = [_input(f"sess-{i}") for i in range(3)]

    with patch(f"{WORKFLOW_MODULE}.temporalio.workflow.execute_activity", new=AsyncMock(side_effect=err)):
        result = await workflow._run_patterns_extraction_chunk(chunk_inputs)

    assert result is err
    assert workflow._processed_patterns_extraction == 0


@pytest.mark.asyncio
async def test_run_patterns_extraction_chunk_records_redis_key_on_success():
    workflow = SummarizeSessionGroupWorkflow()
    workflow._total_sessions = 3

    chunk_inputs = MagicMock()
    chunk_inputs.single_session_summaries_inputs = [_input(f"sess-{i}") for i in range(3)]

    with patch(f"{WORKFLOW_MODULE}.temporalio.workflow.execute_activity", new=AsyncMock(return_value="redis-key-1")):
        result = await workflow._run_patterns_extraction_chunk(chunk_inputs)

    assert result is None
    assert workflow._raw_patterns_extracted_keys == ["redis-key-1"]
    assert workflow._processed_patterns_extraction == 3
