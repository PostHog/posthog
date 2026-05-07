import json
from datetime import datetime
from typing import Any

import pytest
from unittest.mock import MagicMock, patch

from posthog.session_recordings.queries.session_replay_events import SessionReplayEvents

from ee.hogai.session_summaries.session.input_data import EXTRA_SUMMARY_EVENT_FIELDS, get_session_events
from ee.hogai.session_summaries.session.prompt_data import SessionSummaryMetadata, SessionSummaryPromptData
from ee.hogai.session_summaries.session.summarize_session import (
    ExtraSummaryContext,
    generate_single_session_summary_prompt,
    get_session_data_from_db,
)

pytestmark = pytest.mark.django_db


class TestSummarizeSession:
    @pytest.mark.asyncio
    async def test_prepare_data_no_metadata(self, mock_team: MagicMock, mock_session_id: str):
        with (
            patch("ee.hogai.session_summaries.session.input_data.get_team", return_value=mock_team),
            patch.object(
                SessionReplayEvents,
                "get_metadata",
                return_value=None,
            ) as mock_get_db_metadata,
        ):
            with pytest.raises(ValueError, match=f"No session metadata found for session_id {mock_session_id}"):
                await get_session_data_from_db(session_id=mock_session_id, team_id=mock_team.id, local_reads_prod=False)
            mock_get_db_metadata.assert_called_once_with(session_id=mock_session_id, team=mock_team)

    def test_prepare_data_no_events_returns_error_data(
        self, mock_team: MagicMock, mock_raw_metadata: dict[str, Any], mock_session_id: str
    ):
        """Test that we get proper error data when no events are found (for example, for fresh real-time replays)."""
        with (
            patch(
                "ee.hogai.session_summaries.session.summarize_session.get_session_metadata",
                return_value=mock_raw_metadata,
            ),
            patch("ee.hogai.session_summaries.session.input_data.SessionReplayEvents") as mock_replay_events,
        ):
            # Mock the SessionReplayEvents DB model to return different data for each page
            mock_instance = MagicMock()
            mock_replay_events.return_value = mock_instance
            mock_instance.get_events.side_effect = [(None, None), (None, None)]
            with pytest.raises(ValueError, match=f"No columns found for session_id {mock_session_id}"):
                with patch("ee.hogai.session_summaries.session.input_data.get_team", return_value=mock_team):
                    get_session_events(
                        session_id=mock_session_id,
                        session_metadata=mock_raw_metadata,  # type: ignore[arg-type]
                        team_id=mock_team.id,
                    )
                    mock_instance.get_events.assert_called_once_with(
                        session_id=mock_session_id,
                        team_id=mock_team.id,
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
        serializable_events: list[Any] = []
        for event in events:
            serializable_event: list[Any] = []
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
        mock_session_metadata: SessionSummaryMetadata,
        mock_raw_events: list[tuple[Any, ...]],
        mock_raw_events_columns: list[str],
        mock_url_mapping: dict[str, str],
        mock_window_mapping: dict[str, str],
        focus_area: str | None,
        should_contain_focus_area: bool,
    ):
        """Test that generate_prompt generates the correct prompts with the provided data."""
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
        prompt_result = generate_single_session_summary_prompt(
            prompt_data=prompt_data,
            url_mapping_reversed=url_mapping_reversed,
            window_mapping_reversed=window_mapping_reversed,
            extra_summary_context=extra_summary_context,
        )
        summary_prompt, system_prompt = prompt_result.summary_prompt, prompt_result.system_prompt
        # Verify focus area presence
        assert "FOCUS_AREA" not in system_prompt
        assert "FOCUS_AREA" not in summary_prompt
        if should_contain_focus_area:
            assert focus_area is not None
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
