import re
import json
from collections.abc import AsyncGenerator, Callable, Iterator
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from pytest_mock import MockerFixture
from temporalio.client import WorkflowExecutionStatus
from temporalio.common import WorkflowIDConflictPolicy, WorkflowIDReusePolicy

from posthog.models import Team
from posthog.models.user import User
from posthog.session_recordings.queries.session_replay_events import SessionReplayEvents
from posthog.temporal.session_replay.session_summary.activities.event_based.fetch_session_data import (
    fetch_session_data_activity,
)
from posthog.temporal.session_replay.session_summary.state import (
    StateActivitiesEnum,
    generate_state_key,
    get_data_class_from_redis,
)
from posthog.temporal.session_replay.session_summary.types.inputs import SingleSessionProgress
from posthog.temporal.session_replay.session_summary.workflow import (
    SUMMARY_RESULT_NO_EVENTS,
    _execute_single_session_summary_workflow,
    _set_phase,
    _start_video_summary_workflow,
    execute_summarize_session,
    execute_summarize_session_video_stream,
)
from posthog.temporal.tests.session_replay.session_summary.conftest import AsyncRedisTestContext

from products.replay.backend.models.session_summaries import SingleSessionSummary

from ee.hogai.session_summaries.constants import SESSION_EVENTS_REPLAY_CUTOFF_MS, SESSION_SUMMARY_EVENT_BLOCKLIST
from ee.hogai.session_summaries.session.summarize_session import SingleSessionSummaryLlmInputs
from ee.hogai.session_summaries.utils import serialize_to_sse_event

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


def test_frontend_summary_gate_constants_match_backend() -> None:
    # The Summarize button gate in playerMetaLogic.tsx hardcodes copies of the backend summary
    # event filters. Guard against the two drifting apart (there is no shared source).
    repo_root = Path(__file__).resolve().parents[5]
    ts = (repo_root / "frontend/src/scenes/session-recordings/player/player-meta/playerMetaLogic.tsx").read_text()

    cutoff_match = re.search(r"SUMMARY_EVENTS_REPLAY_CUTOFF_MS\s*=\s*(\d+)", ts)
    assert cutoff_match, "SUMMARY_EVENTS_REPLAY_CUTOFF_MS not found in playerMetaLogic.tsx"
    assert int(cutoff_match.group(1)) == SESSION_EVENTS_REPLAY_CUTOFF_MS

    blocklist_match = re.search(r"SUMMARY_EVENT_BLOCKLIST\s*=\s*\[(.*?)\]", ts, re.DOTALL)
    assert blocklist_match, "SUMMARY_EVENT_BLOCKLIST not found in playerMetaLogic.tsx"
    frontend_blocklist = set(re.findall(r"""['"]([^'"]+)['"]""", blocklist_match.group(1)))
    assert frontend_blocklist == set(SESSION_SUMMARY_EVENT_BLOCKLIST)


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

    @pytest.mark.asyncio
    async def test_fetch_session_data_activity_no_metadata_returns_false(
        self,
        mock_single_session_summary_inputs: Callable,
        mock_session_id: str,
        ateam: Team,
        auser: User,
    ):
        """Test that fetch_session_data_activity returns False (instead of raising) when the replay
        metadata is missing, e.g. for expired or deleted recordings picked up by bulk sweeps."""
        input_data = mock_single_session_summary_inputs(
            mock_session_id, ateam.id, auser.id, "test-no-metadata-key-base"
        )
        with (
            patch("ee.hogai.session_summaries.session.input_data.get_team", return_value=ateam),
            patch.object(SessionReplayEvents, "get_metadata", return_value=None),
        ):
            result = await fetch_session_data_activity(input_data)
            assert result is False


class TestExecuteSummarizeSessionVideoStream:
    @pytest.fixture(autouse=True)
    def cap_mocks(self) -> Iterator[SimpleNamespace]:
        """Default cap behavior for the happy path: no in-flight workflow,
        cap not exhausted. Tests that need to block, refund, or simulate Redis
        failures flip the relevant return value rather than re-patching."""
        workflow_is_running = AsyncMock(return_value=False)
        atomic = MagicMock(return_value=MagicMock(allowed=True, used=1, cap=4000))
        refund = MagicMock(return_value=None)
        # In-range metadata by default so the up-front length precheck is a no-op;
        # length tests override the return value to drive the too-short/too-long paths.
        get_metadata = MagicMock(return_value={"duration": 120, "active_seconds": 60})
        with (
            patch(
                "posthog.temporal.session_replay.session_summary.workflow._workflow_is_running",
                workflow_is_running,
            ),
            patch(
                "posthog.temporal.session_replay.session_summary.workflow.atomic_check_and_consume",
                atomic,
            ),
            patch(
                "posthog.temporal.session_replay.session_summary.workflow.refund",
                refund,
            ),
            patch.object(SessionReplayEvents, "get_metadata", get_metadata),
        ):
            yield SimpleNamespace(
                workflow_is_running=workflow_is_running,
                atomic=atomic,
                refund=refund,
                get_metadata=get_metadata,
            )

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
        generator: AsyncGenerator[str],
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
            patch("posthog.temporal.session_replay.session_summary.workflow._prepare_execution") as mock_prepare,
            patch(
                "posthog.temporal.session_replay.session_summary.workflow._start_video_summary_workflow"
            ) as mock_start,
            patch("posthog.temporal.session_replay.session_summary.workflow.async_connect") as mock_connect,
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
                "posthog.temporal.session_replay.session_summary.workflow._prepare_execution",
                return_value=(None, None, None, MagicMock(), "workflow-id"),
            ),
            patch(
                "posthog.temporal.session_replay.session_summary.workflow._start_video_summary_workflow",
                AsyncMock(return_value=handle),
            ),
            patch(
                "posthog.temporal.session_replay.session_summary.workflow.async_connect",
                AsyncMock(return_value=MagicMock()),
            ),
            patch(
                "posthog.temporal.session_replay.session_summary.workflow.asyncio.sleep",
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
                "posthog.temporal.session_replay.session_summary.workflow._prepare_execution",
                return_value=(None, None, None, MagicMock(), "workflow-id"),
            ),
            patch(
                "posthog.temporal.session_replay.session_summary.workflow._start_video_summary_workflow",
                AsyncMock(return_value=handle),
            ),
            patch(
                "posthog.temporal.session_replay.session_summary.workflow.async_connect",
                AsyncMock(return_value=MagicMock()),
            ),
            patch(
                "posthog.temporal.session_replay.session_summary.workflow._get_rasterizer_frame_progress",
                AsyncMock(return_value=rasterizer_progress),
            ) as mock_rasterizer_progress,
            patch(
                "posthog.temporal.session_replay.session_summary.workflow.asyncio.sleep",
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
                "posthog.temporal.session_replay.session_summary.workflow._prepare_execution",
                return_value=(None, None, None, MagicMock(), "workflow-id"),
            ),
            patch(
                "posthog.temporal.session_replay.session_summary.workflow._start_video_summary_workflow",
                AsyncMock(return_value=handle),
            ),
            patch(
                "posthog.temporal.session_replay.session_summary.workflow.async_connect",
                AsyncMock(return_value=MagicMock()),
            ),
            patch(
                "posthog.temporal.session_replay.session_summary.workflow.asyncio.sleep",
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
                "posthog.temporal.session_replay.session_summary.workflow._prepare_execution",
                return_value=(None, None, None, MagicMock(), "workflow-id"),
            ),
            patch(
                "posthog.temporal.session_replay.session_summary.workflow._start_video_summary_workflow",
                AsyncMock(return_value=handle),
            ),
            patch(
                "posthog.temporal.session_replay.session_summary.workflow.async_connect",
                AsyncMock(return_value=MagicMock()),
            ),
            patch(
                "posthog.temporal.session_replay.session_summary.workflow.asyncio.sleep",
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
    async def test_completed_no_events_yields_specific_error(
        self,
        mock_session_id: str,
        mock_user: MagicMock,
        mock_team: MagicMock,
    ):
        # Workflow completes with the no-events sentinel: surface a clear message, not the generic one.
        handle = self._make_handle([(WorkflowExecutionStatus.COMPLETED, SUMMARY_RESULT_NO_EVENTS)])

        with (
            patch.object(SingleSessionSummary.objects, "get_summary", MagicMock(return_value=None)),
            patch(
                "posthog.temporal.session_replay.session_summary.workflow._prepare_execution",
                return_value=(None, None, None, MagicMock(), "workflow-id"),
            ),
            patch(
                "posthog.temporal.session_replay.session_summary.workflow._start_video_summary_workflow",
                AsyncMock(return_value=handle),
            ),
            patch(
                "posthog.temporal.session_replay.session_summary.workflow.async_connect",
                AsyncMock(return_value=MagicMock()),
            ),
            patch(
                "posthog.temporal.session_replay.session_summary.workflow.asyncio.sleep",
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

        assert events == [
            serialize_to_sse_event(
                event_label="session-summary-error",
                event_data="This recording has no events to summarize.",
            )
        ]

    @pytest.mark.parametrize(
        "metadata,expected_substring",
        [
            ({"duration": 5, "active_seconds": 5}, "too short"),
            ({"duration": 40000, "active_seconds": 40000}, "too long"),
        ],
    )
    @pytest.mark.asyncio
    async def test_out_of_range_recording_yields_error_without_starting_workflow(
        self,
        metadata: dict,
        expected_substring: str,
        cap_mocks: SimpleNamespace,
        mock_session_id: str,
        mock_user: MagicMock,
        mock_team: MagicMock,
    ):
        cap_mocks.get_metadata.return_value = metadata

        with (
            patch.object(SingleSessionSummary.objects, "get_summary", MagicMock(return_value=None)),
            patch("posthog.temporal.session_replay.session_summary.workflow._prepare_execution") as mock_prepare,
            patch(
                "posthog.temporal.session_replay.session_summary.workflow._start_video_summary_workflow"
            ) as mock_start,
            patch("posthog.temporal.session_replay.session_summary.workflow.async_connect") as mock_connect,
        ):
            events = await self._collect(
                execute_summarize_session_video_stream(
                    session_id=mock_session_id,
                    user=mock_user,
                    team=mock_team,
                )
            )

        assert len(events) == 1
        assert events[0].startswith("event: session-summary-error\n")
        assert expected_substring in events[0]
        mock_prepare.assert_not_called()
        mock_start.assert_not_called()
        mock_connect.assert_not_called()

    @pytest.mark.asyncio
    async def test_length_precheck_fails_open_when_metadata_read_errors(
        self,
        cap_mocks: SimpleNamespace,
        mock_session_id: str,
        mock_user: MagicMock,
        mock_team: MagicMock,
        mock_enriched_llm_json_response: dict[str, Any],
    ):
        # A failing get_metadata read must not block summarization: skip the length
        # precheck and proceed to start the workflow as normal.
        cap_mocks.get_metadata.side_effect = Exception("clickhouse unavailable")
        completed_summary = MagicMock()
        completed_summary.id = "completed-summary-id"
        completed_summary.summary = mock_enriched_llm_json_response
        handle = self._make_handle([(WorkflowExecutionStatus.COMPLETED, None)])

        with (
            patch.object(SingleSessionSummary.objects, "get_summary", MagicMock(side_effect=[None, completed_summary])),
            patch(
                "posthog.temporal.session_replay.session_summary.workflow._prepare_execution",
                return_value=(None, None, None, MagicMock(), "workflow-id"),
            ),
            patch(
                "posthog.temporal.session_replay.session_summary.workflow._start_video_summary_workflow",
                AsyncMock(return_value=handle),
            ) as mock_start,
            patch(
                "posthog.temporal.session_replay.session_summary.workflow.async_connect",
                AsyncMock(return_value=MagicMock()),
            ),
            patch(
                "posthog.temporal.session_replay.session_summary.workflow.asyncio.sleep",
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

        mock_start.assert_awaited_once()
        assert not any("event: session-summary-error" in event for event in events)
        assert events[-1].startswith("event: session-summary-stream\n")

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
                "posthog.temporal.session_replay.session_summary.workflow._prepare_execution",
                return_value=(None, None, None, MagicMock(), "workflow-id"),
            ),
            patch(
                "posthog.temporal.session_replay.session_summary.workflow._start_video_summary_workflow",
                AsyncMock(return_value=handle),
            ),
            patch(
                "posthog.temporal.session_replay.session_summary.workflow.async_connect",
                AsyncMock(return_value=MagicMock()),
            ),
            patch(
                "posthog.temporal.session_replay.session_summary.workflow.asyncio.sleep",
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
                "posthog.temporal.session_replay.session_summary.workflow._prepare_execution",
                return_value=(None, None, None, MagicMock(), "workflow-id"),
            ),
            patch(
                "posthog.temporal.session_replay.session_summary.workflow._start_video_summary_workflow",
                AsyncMock(return_value=handle),
            ) as mock_start,
            patch(
                "posthog.temporal.session_replay.session_summary.workflow.async_connect",
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
            "posthog.temporal.session_replay.session_summary.workflow.async_connect",
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

    @pytest.mark.asyncio
    async def test_attach_to_running_workflow_skips_check_and_consume(
        self,
        cap_mocks: SimpleNamespace,
        mock_session_id: str,
        mock_user: MagicMock,
        mock_team: MagicMock,
        mock_enriched_llm_json_response: dict[str, Any],
    ):
        """When the same workflow is already RUNNING (silent attach via
        ``id_conflict_policy=USE_EXISTING``), the cap MUST NOT fire. The other
        caller already paid the LLM cost — gating here would 402 a teammate
        reading work-in-progress."""
        cap_mocks.workflow_is_running.return_value = True
        handle = self._make_handle([(WorkflowExecutionStatus.COMPLETED, None)])
        completed_summary = MagicMock()
        completed_summary.id = "id"
        completed_summary.summary = mock_enriched_llm_json_response

        with (
            patch.object(
                SingleSessionSummary.objects,
                "get_summary",
                MagicMock(side_effect=[None, completed_summary]),
            ),
            patch(
                "posthog.temporal.session_replay.session_summary.workflow._prepare_execution",
                return_value=(None, None, None, MagicMock(), "workflow-id"),
            ),
            patch(
                "posthog.temporal.session_replay.session_summary.workflow._start_video_summary_workflow",
                AsyncMock(return_value=handle),
            ),
            patch(
                "posthog.temporal.session_replay.session_summary.workflow.async_connect",
                AsyncMock(return_value=MagicMock()),
            ),
            patch(
                "posthog.temporal.session_replay.session_summary.workflow.asyncio.sleep",
                AsyncMock(),
            ),
        ):
            await self._collect(
                execute_summarize_session_video_stream(
                    session_id=mock_session_id,
                    user=mock_user,
                    team=mock_team,
                )
            )

        cap_mocks.atomic.assert_not_called()
        cap_mocks.refund.assert_not_called()

    @pytest.mark.asyncio
    async def test_force_restart_charges_cap_even_when_already_running(
        self,
        cap_mocks: SimpleNamespace,
        mock_session_id: str,
        mock_user: MagicMock,
        mock_team: MagicMock,
        mock_enriched_llm_json_response: dict[str, Any],
    ):
        """``force_restart=True`` uses TERMINATE_EXISTING — that's a fresh LLM
        run regardless of what was running before. The cap and consume must both
        fire on this path."""
        cap_mocks.workflow_is_running.return_value = True
        handle = self._make_handle([(WorkflowExecutionStatus.COMPLETED, None)])
        completed_summary = MagicMock()
        completed_summary.id = "id"
        completed_summary.summary = mock_enriched_llm_json_response

        with (
            patch.object(
                SingleSessionSummary.objects,
                "get_summary",
                MagicMock(side_effect=[None, completed_summary]),
            ),
            patch(
                "posthog.temporal.session_replay.session_summary.workflow._prepare_execution",
                return_value=(None, None, None, MagicMock(), "workflow-id"),
            ),
            patch(
                "posthog.temporal.session_replay.session_summary.workflow._start_video_summary_workflow",
                AsyncMock(return_value=handle),
            ),
            patch(
                "posthog.temporal.session_replay.session_summary.workflow.async_connect",
                AsyncMock(return_value=MagicMock()),
            ),
            patch(
                "posthog.temporal.session_replay.session_summary.workflow.asyncio.sleep",
                AsyncMock(),
            ),
        ):
            await self._collect(
                execute_summarize_session_video_stream(
                    session_id=mock_session_id,
                    user=mock_user,
                    team=mock_team,
                    force_restart=True,
                )
            )

        cap_mocks.atomic.assert_called_once_with(mock_team.id)
        cap_mocks.refund.assert_not_called()

    @pytest.mark.asyncio
    async def test_quota_blocked_emits_error_and_skips_workflow_start(
        self,
        cap_mocks: SimpleNamespace,
        mock_session_id: str,
        mock_user: MagicMock,
        mock_team: MagicMock,
    ):
        """When `atomic_check_and_consume` returns `allowed=False`, the generator
        yields a session-summary-error event and never starts a workflow.
        The atomic op already rolled the counter back, so no refund needed."""
        cap_mocks.atomic.return_value = MagicMock(allowed=False, used=4000, cap=4000)
        start_mock = AsyncMock()
        with (
            patch.object(SingleSessionSummary.objects, "get_summary", MagicMock(return_value=None)),
            patch(
                "posthog.temporal.session_replay.session_summary.workflow._prepare_execution",
                return_value=(None, None, None, MagicMock(), "workflow-id"),
            ),
            patch(
                "posthog.temporal.session_replay.session_summary.workflow._start_video_summary_workflow",
                start_mock,
            ),
            patch(
                "posthog.temporal.session_replay.session_summary.workflow.async_connect",
                AsyncMock(return_value=MagicMock()),
            ),
            patch("posthog.temporal.session_replay.session_summary.workflow.posthoganalytics.capture") as mock_capture,
        ):
            events = await self._collect(
                execute_summarize_session_video_stream(
                    session_id=mock_session_id,
                    user=mock_user,
                    team=mock_team,
                )
            )

        assert len(events) == 1
        assert events[0].startswith("event: session-summary-error\n")
        assert "4000/4000" in events[0]
        start_mock.assert_not_called()
        cap_mocks.refund.assert_not_called()
        mock_capture.assert_called_once()
        assert mock_capture.call_args.kwargs["event"] == "replay summary quota blocked"
        assert mock_capture.call_args.kwargs["properties"]["used"] == 4000
        assert mock_capture.call_args.kwargs["properties"]["cap"] == 4000

    @pytest.mark.asyncio
    async def test_cached_summary_fast_path_bypasses_cap_entirely(
        self,
        cap_mocks: SimpleNamespace,
        mock_session_id: str,
        mock_user: MagicMock,
        mock_team: MagicMock,
        mock_enriched_llm_json_response: dict[str, Any],
    ):
        """A cached SingleSessionSummary returns immediately — the cap MUST NOT
        be consulted at all on this path, even when the team is over the cap.
        This is the exact regression the gate-relocation fix targets."""
        cached_summary = MagicMock()
        cached_summary.id = "cached-id"
        cached_summary.summary = mock_enriched_llm_json_response
        with (
            patch.object(SingleSessionSummary.objects, "get_summary", return_value=cached_summary),
            patch(
                "posthog.temporal.session_replay.session_summary.workflow._start_video_summary_workflow"
            ) as mock_start,
        ):
            await self._collect(
                execute_summarize_session_video_stream(
                    session_id=mock_session_id,
                    user=mock_user,
                    team=mock_team,
                )
            )

        cap_mocks.atomic.assert_not_called()
        cap_mocks.refund.assert_not_called()
        mock_start.assert_not_called()


@pytest.mark.django_db
class TestVideoStreamCapEndToEnd:
    """Load-style cap regression: drive the video-stream entrypoint past the
    cap with the LLM commit point (`_start_video_summary_workflow`) stubbed
    out, so the only "real" thing under test is the cap module against the
    real Redis counter.

    Verifies, in one test:
    - Requests 1..cap pass through and bump the counter.
    - Requests cap+1..N yield `session-summary-error` and never call
      `_start_video_summary_workflow`.
    - The Redis counter ends at exactly cap (no overshoot in the sequential
      case — concurrency is covered by `test_atomic_check_and_consume_is_overshoot_free`).
    - One `replay summary quota blocked` analytics event per blocked request.

    Cap is overridden to a small value via `get_cap_for_team` so the test
    runs in <1s — the production default of 4000 would just multiply the
    iteration count, not exercise any new behavior.
    """

    @pytest.fixture(autouse=True)
    def _stub_metadata(self) -> Iterator[None]:
        # In-range metadata so the up-front length precheck is a no-op (avoids a real ClickHouse read).
        with patch.object(
            SessionReplayEvents, "get_metadata", MagicMock(return_value={"duration": 120, "active_seconds": 60})
        ):
            yield

    @pytest.fixture(autouse=True)
    def _isolate_redis_key(self, mock_team: MagicMock) -> Iterator[None]:
        from datetime import UTC, datetime

        from posthog.redis import get_client
        from posthog.session_recordings.ai_summary_cap import _redis_key

        key = _redis_key(mock_team.id, now=datetime.now(UTC))
        client = get_client()
        client.delete(key)
        try:
            yield
        finally:
            client.delete(key)

    @pytest.mark.asyncio
    async def test_cap_blocks_after_quota_exhausted_under_load(
        self,
        mock_user: MagicMock,
        mock_team: MagicMock,
        mock_enriched_llm_json_response: dict[str, Any],
    ):
        from posthog.session_recordings.ai_summary_cap import current_usage

        cap = 5
        n_iterations = cap + 3  # 5 allowed, 3 blocked

        completed_summary = MagicMock()
        completed_summary.id = "completed-id"
        completed_summary.summary = mock_enriched_llm_json_response

        # Each iteration uses a unique session_id so we can use a per-session
        # call counter instead of a global rotating side_effect — keeps the
        # mapping trivial regardless of which iterations get blocked.
        get_summary_calls: dict[str, int] = {}

        def get_summary_fn(*args: Any, **kwargs: Any) -> Any:
            sid = kwargs["session_id"]
            n = get_summary_calls.get(sid, 0)
            get_summary_calls[sid] = n + 1
            # First call per session is the cache check (miss). Any later call
            # is the post-COMPLETED read of the freshly written row.
            return None if n == 0 else completed_summary

        # Temporal handle that resolves to COMPLETED on the first describe so
        # the polling loop exits without calling handle.query.
        def _make_handle() -> MagicMock:
            handle = MagicMock()
            handle.describe = AsyncMock(return_value=MagicMock(status=WorkflowExecutionStatus.COMPLETED))
            handle.query = AsyncMock(return_value={})
            handle.result = AsyncMock(return_value=None)
            return handle

        start_mock = AsyncMock(side_effect=lambda *a, **kw: _make_handle())

        with (
            # Cap value comes from the production code path, but we override
            # the Postgres lookup so we don't need a real SignalSourceConfig.
            patch(
                "posthog.session_recordings.ai_summary_cap.get_cap_for_team",
                return_value=cap,
            ),
            patch.object(
                SingleSessionSummary.objects,
                "get_summary",
                side_effect=get_summary_fn,
            ),
            patch(
                "posthog.temporal.session_replay.session_summary.workflow._workflow_is_running",
                AsyncMock(return_value=False),
            ),
            patch(
                "posthog.temporal.session_replay.session_summary.workflow._prepare_execution",
                return_value=(None, None, None, MagicMock(), "workflow-id"),
            ),
            patch(
                "posthog.temporal.session_replay.session_summary.workflow._start_video_summary_workflow",
                start_mock,
            ),
            patch(
                "posthog.temporal.session_replay.session_summary.workflow.async_connect",
                AsyncMock(return_value=MagicMock()),
            ),
            patch(
                "posthog.temporal.session_replay.session_summary.workflow.asyncio.sleep",
                AsyncMock(),
            ),
            patch("posthog.temporal.session_replay.session_summary.workflow.posthoganalytics.capture") as mock_capture,
        ):
            allowed_count = 0
            blocked_count = 0
            for i in range(n_iterations):
                session_id = f"00000000-0000-0000-0001-{i:012d}"
                events: list[str] = []
                async for event in execute_summarize_session_video_stream(
                    session_id=session_id,
                    user=mock_user,
                    team=mock_team,
                ):
                    events.append(event)

                assert events, f"iteration {i}: generator yielded zero events"
                last = events[-1]
                if last.startswith("event: session-summary-error\n"):
                    blocked_count += 1
                    assert f"{cap}/{cap}" in last, f"iteration {i}: missing used/cap in {last!r}"
                else:
                    allowed_count += 1
                    assert any(e.startswith("event: session-summary-stream\n") for e in events), (
                        f"iteration {i}: no success event in {events!r}"
                    )

        assert allowed_count == cap, f"expected {cap} allowed, got {allowed_count}"
        assert blocked_count == n_iterations - cap, f"expected {n_iterations - cap} blocked, got {blocked_count}"

        # The LLM commit point fired exactly `cap` times — never on a blocked iteration.
        assert start_mock.call_count == cap, (
            f"_start_video_summary_workflow called {start_mock.call_count} times; expected {cap}"
        )

        # Real Redis counter advanced exactly to the cap (sequential — no overshoot expected).
        assert current_usage(mock_team.id) == cap

        # Each blocked iteration emitted exactly one quota-blocked analytics event.
        blocked_capture_calls = [
            c for c in mock_capture.call_args_list if c.kwargs.get("event") == "replay summary quota blocked"
        ]
        assert len(blocked_capture_calls) == n_iterations - cap


class TestWorkflowIsRunning:
    """`_workflow_is_running` is the discriminator between a fresh LLM run (cap
    applies) and a silent attach (cap must not). Behavior pinned with explicit
    tests so a future refactor can't quietly flip it."""

    @pytest.mark.asyncio
    async def test_returns_true_when_status_is_running(self) -> None:
        from posthog.temporal.session_replay.session_summary.workflow import _workflow_is_running

        client = MagicMock()
        handle = MagicMock()
        handle.describe = AsyncMock(return_value=MagicMock(status=WorkflowExecutionStatus.RUNNING))
        client.get_workflow_handle = MagicMock(return_value=handle)

        assert await _workflow_is_running(client, "wfid") is True

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "terminal_status",
        [
            WorkflowExecutionStatus.COMPLETED,
            WorkflowExecutionStatus.FAILED,
            WorkflowExecutionStatus.CANCELED,
            WorkflowExecutionStatus.TERMINATED,
            WorkflowExecutionStatus.TIMED_OUT,
        ],
    )
    async def test_returns_false_for_terminal_statuses(
        self,
        terminal_status: WorkflowExecutionStatus,
    ) -> None:
        from posthog.temporal.session_replay.session_summary.workflow import _workflow_is_running

        client = MagicMock()
        handle = MagicMock()
        handle.describe = AsyncMock(return_value=MagicMock(status=terminal_status))
        client.get_workflow_handle = MagicMock(return_value=handle)

        assert await _workflow_is_running(client, "wfid") is False

    @pytest.mark.asyncio
    async def test_returns_false_when_workflow_not_found(self) -> None:
        from temporalio.service import RPCError, RPCStatusCode

        from posthog.temporal.session_replay.session_summary.workflow import _workflow_is_running

        client = MagicMock()
        handle = MagicMock()
        handle.describe = AsyncMock(side_effect=RPCError("not found", RPCStatusCode.NOT_FOUND, b""))
        client.get_workflow_handle = MagicMock(return_value=handle)

        assert await _workflow_is_running(client, "wfid") is False

    @pytest.mark.asyncio
    async def test_reraises_non_not_found_rpc_errors(self) -> None:
        # An UNAVAILABLE Temporal frontend should surface, not silently bypass
        # the cap by claiming "not running".
        from temporalio.service import RPCError, RPCStatusCode

        from posthog.temporal.session_replay.session_summary.workflow import _workflow_is_running

        client = MagicMock()
        handle = MagicMock()
        handle.describe = AsyncMock(side_effect=RPCError("unavailable", RPCStatusCode.UNAVAILABLE, b""))
        client.get_workflow_handle = MagicMock(return_value=handle)

        with pytest.raises(RPCError):
            await _workflow_is_running(client, "wfid")


class TestStartVideoSummaryWorkflow:
    @pytest.mark.asyncio
    async def test_default_uses_use_existing_so_concurrent_clicks_attach(self) -> None:
        """Without ``force_restart`` we must not kill an in-flight workflow that
        another tab/user is already watching — the contract is dedup, not preempt."""
        client = MagicMock()
        client.start_workflow = AsyncMock(return_value=MagicMock())
        with patch(
            "posthog.temporal.session_replay.session_summary.workflow.async_connect",
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
            "posthog.temporal.session_replay.session_summary.workflow.async_connect",
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
            "posthog.temporal.session_replay.session_summary.workflow.async_connect",
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
                "posthog.temporal.session_replay.session_summary.workflow._execute_single_session_summary_workflow"
            ) as mock_execute,
        ):
            result = await execute_summarize_session(
                session_id=mock_session_id,
                user=mock_user,
                team=mock_team,
            )
        assert result == mock_enriched_llm_json_response
        mock_execute.assert_not_called()
