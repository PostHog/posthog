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
async def test_run_summaries_keeps_partial_results_above_threshold():
    # N=10, threshold=3, 7 successes: well above. Failures get tagged for the banner.
    workflow = SummarizeSessionGroupWorkflow()
    workflow._total_sessions = 10

    inputs = [_input(f"sess-{i}") for i in range(10)]
    side_effects = [None, None, RuntimeError("a"), None, None, RuntimeError("b"), None, None, RuntimeError("c"), None]
    expected_success_ids = {"sess-0", "sess-1", "sess-3", "sess-4", "sess-6", "sess-7", "sess-9"}
    expected_failed_ids = {"sess-2", "sess-5", "sess-8"}

    with (
        _patch_workflow_logger(),
        patch(
            f"{WORKFLOW_MODULE}.ensure_llm_single_session_summary",
            new=AsyncMock(side_effect=side_effects),
        ),
    ):
        result = await workflow._run_summaries(inputs)

    assert {r.session_id for r in result} == expected_success_ids
    for failed_id in expected_failed_ids:
        assert workflow._session_statuses[failed_id] == "failed"
        assert failed_id in workflow._failed_sessions
        assert workflow._failed_sessions[failed_id].category == "summarization_failed"


@pytest.mark.parametrize(
    "side_effects",
    [
        [RuntimeError("a"), RuntimeError("b"), RuntimeError("c")],
        [None, RuntimeError("a"), RuntimeError("b"), RuntimeError("c"), RuntimeError("d")],
        [None] + [RuntimeError(f"boom-{i}") for i in range(29)],
    ],
)
@pytest.mark.asyncio
async def test_run_summaries_aborts_below_threshold(side_effects):
    workflow = SummarizeSessionGroupWorkflow()
    workflow._total_sessions = len(side_effects)

    inputs = [_input(f"sess-{i}") for i in range(len(side_effects))]

    with (
        _patch_workflow_logger(),
        patch(
            f"{WORKFLOW_MODULE}.ensure_llm_single_session_summary",
            new=AsyncMock(side_effect=side_effects),
        ),
    ):
        with pytest.raises(ApplicationError, match="sessions summarized successfully"):
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
