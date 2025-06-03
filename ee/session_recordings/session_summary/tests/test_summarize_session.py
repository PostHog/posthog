from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from ee.session_recordings.session_summary.input_data import EXTRA_SUMMARY_EVENT_FIELDS
from ee.session_recordings.session_summary.summarize_session import ReplaySummarizer
from posthog.models import Team, User
from posthog.session_recordings.models.session_recording import SessionRecording
from posthog.session_recordings.queries.session_replay_events import SessionReplayEvents


class AsyncIterator:
    def __init__(self, items):
        self.items = items

    def __aiter__(self):
        return self

    async def __anext__(self):
        try:
            return next(self.items)
        except StopIteration:
            raise StopAsyncIteration


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
    return ReplaySummarizer(mock_recording.session_id, mock_user, mock_team)


class TestReplaySummarizer:
    def test_summarize_recording_success(
        self,
        summarizer: ReplaySummarizer,
        mock_raw_metadata: dict[str, Any],
        mock_raw_events: list[tuple[Any, ...]],
        mock_raw_events_columns: list[str],
        mock_valid_llm_yaml_response: str,
    ):
        """
        Basic test to ensure the operations are called in the correct order.
        Most of the mocked functions are tested in other test modules.
        """
        columns = mock_raw_events_columns
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
                local_reads_prod=False,
            )
            mock_get_events.assert_called_once_with(
                session_id="test_session_id",
                team=summarizer.team,
                session_metadata=mock_raw_metadata,
                local_reads_prod=False,
            )
            mock_stream_summary.assert_called_once()
            # Verify result structure
            # TODO: Test timing header when start timing streaming
            # assert "content" in result
            # assert "timings_header" in result

            assert len(results) == 1
            assert results[0] == mock_valid_llm_yaml_response

    def test_summarize_recording_no_metadata(self, summarizer: ReplaySummarizer):
        with patch.object(
            SessionReplayEvents,
            "get_metadata",
            return_value=None,
        ) as mock_get_db_metadata:
            with pytest.raises(ValueError, match=f"No session metadata found for session_id {summarizer.session_id}"):
                list(summarizer.summarize_recording())
            mock_get_db_metadata.assert_called_once_with(
                session_id="test_session_id",
                team=summarizer.team,
            )

    def test_summarize_recording_no_columns(self, summarizer: ReplaySummarizer, mock_raw_metadata: dict[str, Any]):
        with (
            patch(
                "ee.session_recordings.session_summary.summarize_session.get_session_metadata",
                return_value=mock_raw_metadata,
            ),
            patch("ee.session_recordings.session_summary.input_data.SessionReplayEvents") as mock_replay_events,
        ):
            # Mock the SessionReplayEvents DB model to return different data for each page
            mock_instance = MagicMock()
            mock_replay_events.return_value = mock_instance
            mock_instance.get_events.side_effect = [(None, None), (None, None)]
            with pytest.raises(ValueError, match=f"No columns found for session_id {summarizer.session_id}"):
                list(summarizer.summarize_recording())
                mock_instance.get_events.assert_called_once_with(
                    session_id="test_session_id",
                    team=summarizer.team,
                    metadata=mock_raw_metadata,
                    events_to_ignore=["$feature_flag_called"],
                    extra_fields=EXTRA_SUMMARY_EVENT_FIELDS,
                    page=0,
                    limit=3000,
                )

    @pytest.mark.asyncio
    async def test_stream_recording_summary_asgi(
        self,
        summarizer: ReplaySummarizer,
        mock_raw_metadata: dict[str, Any],
        mock_raw_events: list[tuple[Any, ...]],
        mock_raw_events_columns: list[str],
        mock_valid_llm_yaml_response: str,
    ):
        """Test the ASGI streaming path."""
        with (
            patch("posthog.settings.SERVER_GATEWAY_INTERFACE", "ASGI"),
            patch(
                "ee.session_recordings.session_summary.summarize_session.get_session_metadata",
                return_value=mock_raw_metadata,
            ),
            patch(
                "ee.session_recordings.session_summary.summarize_session.get_session_events",
                return_value=(mock_raw_events_columns, mock_raw_events),
            ),
            patch(
                "ee.session_recordings.session_summary.summarize_session.stream_llm_session_summary",
                return_value=AsyncIterator(iter([mock_valid_llm_yaml_response])),
            ),
        ):
            async_gen = summarizer.stream_recording_summary()
            results = [chunk async for chunk in async_gen]
            assert len(results) == 1
            assert results[0] == mock_valid_llm_yaml_response

    def test_summarize_recording_no_events_sse_error(
        self, summarizer: ReplaySummarizer, mock_raw_metadata: dict[str, Any], mock_raw_events_columns: list[str]
    ):
        """Test that we yield a proper SSE error when no events are found (for example, for fresh real-time replays)."""
        with (
            patch(
                "ee.session_recordings.session_summary.summarize_session.get_session_metadata",
                return_value=mock_raw_metadata,
            ),
            patch.object(
                SessionReplayEvents,
                "get_events",
                return_value=(mock_raw_events_columns, []),  # Return columns but no events
            ) as mock_get_db_events,
        ):
            result = list(summarizer.summarize_recording())
            assert len(result) == 1
            assert (
                result[0]
                == "event: session-summary-error\ndata: No events found for this replay yet. Please try again in a few minutes.\n\n"
            )
            mock_get_db_events.assert_called_once_with(
                session_id="test_session_id",
                team=summarizer.team,
                metadata=mock_raw_metadata,
                events_to_ignore=["$feature_flag_called"],
                extra_fields=EXTRA_SUMMARY_EVENT_FIELDS,
                page=0,
                limit=3000,
            )
