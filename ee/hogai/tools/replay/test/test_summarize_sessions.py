from collections.abc import AsyncIterator
from datetime import UTC, datetime
from typing import Any

from posthog.test.base import BaseTest
from unittest.mock import AsyncMock, MagicMock, patch

from langchain_core.runnables import RunnableConfig

from posthog.temporal.session_replay.session_summary_group.types import SessionSummaryStreamUpdate

from ee.hogai.session_summaries.session_group.patterns import EnrichedSessionGroupSummaryPatternsList
from ee.hogai.session_summaries.session_group.summarize_session_group import (
    FoundSessionsWithTimestamps,
    SessionRecordingPartition,
)
from ee.hogai.tools.replay.summarize_sessions import SessionSummariesResult, SummarizeSessionsTool
from ee.hogai.utils.types import AssistantState
from ee.hogai.utils.types.base import NodePath

MIN_TS = datetime(2026, 7, 29, 8, 0, 0, tzinfo=UTC)
MAX_TS = datetime(2026, 7, 29, 9, 0, 0, tzinfo=UTC)
REQUESTED_SESSION_IDS = [f"s-{index}" for index in range(7)]


class _NoopHeartbeater:
    async def __aenter__(self) -> "_NoopHeartbeater":
        return self

    async def __aexit__(self, *_args: Any) -> bool:
        return False


class TestSummarizeSessionsTool(BaseTest):
    async def _create_tool(self) -> SummarizeSessionsTool:
        config: RunnableConfig = RunnableConfig()
        return await SummarizeSessionsTool.create_tool_class(
            team=self.team,
            user=self.user,
            state=AssistantState(messages=[]),
            config=config,
            node_path=(NodePath(name="test_node", tool_call_id="test_tool_call_id", message_id="test"),),
        )

    @staticmethod
    def _metadata(session_ids: list[str]) -> dict[str, dict]:
        return {
            session_id: {
                "first_url": "",
                "active_duration_s": 0,
                "distinct_id": "",
                "start_time": None,
                "snapshot_source": "web",
            }
            for session_id in session_ids
        }

    async def test_group_summary_skips_the_missing_recording_and_reports_it(self) -> None:
        found_session_ids, dropped_session_ids = REQUESTED_SESSION_IDS[:6], REQUESTED_SESSION_IDS[6:]
        tool = await self._create_tool()
        workflow_kwargs: dict[str, Any] = {}

        async def fake_execute_summarize_session_group(
            **kwargs: Any,
        ) -> AsyncIterator[tuple[SessionSummaryStreamUpdate, Any]]:
            workflow_kwargs.update(kwargs)
            # The workflow persists the sessions dropped before the run, so they come back with the final result
            yield (
                SessionSummaryStreamUpdate.FINAL_RESULT,
                (
                    EnrichedSessionGroupSummaryPatternsList(patterns=[]),
                    "summary-id",
                    list(kwargs["pre_run_failed_sessions"]),
                ),
            )

        with (
            patch.object(
                SummarizeSessionsTool, "_get_session_metadata", return_value=self._metadata(REQUESTED_SESSION_IDS)
            ),
            patch(
                "ee.hogai.tools.replay.summarize_sessions.find_sessions_timestamps_dropping_missing",
                return_value=FoundSessionsWithTimestamps(
                    found_session_ids=found_session_ids,
                    missing_session_ids=dropped_session_ids,
                    min_timestamp=MIN_TS,
                    max_timestamp=MAX_TS,
                ),
            ),
            patch("ee.hogai.tools.replay.summarize_sessions.Heartbeater", _NoopHeartbeater),
            patch(
                "ee.hogai.tools.replay.summarize_sessions.execute_summarize_session_group",
                fake_execute_summarize_session_group,
            ),
        ):
            result = await tool._summarize_sessions(
                session_ids=REQUESTED_SESSION_IDS, summary_title="Test", session_ids_source="explicit"
            )

        assert workflow_kwargs["session_ids"] == found_session_ids
        assert result.summary_id == "summary-id"
        assert [(fs.session_id, fs.category) for fs in result.failed_sessions] == [("s-6", "skipped")]
        assert "only 6 of 7 sessions were included" in result.content

    async def test_group_summary_falls_back_to_individual_when_too_few_recordings_are_left(self) -> None:
        found_session_ids, dropped_session_ids = REQUESTED_SESSION_IDS[:5], REQUESTED_SESSION_IDS[5:]
        tool = await self._create_tool()
        mock_summarize_session = AsyncMock(return_value={})
        mock_summarize_session_group = MagicMock()

        with (
            patch.object(
                SummarizeSessionsTool, "_get_session_metadata", return_value=self._metadata(REQUESTED_SESSION_IDS)
            ),
            patch(
                "ee.hogai.tools.replay.summarize_sessions.find_sessions_timestamps_dropping_missing",
                return_value=FoundSessionsWithTimestamps(
                    found_session_ids=found_session_ids,
                    missing_session_ids=dropped_session_ids,
                    min_timestamp=MIN_TS,
                    max_timestamp=MAX_TS,
                ),
            ),
            patch("ee.hogai.tools.replay.summarize_sessions.Heartbeater", _NoopHeartbeater),
            patch(
                "ee.hogai.tools.replay.summarize_sessions.execute_summarize_session_group",
                mock_summarize_session_group,
            ),
            patch("ee.hogai.tools.replay.summarize_sessions.execute_summarize_session", mock_summarize_session),
            patch("ee.hogai.tools.replay.summarize_sessions.SingleSessionSummaryStringifier") as mock_stringifier,
        ):
            mock_stringifier.return_value.stringify_session.return_value = "Session summary"
            result = await tool._summarize_sessions(
                session_ids=REQUESTED_SESSION_IDS, summary_title="Test", session_ids_source="explicit"
            )

        mock_summarize_session_group.assert_not_called()
        assert sorted(call.kwargs["session_id"] for call in mock_summarize_session.await_args_list) == found_session_ids
        assert result.summary_id is None
        assert [(fs.session_id, fs.category) for fs in result.failed_sessions] == [
            ("s-5", "skipped"),
            ("s-6", "skipped"),
        ]
        assert "only 5 of 7 sessions were included" in result.content

    async def test_validate_specific_session_ids_dedupes_and_partitions(self) -> None:
        tool = await self._create_tool()
        with patch(
            "posthog.session_recordings.queries.session_replay_events.SessionReplayEvents.sessions_found_with_timestamps",
            return_value=MagicMock(session_ids={"s-1", "s-2"}),
        ):
            partition = tool._validate_specific_session_ids(["s-1", "s-1", "s-2", "s-3"])
        assert partition.found_session_ids == ["s-1", "s-2"]
        assert partition.missing_session_ids == ["s-3"]

    async def test_sessions_missing_at_validation_time_are_reported(self) -> None:
        # An explicitly selected recording that already expired is reported, not silently dropped
        tool = await self._create_tool()
        workflow_kwargs: dict[str, Any] = {}

        async def fake_execute_summarize_session_group(
            **kwargs: Any,
        ) -> AsyncIterator[tuple[SessionSummaryStreamUpdate, Any]]:
            workflow_kwargs.update(kwargs)
            yield (
                SessionSummaryStreamUpdate.FINAL_RESULT,
                (
                    EnrichedSessionGroupSummaryPatternsList(patterns=[]),
                    "summary-id",
                    list(kwargs["pre_run_failed_sessions"]),
                ),
            )

        with (
            patch.object(
                SummarizeSessionsTool, "_get_session_metadata", return_value=self._metadata(REQUESTED_SESSION_IDS)
            ),
            patch(
                "ee.hogai.tools.replay.summarize_sessions.find_sessions_timestamps_dropping_missing",
                return_value=FoundSessionsWithTimestamps(
                    found_session_ids=REQUESTED_SESSION_IDS,
                    missing_session_ids=[],
                    min_timestamp=MIN_TS,
                    max_timestamp=MAX_TS,
                ),
            ),
            patch("ee.hogai.tools.replay.summarize_sessions.Heartbeater", _NoopHeartbeater),
            patch(
                "ee.hogai.tools.replay.summarize_sessions.execute_summarize_session_group",
                fake_execute_summarize_session_group,
            ),
        ):
            result = await tool._summarize_sessions(
                session_ids=REQUESTED_SESSION_IDS,
                summary_title="Test",
                session_ids_source="explicit",
                pre_dropped_session_ids=["s-expired"],
            )

        assert workflow_kwargs["session_ids"] == REQUESTED_SESSION_IDS
        assert [(fs.session_id, fs.category) for fs in workflow_kwargs["pre_run_failed_sessions"]] == [
            ("s-expired", "skipped")
        ]
        assert result.summary_id == "summary-id"
        assert [(fs.session_id, fs.category) for fs in result.failed_sessions] == [("s-expired", "skipped")]
        assert "only 7 of 8 sessions were included" in result.content

    async def test_individual_summary_failures_are_counted_in_the_note(self) -> None:
        session_ids = REQUESTED_SESSION_IDS[:3]
        tool = await self._create_tool()

        async def mock_execute_summarize_session(**kwargs: Any) -> dict:
            if kwargs["session_id"] == "s-1":
                raise ValueError("summary generation failed")
            return {}

        with (
            patch.object(SummarizeSessionsTool, "_get_session_metadata", return_value=self._metadata(session_ids)),
            patch("ee.hogai.tools.replay.summarize_sessions.Heartbeater", _NoopHeartbeater),
            patch("ee.hogai.tools.replay.summarize_sessions.execute_summarize_session", mock_execute_summarize_session),
            patch("ee.hogai.tools.replay.summarize_sessions.SingleSessionSummaryStringifier") as mock_stringifier,
        ):
            mock_stringifier.return_value.stringify_session.return_value = "Session summary"
            result = await tool._summarize_sessions(
                session_ids=session_ids, summary_title="Test", session_ids_source="explicit"
            )

        assert result.summary_id is None
        assert [(fs.session_id, fs.category) for fs in result.failed_sessions] == [("s-1", "summarization_failed")]
        assert "only 2 of 3 sessions were included" in result.content
        assert result.content.count("Session summary") == 2

    async def test_tracking_reports_the_executed_path_after_fallback(self) -> None:
        # A group request that falls back to individual summaries should not be tracked as a group run
        tool = await self._create_tool()
        fallback_result = SessionSummariesResult(content="Session summary", summary_id=None, failed_sessions=[])

        with (
            patch.object(
                SummarizeSessionsTool,
                "_validate_specific_session_ids",
                return_value=SessionRecordingPartition(found_session_ids=REQUESTED_SESSION_IDS, missing_session_ids=[]),
            ),
            patch.object(SummarizeSessionsTool, "_summarize_sessions", AsyncMock(return_value=fallback_result)),
            patch("ee.hogai.tools.replay.summarize_sessions.capture_session_summary_started") as mock_started,
            patch("ee.hogai.tools.replay.summarize_sessions.capture_session_summary_generated") as mock_generated,
        ):
            content, artifact = await tool._arun_impl(
                recordings_filters_or_explicit_session_ids=REQUESTED_SESSION_IDS, summary_title="Test"
            )

        assert content == "Session summary"
        assert artifact is None
        assert mock_started.call_args.kwargs["summary_type"] == "group"
        assert mock_generated.call_args.kwargs["summary_type"] == "single"
