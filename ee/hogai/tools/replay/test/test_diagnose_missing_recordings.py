from typing import Any

from posthog.test.base import NonAtomicBaseTest
from unittest.mock import AsyncMock, patch

from langchain_core.runnables import RunnableConfig
from parameterized import parameterized

from ee.hogai.context.context import AssistantContextManager
from ee.hogai.tools.replay.diagnose_missing_recordings import (
    VERDICT_AD_BLOCKED,
    VERDICT_BUFFERING_EMPTY,
    VERDICT_CAPTURED,
    VERDICT_DISABLED,
    VERDICT_DISABLED_PROJECT,
    VERDICT_FLUSH_BLOCKED,
    VERDICT_NO_EVENTS,
    VERDICT_PAUSED,
    VERDICT_SAMPLED_OUT,
    VERDICT_TRIGGER_PENDING,
    VERDICT_UNKNOWN,
    DiagnoseMissingRecordingsTool,
    _classify_signals,
)
from ee.hogai.utils.types import AssistantState
from ee.hogai.utils.types.base import NodePath


class TestClassifySignals(NonAtomicBaseTest):
    @parameterized.expand(
        [
            (
                "captured_via_has_recording",
                {"has_recording": True, "recording_status": "active"},
                VERDICT_CAPTURED,
            ),
            (
                "ad_blocked_via_script_not_loaded",
                {"script_not_loaded": True, "recording_status": "buffering"},
                VERDICT_AD_BLOCKED,
            ),
            (
                "disabled_via_recording_status",
                {"recording_status": "disabled"},
                VERDICT_DISABLED,
            ),
            (
                "trigger_pending_when_url_trigger_pending_and_none_matched",
                {
                    "recording_status": "buffering",
                    "url_trigger": "trigger_pending",
                    "event_trigger": None,
                    "flag_trigger": None,
                },
                VERDICT_TRIGGER_PENDING,
            ),
            (
                "sampled_out_via_start_reason",
                {"start_reason": "sampled_out"},
                VERDICT_SAMPLED_OUT,
            ),
            (
                "buffering_empty_when_buffering_with_no_data",
                {"recording_status": "buffering", "buffer_length": 0, "flushed_size": 0},
                VERDICT_BUFFERING_EMPTY,
            ),
            (
                "captured_when_sampled_status",
                {"recording_status": "sampled"},
                VERDICT_CAPTURED,
            ),
            (
                "captured_when_active_with_flushed_size",
                {"recording_status": "active", "max_flushed_size": 1024},
                VERDICT_CAPTURED,
            ),
            (
                "paused_via_recording_status",
                {"recording_status": "paused"},
                VERDICT_PAUSED,
            ),
            (
                "flush_blocked_when_buffer_climbs_but_no_flush",
                {"recording_status": "active", "max_buffer_length": 200, "max_flushed_size": 0},
                VERDICT_FLUSH_BLOCKED,
            ),
            (
                "unknown_when_no_signals_match",
                {},
                VERDICT_UNKNOWN,
            ),
            (
                "trigger_matched_does_not_count_as_pending",
                {
                    "url_trigger": "trigger_pending",
                    "event_trigger": "trigger_matched",
                    "recording_status": "active",
                    "max_flushed_size": 100,
                },
                VERDICT_CAPTURED,
            ),
            (
                "ad_blocked_takes_priority_over_disabled",
                {"script_not_loaded": True, "recording_status": "disabled"},
                VERDICT_AD_BLOCKED,
            ),
            (
                "captured_takes_priority_over_everything",
                {
                    "has_recording": True,
                    "script_not_loaded": True,
                    "recording_status": "disabled",
                },
                VERDICT_CAPTURED,
            ),
        ]
    )
    def test_classify_signals(self, _name: str, row: dict[str, Any], expected: str) -> None:
        self.assertEqual(_classify_signals(row), expected)


class TestDiagnoseMissingRecordingsTool(NonAtomicBaseTest):
    CLASS_DATA_LEVEL_SETUP = False

    def _make_tool(self) -> DiagnoseMissingRecordingsTool:
        config: RunnableConfig = RunnableConfig()
        context_manager = AssistantContextManager(team=self.team, user=self.user, config=config)
        return DiagnoseMissingRecordingsTool(
            team=self.team,
            user=self.user,
            state=AssistantState(messages=[]),
            config=config,
            context_manager=context_manager,
            node_path=(NodePath(name="test", tool_call_id="t", message_id="m"),),
        )

    async def test_returns_disabled_project_when_replay_opt_in_is_false(self) -> None:
        self.team.session_recording_opt_in = False
        await self.team.asave()

        tool = self._make_tool()
        with patch.object(DiagnoseMissingRecordingsTool, "_query_recent_signals", new=AsyncMock(return_value=[])):
            content, artifact = await tool._arun_impl(session_id=None)

        self.assertIsNotNone(artifact)
        assert artifact is not None
        self.assertEqual(len(artifact["verdicts"]), 1)
        self.assertEqual(artifact["verdicts"][0]["verdict"], VERDICT_DISABLED_PROJECT)
        self.assertIn("disabled at the project level", content)

    async def test_returns_no_events_when_replay_enabled_but_no_signals(self) -> None:
        self.team.session_recording_opt_in = True
        await self.team.asave()

        tool = self._make_tool()
        with patch.object(DiagnoseMissingRecordingsTool, "_query_session_signals", new=AsyncMock(return_value=[])):
            content, artifact = await tool._arun_impl(session_id="abc")

        assert artifact is not None
        verdicts = artifact["verdicts"]
        self.assertEqual(len(verdicts), 1)
        self.assertEqual(verdicts[0]["verdict"], VERDICT_NO_EVENTS)
        self.assertIn("Diagnosis for session `abc`", content)

    async def test_session_diagnosis_returns_ad_blocked_verdict(self) -> None:
        self.team.session_recording_opt_in = True
        await self.team.asave()

        tool = self._make_tool()
        signal_row = {
            "has_recording": False,
            "recording_status": "buffering",
            "start_reason": None,
            "script_not_loaded": True,
            "url_trigger": None,
            "event_trigger": None,
            "flag_trigger": None,
            "sample_rate": 1.0,
            "buffer_length": 0,
            "flushed_size": 0,
            "max_buffer_length": 0,
            "max_flushed_size": 0,
            "sdk_library": "web",
            "sdk_version": "1.369.2",
            "event_count": 5,
        }
        with patch.object(
            DiagnoseMissingRecordingsTool,
            "_query_session_signals",
            new=AsyncMock(return_value=[signal_row]),
        ):
            content, artifact = await tool._arun_impl(session_id="ad-blocked-session")

        assert artifact is not None
        self.assertEqual(artifact["verdicts"][0]["verdict"], VERDICT_AD_BLOCKED)
        self.assertIn("ad_blocked", content)
        self.assertIn("recorder script", content)
        self.assertIn("script_not_loaded=True", content)

    async def test_session_diagnosis_returns_sampled_out_verdict(self) -> None:
        self.team.session_recording_opt_in = True
        await self.team.asave()

        tool = self._make_tool()
        signal_row = {
            "has_recording": False,
            "recording_status": "buffering",
            "start_reason": "sampled_out",
            "script_not_loaded": False,
            "url_trigger": None,
            "event_trigger": None,
            "flag_trigger": None,
            "sample_rate": 0.1,
            "buffer_length": 0,
            "flushed_size": 0,
            "max_buffer_length": 0,
            "max_flushed_size": 0,
            "sdk_library": "web",
            "sdk_version": "1.369.2",
            "event_count": 3,
        }
        with patch.object(
            DiagnoseMissingRecordingsTool,
            "_query_session_signals",
            new=AsyncMock(return_value=[signal_row]),
        ):
            content, artifact = await tool._arun_impl(session_id="sampled-out-session")

        assert artifact is not None
        self.assertEqual(artifact["verdicts"][0]["verdict"], VERDICT_SAMPLED_OUT)
        self.assertIn("sampled_out", content)

    async def test_project_wide_diagnosis_aggregates_verdicts(self) -> None:
        self.team.session_recording_opt_in = True
        await self.team.asave()

        tool = self._make_tool()
        signals = [
            {
                "recording_status": "disabled",
                "event_count": 10,
            },
            {
                "recording_status": "disabled",
                "event_count": 8,
            },
            {
                "recording_status": "active",
                "max_flushed_size": 4096,
                "event_count": 12,
            },
        ]
        with patch.object(
            DiagnoseMissingRecordingsTool,
            "_query_recent_signals",
            new=AsyncMock(return_value=signals),
        ):
            content, artifact = await tool._arun_impl(session_id=None)

        assert artifact is not None
        verdicts = {v["verdict"]: v["row_count"] for v in artifact["verdicts"]}
        self.assertEqual(verdicts.get(VERDICT_DISABLED), 2)
        self.assertEqual(verdicts.get(VERDICT_CAPTURED), 1)
        self.assertIn("Project-wide replay diagnosis", content)

    async def test_team_settings_are_returned_in_artifact(self) -> None:
        self.team.session_recording_opt_in = True
        self.team.session_recording_sample_rate = 0.5
        self.team.session_recording_minimum_duration_milliseconds = 2000
        self.team.session_recording_url_trigger_config = [{"url": "/checkout", "matching": "regex"}]
        await self.team.asave()

        tool = self._make_tool()
        with patch.object(DiagnoseMissingRecordingsTool, "_query_recent_signals", new=AsyncMock(return_value=[])):
            _, artifact = await tool._arun_impl(session_id=None)

        assert artifact is not None
        settings = artifact["team_settings"]
        self.assertTrue(settings["session_recording_opt_in"])
        self.assertEqual(settings["session_recording_sample_rate"], 0.5)
        self.assertEqual(settings["session_recording_minimum_duration_milliseconds"], 2000)
        self.assertEqual(settings["session_recording_url_trigger_count"], 1)

    async def test_query_failure_is_reported_gracefully(self) -> None:
        self.team.session_recording_opt_in = True
        await self.team.asave()

        tool = self._make_tool()
        with patch.object(
            DiagnoseMissingRecordingsTool,
            "_query_session_signals",
            new=AsyncMock(side_effect=RuntimeError("clickhouse boom")),
        ):
            content, artifact = await tool._arun_impl(session_id="some-session")

        self.assertIsNone(artifact)
        self.assertIn("clickhouse boom", content)
        self.assertIn("troubleshooting", content)
