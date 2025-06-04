from typing import Any
from unittest.mock import MagicMock, patch
import json
from datetime import datetime

import pytest

from ee.session_recordings.session_summary.input_data import EXTRA_SUMMARY_EVENT_FIELDS
from ee.session_recordings.session_summary.summarize_session import ExtraSummaryContext, ReplaySummarizer
from posthog.models import Team, User
from posthog.session_recordings.models.session_recording import SessionRecording
from posthog.session_recordings.queries.session_replay_events import SessionReplayEvents
from ee.session_recordings.session_summary.prompt_data import SessionSummaryMetadata, SessionSummaryPromptData


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
            empty_context = ExtraSummaryContext()
            result_generator = summarizer.summarize_recording(extra_summary_context=empty_context)
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
        empty_context = ExtraSummaryContext()
        with patch.object(
            SessionReplayEvents,
            "get_metadata",
            return_value=None,
        ) as mock_get_db_metadata:
            with pytest.raises(ValueError, match=f"No session metadata found for session_id {summarizer.session_id}"):
                list(summarizer.summarize_recording(extra_summary_context=empty_context))
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
            empty_context = ExtraSummaryContext()
            with pytest.raises(ValueError, match=f"No columns found for session_id {summarizer.session_id}"):
                list(summarizer.summarize_recording(extra_summary_context=empty_context))
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
        empty_context = ExtraSummaryContext()
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
            result = list(summarizer.summarize_recording(extra_summary_context=empty_context))
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

    @staticmethod
    def _make_events_json_serializable(events: list[tuple[Any, ...]]) -> list[list[Any]]:
        """
        Convert events into JSON-serializable format by converting tuples to lists and datetimes to ISO strings.
        """
        serializable_events = []
        for event in events:
            serializable_event = []
            for value in event:
                if isinstance(value, datetime):
                    serializable_event.append(value.isoformat())
                elif isinstance(value, tuple):
                    serializable_event.append(list(value))
                else:
                    serializable_event.append(value)
            serializable_events.append(serializable_event)
        return serializable_events

    @pytest.mark.parametrize(
        "focus_area,should_contain_focus_area",
        [
            ("unexpected focus area that won't be in the prompt naturally", True),
            (None, False),
        ],
    )
    def test_generate_prompt(
        self,
        summarizer: ReplaySummarizer,
        mock_session_metadata: SessionSummaryMetadata,
        mock_raw_events: list[tuple[Any, ...]],
        mock_raw_events_columns: list[str],
        mock_url_mapping: dict[str, str],
        mock_window_mapping: dict[str, str],
        focus_area: str | None,
        should_contain_focus_area: bool,
    ):
        """Test that _generate_prompt generates the correct prompts with the provided data."""
        prompt_data = SessionSummaryPromptData(
            columns=mock_raw_events_columns,
            results=self._make_events_json_serializable(mock_raw_events),
            metadata=mock_session_metadata,
            url_mapping=mock_url_mapping,
            window_id_mapping=mock_window_mapping,
        )
        # Reverse mappings for easier reference in the prompt
        url_mapping_reversed = {v: k for k, v in prompt_data.url_mapping.items()}
        window_mapping_reversed = {v: k for k, v in prompt_data.window_id_mapping.items()}
        extra_summary_context = ExtraSummaryContext(focus_area=focus_area)
        # Generate prompts
        summary_prompt, system_prompt = summarizer._generate_prompt(
            prompt_data=prompt_data,
            url_mapping_reversed=url_mapping_reversed,
            window_mapping_reversed=window_mapping_reversed,
            extra_summary_context=extra_summary_context,
        )
        # Verify focus area presence
        assert "FOCUS_AREA" not in system_prompt
        assert "FOCUS_AREA" not in summary_prompt
        if should_contain_focus_area:
            assert focus_area in system_prompt
            assert focus_area in summary_prompt
        # Verify that prompt variables were replaced with actual data
        assert "EVENTS_DATA" not in summary_prompt
        assert "SESSION_METADATA" not in summary_prompt
        assert "URL_MAPPING" not in summary_prompt
        assert "WINDOW_ID_MAPPING" not in summary_prompt
        assert "SUMMARY_EXAMPLE" not in summary_prompt
        # Verify events data matches
        events_data_start = summary_prompt.find("<events_input>\n```\n") + len("<events_input>\n```\n")
        events_data_end = summary_prompt.find("\n```\n</events_input>")
        events_data = json.loads(summary_prompt[events_data_start:events_data_end].strip())
        assert events_data == self._make_events_json_serializable(mock_raw_events)
        # Verify URL mapping data matches
        url_mapping_start = summary_prompt.find("<url_mapping_input>\n```\n") + len("<url_mapping_input>\n```\n")
        url_mapping_end = summary_prompt.find("\n```\n</url_mapping_input>")
        url_mapping_data = json.loads(summary_prompt[url_mapping_start:url_mapping_end].strip())
        assert url_mapping_data == url_mapping_reversed
        # Verify window mapping data matches
        window_mapping_start = summary_prompt.find("<window_mapping_input>\n```\n") + len(
            "<window_mapping_input>\n```\n"
        )
        window_mapping_end = summary_prompt.find("\n```\n</window_mapping_input>")
        window_mapping_data = json.loads(summary_prompt[window_mapping_start:window_mapping_end].strip())
        assert window_mapping_data == window_mapping_reversed
        # Verify session metadata matches
        session_metadata_start = summary_prompt.find("<session_metadata_input>\n```\n") + len(
            "<session_metadata_input>\n```\n"
        )
        session_metadata_end = summary_prompt.find("\n```\n</session_metadata_input>")
        session_metadata_data = json.loads(summary_prompt[session_metadata_start:session_metadata_end].strip())
        assert session_metadata_data == mock_session_metadata.to_dict()
