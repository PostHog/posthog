from datetime import datetime
from typing import Any
from unittest.mock import MagicMock, patch

import pytest
from ee.session_recordings.ai.output_data import RawSessionSummarySerializer
from ee.session_recordings.ai.prompt_data import SessionSummaryPromptData
from ee.session_recordings.session_summary.summarize_session import ReplaySummarizer
from posthog.models import Team, User
from posthog.session_recordings.models.session_recording import SessionRecording
from posthog.session_recordings.queries.session_replay_events import SessionReplayEvents


@pytest.fixture
def mock_recording() -> MagicMock:
    recording = MagicMock(spec=SessionRecording)
    recording.session_id = "test_session_id"
    return recording


@pytest.fixture
def mock_user() -> MagicMock:
    user = MagicMock(spec=User)
    return user


@pytest.fixture
def mock_team() -> MagicMock:
    team = MagicMock(spec=Team)
    return team


@pytest.fixture
def summarizer(
    mock_recording: MagicMock,
    mock_user: MagicMock,
    mock_team: MagicMock,
) -> ReplaySummarizer:
    return ReplaySummarizer(mock_recording, mock_user, mock_team)


@pytest.fixture
def mock_prompt_data(
    mock_raw_metadata: dict[str, Any],
    mock_raw_events: list[list[Any]],
    mock_recording: MagicMock,
) -> tuple[SessionSummaryPromptData, dict[str, list[Any]]]:
    prompt_data = SessionSummaryPromptData()
    raw_columns = [
        "event",
        "timestamp",
        "elements_chain_href",
        "elements_chain_texts",
        "elements_chain_elements",
        "$window_id",
        "$current_url",
        "$event_type",
    ]
    events_mapping = prompt_data.load_session_data(
        mock_raw_events, mock_raw_metadata, raw_columns, mock_recording.session_id
    )
    return prompt_data, events_mapping


class TestReplaySummarizer:
    def test_summarize_recording_success(
        self,
        summarizer: ReplaySummarizer,
        mock_raw_metadata: dict[str, Any],
        mock_raw_events: list[list[Any]],
        mock_prompt_data: tuple[SessionSummaryPromptData, dict[str, list[Any]]],
    ):
        """
        Basic test to ensure the operations are called in the correct order.
        Most of the mocked functions are tested in other test modules.
        """
        prompt_data, events_mapping = mock_prompt_data

        # Mock dependencies
        with (
            patch.object(
                ReplaySummarizer, "_get_session_metadata", return_value=mock_raw_metadata
            ) as mock_get_metadata,
            patch.object(
                ReplaySummarizer,
                "_get_session_events",
                return_value=(mock_prompt_data[0].columns, mock_raw_events),
            ) as mock_get_events,
            patch(
                "ee.session_recordings.session_summary.summarize_session.SessionSummaryPromptData"
            ) as mock_prompt_data_class,
            patch(
                "ee.session_recordings.session_summary.summarize_session.get_raw_llm_session_summary"
            ) as mock_get_summary,
            patch(
                "ee.session_recordings.session_summary.summarize_session.enrich_raw_session_summary_with_events_meta"
            ) as mock_enrich_summary,
        ):
            # Mock prompt data
            mock_prompt_instance = MagicMock()
            mock_prompt_instance.columns = prompt_data.columns
            mock_prompt_instance.url_mapping = prompt_data.url_mapping
            mock_prompt_instance.window_id_mapping = prompt_data.window_id_mapping
            mock_prompt_instance.metadata.start_time = datetime(2025, 4, 1, 11, 13, 33, 315000)
            # Return the mocked events mapping
            mock_prompt_instance.load_session_data.return_value = events_mapping
            mock_prompt_data_class.return_value = mock_prompt_instance
            # Setup mock summary
            mock_summary = RawSessionSummarySerializer({"summary": "test", "key_events": []})
            mock_get_summary.return_value = mock_summary
            mock_enrich_summary.return_value = mock_summary
            result = summarizer.summarize_recording()
            # Verify all mocks were called correctly
            mock_get_metadata.assert_called_once_with("test_session_id", summarizer.team)
            mock_get_events.assert_called_once_with("test_session_id", mock_raw_metadata, summarizer.team)
            mock_prompt_instance.load_session_data.assert_called_once()
            mock_get_summary.assert_called_once()
            mock_enrich_summary.assert_called_once()
            # Verify result structure
            assert "content" in result
            assert "timings" in result
            assert result["content"] == {"summary": "test", "key_events": []}

    def test_summarize_recording_no_metadata(self, summarizer: ReplaySummarizer):
        with patch.object(SessionReplayEvents, "get_metadata", return_value=None):
            with pytest.raises(
                ValueError, match=f"no session metadata found for session_id {summarizer.recording.session_id}"
            ):
                summarizer.summarize_recording()

    def test_summarize_recording_no_events(self, summarizer: ReplaySummarizer, mock_raw_metadata: dict[str, Any]):
        with (
            patch.object(SessionReplayEvents, "get_metadata", return_value=mock_raw_metadata),
            patch.object(SessionReplayEvents, "get_events", return_value=(None, None)),
        ):
            with pytest.raises(ValueError, match=f"no events found for session_id {summarizer.recording.session_id}"):
                summarizer.summarize_recording()
