import json
from collections.abc import AsyncGenerator, Callable
from typing import Any

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from pytest_mock import MockerFixture
from temporalio.client import WorkflowExecutionStatus
from temporalio.common import WorkflowIDConflictPolicy, WorkflowIDReusePolicy

from posthog.models import Team
from posthog.models.user import User
from posthog.temporal.session_replay.session_summary.state import (
    StateActivitiesEnum,
    generate_state_key,
    get_data_class_from_redis,
)
from posthog.temporal.session_replay.session_summary.summarize_session import (
    _execute_single_session_summary_workflow,
    _set_phase,
    _start_video_summary_workflow,
    execute_summarize_session,
    execute_summarize_session_video_stream,
    fetch_session_data_activity,
)
from posthog.temporal.session_replay.session_summary.types.single import SingleSessionProgress
from posthog.temporal.tests.session_replay.session_summary.conftest import AsyncRedisTestContext

from ee.hogai.session_summaries.session.summarize_session import SingleSessionSummaryLlmInputs
from ee.hogai.session_summaries.utils import serialize_to_sse_event
from ee.models.session_summaries import SingleSessionSummary

pytestmark = pytest.mark.django_db


def test_set_phase_updates_phase_and_step() -> None:
    progress: SingleSessionProgress = {
        "phase": "fetching_data",
        "step": 0,
        "total_steps": 6,
        "rasterizer_workflow_id": None,
        "segments_total": 0,
        "segments_completed": 0,
    }

    _set_phase(progress, "uploading_to_gemini")

    assert progress["phase"] == "uploading_to_gemini"
    assert progress["step"] == 3


class TestFetchSessionDataActivity:
    @pytest.mark.asyncio
    async def test_fetch_session_data_activity_standalone(
        self,
        mocker: MockerFixture,
        mock_session_id: str,
        mock_single_session_summary_inputs: Callable,
        ateam: Team,
        auser: User,
        mock_raw_metadata: dict[str, Any],
        mock_raw_events_columns: list[str],
        mock_raw_events: list[tuple[Any, ...]],
        redis_test_setup: AsyncRedisTestContext,
    ):
        """Test that fetch_session_data_activity stores compressed data correctly in Redis."""
        key_base = "fetch-session-data-activity-standalone"
        input_data = mock_single_session_summary_inputs(mock_session_id, ateam.id, auser.id, key_base)
        redis_input_key = generate_state_key(
            key_base=key_base, label=StateActivitiesEnum.SESSION_DB_DATA, state_id=mock_session_id
        )
        # Set up a spy to track Redis operations
        spy_setex = mocker.spy(redis_test_setup.redis_client, "setex")
        with (
            # Mock DB calls
            patch("ee.hogai.session_summaries.session.input_data.get_team", return_value=ateam),
            patch(
                "ee.hogai.session_summaries.session.summarize_session.get_session_metadata",
                return_value=mock_raw_metadata,
            ),
            patch(
                "ee.hogai.session_summaries.session.summarize_session.get_session_events",
                return_value=(mock_raw_events_columns, mock_raw_events),
            ),
        ):
            # Call the activity directly as a function, success if no exception is raised
            await fetch_session_data_activity(input_data)
            # Verify Redis operations
            assert spy_setex.call_count == 1  # Store compressed data
            # Verify the data was stored correctly
            stored_data = await redis_test_setup.redis_client.get(redis_input_key)
            assert stored_data is not None
            # Verify we can decompress and parse the stored data
            decompressed_data = await get_data_class_from_redis(
                redis_client=redis_test_setup.redis_client,
                redis_key=redis_input_key,
                label=StateActivitiesEnum.SESSION_DB_DATA,
                target_class=SingleSessionSummaryLlmInputs,
            )
            assert decompressed_data
            assert decompressed_data.session_id == mock_session_id
            assert decompressed_data.user_id == input_data.user_id

    @pytest.mark.asyncio
    async def test_fetch_session_data_activity_no_events_returns_false(
        self,
        mock_single_session_summary_inputs: Callable,
        mock_session_id: str,
        ateam: Team,
        auser: User,
        mock_raw_metadata: dict[str, Any],
        mock_raw_events_columns: list[str],
    ):
        """Test that fetch_session_data_activity returns False when no events are found (e.g., for static recordings)."""
        input_data = mock_single_session_summary_inputs(mock_session_id, ateam.id, auser.id, "test-no-events-key-base")
        with (
            patch("ee.hogai.session_summaries.session.input_data.get_team", return_value=ateam),
            patch(
                "ee.hogai.session_summaries.session.summarize_session.get_session_metadata",
                return_value=mock_raw_metadata,
            ),
            patch(
                "ee.hogai.session_summaries.session.summarize_session.get_session_events",
                return_value=(mock_raw_events_columns, []),
            ),
        ):
            result = await fetch_session_data_activity(input_data)
            assert result is False


class TestExecuteSummarizeSessionVideoStream:
    @staticmethod
    def _make_handle(check_handle_data_side_effect: list[tuple[Any, Any]]) -> MagicMock:
        handle = MagicMock()
        handle.query = AsyncMock()
        # Drive _check_handle_data via the underlying describe/result calls.
        describes = []
        result_value: Any = None
        for status, final_result in check_handle_data_side_effect:
            describes.append(MagicMock(status=status))
            if status == WorkflowExecutionStatus.COMPLETED:
                result_value = final_result
        handle.describe = AsyncMock(side_effect=describes)
        handle.result = AsyncMock(return_value=result_value)
        return handle

    @staticmethod
    async def _collect(
        generator: AsyncGenerator[str, None],
    ) -> list[str]:
        return [event async for event in generator]

    @pytest.mark.asyncio
    async def test_fast_path_returns_cached_summary_without_starting_workflow(
        self,
        mock_session_id: str,
        mock_user: MagicMock,
        mock_team: MagicMock,
        mock_enriched_llm_json_response: dict[str, Any],
    ):
        cached_summary = MagicMock()
        cached_summary.id = "cached-summary-id"
        cached_summary.summary = mock_enriched_llm_json_response
        with (
            patch.object(SingleSessionSummary.objects, "get_summary", return_value=cached_summary),
            patch(
                "posthog.temporal.session_replay.session_summary.summarize_session._prepare_execution"
            ) as mock_prepare,
            patch(
                "posthog.temporal.session_replay.session_summary.summarize_session._start_video_summary_workflow"
            ) as mock_start,
            patch("posthog.temporal.session_replay.session_summary.summarize_session.async_connect") as mock_connect,
        ):
            events = await self._collect(
                execute_summarize_session_video_stream(
                    session_id=mock_session_id,
                    user=mock_user,
                    team=mock_team,
                )
            )

        assert len(events) == 1
        assert events[0] == serialize_to_sse_event(
            event_label="session-summary-stream",
            event_data=json.dumps({"id": "cached-summary-id", "summary": mock_enriched_llm_json_response}),
        )
        mock_prepare.assert_not_called()
        mock_start.assert_not_called()
        mock_connect.assert_not_called()

    @pytest.mark.asyncio
    async def test_polling_loop_yields_progress_then_final_summary(
        self,
        mock_session_id: str,
        mock_user: MagicMock,
        mock_team: MagicMock,
        mock_enriched_llm_json_response: dict[str, Any],
    ):
        handle = self._make_handle(
            [
                (WorkflowExecutionStatus.RUNNING, None),
                (WorkflowExecutionStatus.RUNNING, None),
                (WorkflowExecutionStatus.COMPLETED, None),
            ]
        )
        progress_payloads = [
            {
                "phase": "fetching_data",
                "step": 0,
                "total_steps": 9,
                "rasterizer_workflow_id": None,
                "segments_total": 0,
                "segments_completed": 0,
            },
            {
                "phase": "uploading_to_gemini",
                "step": 3,
                "total_steps": 9,
                "rasterizer_workflow_id": None,
                "segments_total": 0,
                "segments_completed": 0,
            },
        ]
        handle.query.side_effect = progress_payloads

        completed_summary = MagicMock()
        completed_summary.id = "completed-summary-id"
        completed_summary.summary = mock_enriched_llm_json_response
        # First call is the fast-path check (returns None — no cached row),
        # second call is after COMPLETED (returns the freshly written row).
        get_summary_mock = MagicMock(side_effect=[None, completed_summary])

        with (
            patch.object(SingleSessionSummary.objects, "get_summary", get_summary_mock),
            patch(
                "posthog.temporal.session_replay.session_summary.summarize_session._prepare_execution",
                return_value=(None, None, None, MagicMock(), "workflow-id"),
            ),
            patch(
                "posthog.temporal.session_replay.session_summary.summarize_session._start_video_summary_workflow",
                AsyncMock(return_value=handle),
            ),
            patch(
                "posthog.temporal.session_replay.session_summary.summarize_session.async_connect",
                AsyncMock(return_value=MagicMock()),
            ),
            patch(
                "posthog.temporal.session_replay.session_summary.summarize_session.asyncio.sleep",
                AsyncMock(),
            ),
        ):
            events = await self._collect(
                execute_summarize_session_video_stream(
                    session_id=mock_session_id,
                    user=mock_user,
                    team=mock_team,
                )
            )

        assert len(events) == 3
        # First two events are progress with the rasterizer field added as None.
        first_progress = json.loads(events[0].split("data: ", 1)[1].strip())
        second_progress = json.loads(events[1].split("data: ", 1)[1].strip())
        assert first_progress["phase"] == "fetching_data"
        assert first_progress["rasterizer"] is None
        assert second_progress["phase"] == "uploading_to_gemini"
        assert second_progress["rasterizer"] is None
        # Final event is the summary stream.
        assert events[2] == serialize_to_sse_event(
            event_label="session-summary-stream",
            event_data=json.dumps({"id": "completed-summary-id", "summary": mock_enriched_llm_json_response}),
        )
        assert handle.query.call_count == 2

    @pytest.mark.asyncio
    async def test_rendering_video_phase_queries_rasterizer_child_workflow(
        self,
        mock_session_id: str,
        mock_user: MagicMock,
        mock_team: MagicMock,
        mock_enriched_llm_json_response: dict[str, Any],
    ):
        handle = self._make_handle(
            [
                (WorkflowExecutionStatus.RUNNING, None),
                (WorkflowExecutionStatus.COMPLETED, None),
            ]
        )
        rasterizer_id = "session-video-summary-rasterize_321_abc"
        handle.query.side_effect = [
            {
                "phase": "rendering_video",
                "step": 2,
                "total_steps": 9,
                "rasterizer_workflow_id": rasterizer_id,
                "segments_total": 0,
                "segments_completed": 0,
            },
        ]
        rasterizer_progress = {
            "phase": "rendering",
            "frame_progress": {"phase": "capture", "frame": 120, "estimatedTotalFrames": 600},
        }

        completed_summary = MagicMock()
        completed_summary.summary = mock_enriched_llm_json_response

        with (
            patch.object(
                SingleSessionSummary.objects,
                "get_summary",
                MagicMock(side_effect=[None, completed_summary]),
            ),
            patch(
                "posthog.temporal.session_replay.session_summary.summarize_session._prepare_execution",
                return_value=(None, None, None, MagicMock(), "workflow-id"),
            ),
            patch(
                "posthog.temporal.session_replay.session_summary.summarize_session._start_video_summary_workflow",
                AsyncMock(return_value=handle),
            ),
            patch(
                "posthog.temporal.session_replay.session_summary.summarize_session.async_connect",
                AsyncMock(return_value=MagicMock()),
            ),
            patch(
                "posthog.temporal.session_replay.session_summary.summarize_session._get_rasterizer_frame_progress",
                AsyncMock(return_value=rasterizer_progress),
            ) as mock_rasterizer_progress,
            patch(
                "posthog.temporal.session_replay.session_summary.summarize_session.asyncio.sleep",
                AsyncMock(),
            ),
        ):
            events = await self._collect(
                execute_summarize_session_video_stream(
                    session_id=mock_session_id,
                    user=mock_user,
                    team=mock_team,
                )
            )

        mock_rasterizer_progress.assert_awaited_once()
        args, _kwargs = mock_rasterizer_progress.call_args
        assert args[1] == rasterizer_id
        assert len(events) == 2
        progress_payload = json.loads(events[0].split("data: ", 1)[1].strip())
        assert progress_payload["phase"] == "rendering_video"
        assert progress_payload["rasterizer"] == rasterizer_progress

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "terminal_status,expected_message",
        [
            (
                WorkflowExecutionStatus.FAILED,
                "Something went wrong while generating the summary. Please try again.",
            ),
            (WorkflowExecutionStatus.CANCELED, "The summary generation was canceled."),
            (
                WorkflowExecutionStatus.TERMINATED,
                "The summary generation was terminated unexpectedly. Please try again.",
            ),
            (
                WorkflowExecutionStatus.TIMED_OUT,
                "The summary generation timed out. The recording may be too long or complex. Please try again.",
            ),
        ],
    )
    async def test_terminal_failure_status_yields_error_event(
        self,
        terminal_status: WorkflowExecutionStatus,
        expected_message: str,
        mock_session_id: str,
        mock_user: MagicMock,
        mock_team: MagicMock,
    ):
        handle = self._make_handle([(terminal_status, None)])

        with (
            patch.object(SingleSessionSummary.objects, "get_summary", MagicMock(return_value=None)),
            patch(
                "posthog.temporal.session_replay.session_summary.summarize_session._prepare_execution",
                return_value=(None, None, None, MagicMock(), "workflow-id"),
            ),
            patch(
                "posthog.temporal.session_replay.session_summary.summarize_session._start_video_summary_workflow",
                AsyncMock(return_value=handle),
            ),
            patch(
                "posthog.temporal.session_replay.session_summary.summarize_session.async_connect",
                AsyncMock(return_value=MagicMock()),
            ),
            patch(
                "posthog.temporal.session_replay.session_summary.summarize_session.asyncio.sleep",
                AsyncMock(),
            ),
        ):
            events = await self._collect(
                execute_summarize_session_video_stream(
                    session_id=mock_session_id,
                    user=mock_user,
                    team=mock_team,
                )
            )

        assert len(events) == 1
        assert events[0] == serialize_to_sse_event(
            event_label="session-summary-error",
            event_data=expected_message,
        )
        handle.query.assert_not_called()

    @pytest.mark.asyncio
    async def test_completed_without_db_row_yields_error_event(
        self,
        mock_session_id: str,
        mock_user: MagicMock,
        mock_team: MagicMock,
    ):
        handle = self._make_handle([(WorkflowExecutionStatus.COMPLETED, None)])

        with (
            patch.object(SingleSessionSummary.objects, "get_summary", MagicMock(return_value=None)),
            patch(
                "posthog.temporal.session_replay.session_summary.summarize_session._prepare_execution",
                return_value=(None, None, None, MagicMock(), "workflow-id"),
            ),
            patch(
                "posthog.temporal.session_replay.session_summary.summarize_session._start_video_summary_workflow",
                AsyncMock(return_value=handle),
            ),
            patch(
                "posthog.temporal.session_replay.session_summary.summarize_session.async_connect",
                AsyncMock(return_value=MagicMock()),
            ),
            patch(
                "posthog.temporal.session_replay.session_summary.summarize_session.asyncio.sleep",
                AsyncMock(),
            ),
        ):
            events = await self._collect(
                execute_summarize_session_video_stream(
                    session_id=mock_session_id,
                    user=mock_user,
                    team=mock_team,
                )
            )

        assert len(events) == 1
        assert events[0] == serialize_to_sse_event(
            event_label="session-summary-error",
            event_data="Something went wrong while generating the summary. Please try again.",
        )

    @pytest.mark.asyncio
    async def test_get_progress_query_failure_retries_next_iteration(
        self,
        mock_session_id: str,
        mock_user: MagicMock,
        mock_team: MagicMock,
        mock_enriched_llm_json_response: dict[str, Any],
    ):
        handle = self._make_handle(
            [
                (WorkflowExecutionStatus.RUNNING, None),
                (WorkflowExecutionStatus.COMPLETED, None),
            ]
        )
        # First query raises, loop should continue and reach COMPLETED on the
        # next iteration — yielding only the final summary event.
        handle.query.side_effect = [RuntimeError("workflow not queryable yet")]

        completed_summary = MagicMock()
        completed_summary.id = "completed-summary-id"
        completed_summary.summary = mock_enriched_llm_json_response

        with (
            patch.object(
                SingleSessionSummary.objects,
                "get_summary",
                MagicMock(side_effect=[None, completed_summary]),
            ),
            patch(
                "posthog.temporal.session_replay.session_summary.summarize_session._prepare_execution",
                return_value=(None, None, None, MagicMock(), "workflow-id"),
            ),
            patch(
                "posthog.temporal.session_replay.session_summary.summarize_session._start_video_summary_workflow",
                AsyncMock(return_value=handle),
            ),
            patch(
                "posthog.temporal.session_replay.session_summary.summarize_session.async_connect",
                AsyncMock(return_value=MagicMock()),
            ),
            patch(
                "posthog.temporal.session_replay.session_summary.summarize_session.asyncio.sleep",
                AsyncMock(),
            ),
        ):
            events = await self._collect(
                execute_summarize_session_video_stream(
                    session_id=mock_session_id,
                    user=mock_user,
                    team=mock_team,
                )
            )

        assert len(events) == 1
        assert events[0] == serialize_to_sse_event(
            event_label="session-summary-stream",
            event_data=json.dumps({"id": "completed-summary-id", "summary": mock_enriched_llm_json_response}),
        )
        assert handle.query.call_count == 1

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "force_restart,expected_conflict_policy",
        [
            (False, WorkflowIDConflictPolicy.USE_EXISTING),
            (True, WorkflowIDConflictPolicy.TERMINATE_EXISTING),
        ],
    )
    async def test_video_stream_threads_force_restart_into_start_workflow(
        self,
        force_restart: bool,
        expected_conflict_policy: WorkflowIDConflictPolicy,
        mock_session_id: str,
        mock_user: MagicMock,
        mock_team: MagicMock,
        mock_enriched_llm_json_response: dict[str, Any],
    ):
        """``force_restart`` is forwarded so the conflict policy matches the user
        intent (attach-to-existing vs. preempt-and-restart)."""
        handle = self._make_handle([(WorkflowExecutionStatus.COMPLETED, None)])
        completed_summary = MagicMock()
        completed_summary.summary = mock_enriched_llm_json_response

        with (
            patch.object(
                SingleSessionSummary.objects,
                "get_summary",
                MagicMock(side_effect=[None, completed_summary]),
            ),
            patch(
                "posthog.temporal.session_replay.session_summary.summarize_session._prepare_execution",
                return_value=(None, None, None, MagicMock(), "workflow-id"),
            ),
            patch(
                "posthog.temporal.session_replay.session_summary.summarize_session._start_video_summary_workflow",
                AsyncMock(return_value=handle),
            ) as mock_start,
            patch(
                "posthog.temporal.session_replay.session_summary.summarize_session.async_connect",
                AsyncMock(return_value=MagicMock()),
            ),
        ):
            await self._collect(
                execute_summarize_session_video_stream(
                    session_id=mock_session_id,
                    user=mock_user,
                    team=mock_team,
                    force_restart=force_restart,
                )
            )

        mock_start.assert_awaited_once()
        assert mock_start.call_args.kwargs["force_restart"] is force_restart

        # Drive _start_video_summary_workflow itself once with the same flag and
        # confirm it picks the matching conflict policy when calling Temporal —
        # this keeps the test honest about the contract instead of just
        # checking pass-through.
        client = MagicMock()
        client.start_workflow = AsyncMock(return_value=handle)
        with patch(
            "posthog.temporal.session_replay.session_summary.summarize_session.async_connect",
            AsyncMock(return_value=client),
        ):
            await _start_video_summary_workflow(
                inputs=MagicMock(team_id=321),
                workflow_id="wfid",
                force_restart=force_restart,
            )
        kwargs = client.start_workflow.call_args.kwargs
        assert kwargs["id_reuse_policy"] == WorkflowIDReusePolicy.ALLOW_DUPLICATE
        assert kwargs["id_conflict_policy"] == expected_conflict_policy


class TestStartVideoSummaryWorkflow:
    @pytest.mark.asyncio
    async def test_default_uses_use_existing_so_concurrent_clicks_attach(self) -> None:
        """Without ``force_restart`` we must not kill an in-flight workflow that
        another tab/user is already watching — the contract is dedup, not preempt."""
        client = MagicMock()
        client.start_workflow = AsyncMock(return_value=MagicMock())
        with patch(
            "posthog.temporal.session_replay.session_summary.summarize_session.async_connect",
            AsyncMock(return_value=client),
        ):
            await _start_video_summary_workflow(
                inputs=MagicMock(team_id=321),
                workflow_id="wfid",
            )
        kwargs = client.start_workflow.call_args.kwargs
        assert kwargs["id_conflict_policy"] == WorkflowIDConflictPolicy.USE_EXISTING
        assert kwargs["id_reuse_policy"] == WorkflowIDReusePolicy.ALLOW_DUPLICATE

    @pytest.mark.asyncio
    async def test_force_restart_uses_terminate_existing(self) -> None:
        """Retry-after-cancel must atomically preempt the previous workflow,
        even if it's still in the CANCEL_REQUESTED → CANCELLED window."""
        client = MagicMock()
        client.start_workflow = AsyncMock(return_value=MagicMock())
        with patch(
            "posthog.temporal.session_replay.session_summary.summarize_session.async_connect",
            AsyncMock(return_value=client),
        ):
            await _start_video_summary_workflow(
                inputs=MagicMock(team_id=321),
                workflow_id="wfid",
                force_restart=True,
            )
        kwargs = client.start_workflow.call_args.kwargs
        assert kwargs["id_conflict_policy"] == WorkflowIDConflictPolicy.TERMINATE_EXISTING
        assert kwargs["id_reuse_policy"] == WorkflowIDReusePolicy.ALLOW_DUPLICATE


class TestExecuteSingleSessionSummaryWorkflow:
    @pytest.mark.asyncio
    async def test_uses_allow_duplicate_and_use_existing(self) -> None:
        """The AI-tool path must be compatible with workflow ids the UI just
        cancelled: USE_EXISTING attaches to a running workflow instead of
        raising, and ALLOW_DUPLICATE permits a fresh start once the previous
        run reaches any terminal state (including CANCELLED)."""
        client = MagicMock()
        client.execute_workflow = AsyncMock(return_value=None)
        with patch(
            "posthog.temporal.session_replay.session_summary.summarize_session.async_connect",
            AsyncMock(return_value=client),
        ):
            await _execute_single_session_summary_workflow(
                inputs=MagicMock(team_id=321),
                workflow_id="wfid",
            )
        kwargs = client.execute_workflow.call_args.kwargs
        assert kwargs["id_reuse_policy"] == WorkflowIDReusePolicy.ALLOW_DUPLICATE
        assert kwargs["id_conflict_policy"] == WorkflowIDConflictPolicy.USE_EXISTING


class TestExecuteSummarizeSession:
    @pytest.mark.asyncio
    async def test_returns_existing_summary_without_starting_workflow(
        self,
        mock_session_id: str,
        mock_user: MagicMock,
        mock_team: MagicMock,
        mock_enriched_llm_json_response: dict[str, Any],
    ) -> None:
        cached = MagicMock()
        cached.summary = mock_enriched_llm_json_response
        with (
            patch.object(SingleSessionSummary.objects, "get_summary", MagicMock(return_value=cached)),
            patch(
                "posthog.temporal.session_replay.session_summary.summarize_session._execute_single_session_summary_workflow"
            ) as mock_execute,
        ):
            result = await execute_summarize_session(
                session_id=mock_session_id,
                user=mock_user,
                team=mock_team,
            )
        assert result == mock_enriched_llm_json_response
        mock_execute.assert_not_called()
