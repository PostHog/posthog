from typing import Any
from unittest.mock import MagicMock, patch

import pytest
from ee.session_recordings.session_summary.prompt_data import SessionSummaryPromptData
from ee.session_recordings.session_summary.summarize_session import ReplaySummarizer
from posthog.models import Team, User
from posthog.session_recordings.models.session_recording import SessionRecording


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
    mock_events_columns: list[str],
    mock_recording: MagicMock,
) -> tuple[SessionSummaryPromptData, dict[str, list[Any]]]:
    prompt_data = SessionSummaryPromptData()
    # Cut last two columns as they should be calculated by the summarizer
    columns = mock_events_columns[:-2]
    events_mapping = prompt_data.load_session_data(
        mock_raw_events, mock_raw_metadata, columns, mock_recording.session_id
    )
    return prompt_data, events_mapping


class TestReplaySummarizer:
    def test_summarize_recording_success(
        self,
        summarizer: ReplaySummarizer,
        mock_raw_metadata: dict[str, Any],
        mock_raw_events: list[list[Any]],
        # mock_prompt_data: tuple[SessionSummaryPromptData, dict[str, list[Any]]],
        mock_events_columns: list[str],
        mock_valid_llm_yaml_response: str,
    ):
        """
        Basic test to ensure the operations are called in the correct order.
        Most of the mocked functions are tested in other test modules.
        """
        # Cut last two columns as they should be calculated by the summarizer
        columns = mock_events_columns[:-2]
        # Mock DB/LLM dependencies
        with (
            patch(
                "ee.session_recordings.session_summary.summarize_session.get_session_metadata",
                return_value=mock_raw_metadata,
            ) as mock_get_metadata,
            patch(
                "ee.session_recordings.session_summary.summarize_session.get_session_events",
                return_value=(columns, mock_raw_events),
            ) as mock_get_events,
            patch(
                "ee.session_recordings.session_summary.summarize_session.stream_llm_session_summary",
                return_value=iter([mock_valid_llm_yaml_response]),
            ) as mock_stream_summary,
        ):
            # Get the generator (stream simulation)
            result_generator = summarizer.summarize_recording()
            # Get all results from generator (consume the stream fully)
            results = list(result_generator)
            # Verify all mocks were called correctly
            mock_get_metadata.assert_called_once_with(
                session_id="test_session_id",
                team=summarizer.team,
            )
            mock_get_events.assert_called_once_with(
                session_id="test_session_id",
                team=summarizer.team,
                session_metadata=mock_raw_metadata,
            )
            mock_stream_summary.assert_called_once()
            # Verify result structure
            assert len(results) == 1
            assert results[0] == mock_valid_llm_yaml_response

    # def test_summarize_recording_no_metadata(self, summarizer: ReplaySummarizer):
    #     with patch(
    #         "ee.session_recordings.session_summary.summarize_session.get_session_metadata",
    #         return_value=None,
    #     ):
    #         with pytest.raises(
    #             ValueError, match=f"No metadata found for session_id {summarizer.recording.session_id}"
    #         ):
    #             list(summarizer.summarize_recording())

    # def test_summarize_recording_no_events(self, summarizer: ReplaySummarizer, mock_raw_metadata: dict[str, Any]):
    #     with (
    #         patch.object(SessionReplayEvents, "get_metadata", return_value=mock_raw_metadata),
    #         patch.object(SessionReplayEvents, "get_events", return_value=(None, None)),
    #     ):
    #         with pytest.raises(ValueError, match=f"no events found for session_id {summarizer.recording.session_id}"):
    #             summarizer.summarize_recording()
