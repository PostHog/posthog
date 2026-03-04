import json
from datetime import datetime

import pytest
from unittest.mock import MagicMock, patch

from ee.hogai.tools.replay.summarize_sessions import SummarizeSessionsTool


class MockDispatcher:
    def __init__(self):
        self.updates: list[str] = []

    def update(self, content):
        self.updates.append(content)


def create_tool_with_mock_dispatcher() -> tuple[SummarizeSessionsTool, MockDispatcher]:
    tool = SummarizeSessionsTool.__new__(SummarizeSessionsTool)
    tool._team = MagicMock()
    tool._user = MagicMock()
    dispatcher = MockDispatcher()
    tool._dispatcher = dispatcher
    return tool, dispatcher


class TestDispatchStructuredUpdate:
    def test_serializes_dict_to_json(self):
        tool, dispatcher = create_tool_with_mock_dispatcher()
        data = {"type": "sessions_discovered", "sessions": []}
        tool._dispatch_structured_update(data)

        assert len(dispatcher.updates) == 1
        assert json.loads(dispatcher.updates[0]) == data

    def test_preserves_nested_structure(self):
        tool, dispatcher = create_tool_with_mock_dispatcher()
        data = {
            "type": "progress",
            "status_changes": [{"id": "s1", "status": "summarizing"}],
            "phase": "watching_sessions",
            "completed_count": 0,
            "total_count": 3,
            "patterns_found": [],
        }
        tool._dispatch_structured_update(data)

        parsed = json.loads(dispatcher.updates[0])
        assert parsed["status_changes"][0]["id"] == "s1"
        assert parsed["phase"] == "watching_sessions"


class TestDispatchSessionProgress:
    @pytest.mark.parametrize(
        "status,completed,total",
        [
            ("summarizing", 0, 3),
            ("summarized", 1, 3),
            ("failed", 2, 3),
        ],
    )
    def test_emits_progress_update(self, status, completed, total):
        tool, dispatcher = create_tool_with_mock_dispatcher()
        tool._dispatch_session_progress("session-abc", status, completed, total)

        assert len(dispatcher.updates) == 1
        parsed = json.loads(dispatcher.updates[0])
        assert parsed["type"] == "progress"
        assert parsed["status_changes"] == [{"id": "session-abc", "status": status}]
        assert parsed["phase"] == "watching_sessions"
        assert parsed["completed_count"] == completed
        assert parsed["total_count"] == total
        assert parsed["patterns_found"] == []


class TestGetSessionMetadata:
    def test_returns_metadata_for_found_sessions(self):
        tool, _ = create_tool_with_mock_dispatcher()
        mock_start_time = datetime(2025, 3, 1, 10, 0, 0)
        mock_metadata = {
            "s1": {
                "first_url": "https://example.com/page1",
                "active_seconds": 120,
                "distinct_id": "user-alpha",
                "start_time": mock_start_time,
                "snapshot_source": "web",
            },
        }

        with patch(
            "posthog.session_recordings.queries.session_replay_events.SessionReplayEvents.get_group_metadata",
            return_value=mock_metadata,
        ):
            result = tool._get_session_metadata(["s1"])

        assert result["s1"]["first_url"] == "https://example.com/page1"
        assert result["s1"]["active_duration_s"] == 120
        assert result["s1"]["distinct_id"] == "user-alpha"
        assert result["s1"]["start_time"] == mock_start_time.isoformat()
        assert result["s1"]["snapshot_source"] == "web"

    def test_returns_defaults_for_missing_sessions(self):
        tool, _ = create_tool_with_mock_dispatcher()

        with patch(
            "posthog.session_recordings.queries.session_replay_events.SessionReplayEvents.get_group_metadata",
            return_value={},
        ):
            result = tool._get_session_metadata(["missing-session"])

        assert result["missing-session"] == {
            "first_url": "",
            "active_duration_s": 0,
            "distinct_id": "",
            "start_time": None,
            "snapshot_source": "web",
        }

    def test_handles_none_values_in_metadata(self):
        tool, _ = create_tool_with_mock_dispatcher()
        mock_metadata = {
            "s1": {
                "first_url": None,
                "active_seconds": None,
                "distinct_id": None,
                "start_time": None,
                "snapshot_source": None,
            },
        }

        with patch(
            "posthog.session_recordings.queries.session_replay_events.SessionReplayEvents.get_group_metadata",
            return_value=mock_metadata,
        ):
            result = tool._get_session_metadata(["s1"])

        assert result["s1"]["first_url"] == ""
        assert result["s1"]["active_duration_s"] == 0
        assert result["s1"]["distinct_id"] == ""
        assert result["s1"]["start_time"] is None
        assert result["s1"]["snapshot_source"] == "web"

    def test_preserves_session_id_order(self):
        tool, _ = create_tool_with_mock_dispatcher()
        mock_metadata = {
            "s2": {
                "first_url": "https://example.com/b",
                "active_seconds": 60,
                "distinct_id": "user-b",
                "start_time": None,
                "snapshot_source": "web",
            },
            "s1": {
                "first_url": "https://example.com/a",
                "active_seconds": 120,
                "distinct_id": "user-a",
                "start_time": None,
                "snapshot_source": "mobile",
            },
        }

        with patch(
            "posthog.session_recordings.queries.session_replay_events.SessionReplayEvents.get_group_metadata",
            return_value=mock_metadata,
        ):
            result = tool._get_session_metadata(["s1", "s2", "s3"])

        assert list(result.keys()) == ["s1", "s2", "s3"]
        assert result["s1"]["snapshot_source"] == "mobile"
        assert result["s3"]["first_url"] == ""
