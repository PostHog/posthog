from typing import Any
from unittest.mock import MagicMock, patch
import json
from datetime import datetime

import pytest
from temporalio.client import WorkflowExecutionStatus

from ee.hogai.utils.asgi import SyncIterableToAsync
from ee.session_recordings.session_summary.input_data import EXTRA_SUMMARY_EVENT_FIELDS, get_session_events
from ee.session_recordings.session_summary.summarize_session import (
    ExtraSummaryContext,
    prepare_data_for_single_session_summary,
    generate_single_session_summary_prompt,
)
from ee.session_recordings.session_summary.stream import stream_recording_summary
from ee.session_recordings.session_summary.utils import serialize_to_sse_event
from posthog.temporal.ai.session_summary.summarize_session import execute_summarize_session_stream
from posthog.session_recordings.queries.session_replay_events import SessionReplayEvents
from ee.session_recordings.session_summary.prompt_data import SessionSummaryMetadata, SessionSummaryPromptData

pytestmark = pytest.mark.django_db


class TestSummarizeSession:
    def test_execute_summarize_session_stream_success(
        self, mock_user: MagicMock, mock_team: MagicMock, mock_valid_llm_yaml_response: str, mock_session_id: str
    ):
        """
        Basic test to ensure the operations are called in the correct order.
        Most of the mocked functions are tested in other test modules.
        """
        # Mock DB/LLM dependencies
        with (
            patch("posthog.temporal.ai.session_summary.summarize_session._start_workflow") as mock_workflow,
            patch("posthog.temporal.ai.session_summary.summarize_session.asyncio.run") as mock_asyncio_run,
        ):
            # Mock workflow handle
            mock_handle = MagicMock()
            mock_workflow.return_value = mock_handle
            mock_desc = MagicMock()
            mock_desc.status = WorkflowExecutionStatus.COMPLETED
            mock_asyncio_run.side_effect = [mock_handle, (mock_desc, mock_valid_llm_yaml_response)]
            # Get the generator (stream simulation)
            empty_context = ExtraSummaryContext()
            result_generator = execute_summarize_session_stream(
                session_id=mock_session_id, user_id=mock_user.id, team=mock_team, extra_summary_context=empty_context
            )
            # Get all results from generator (consume the stream fully)
            results = list(result_generator)
            # Verify all mocks were called correctly
            assert len(results) == 1
            assert results[0] == serialize_to_sse_event(
                event_label="session-summary-stream",
                event_data=mock_valid_llm_yaml_response,
            )

    @pytest.mark.asyncio
    async def test_prepare_data_no_metadata(self, mock_user: MagicMock, mock_team: MagicMock, mock_session_id: str):
        empty_context = ExtraSummaryContext()
        with (
            patch("ee.session_recordings.session_summary.input_data.get_team", return_value=mock_team),
            patch.object(
                SessionReplayEvents,
                "get_metadata",
                return_value=None,
            ) as mock_get_db_metadata,
        ):
            with pytest.raises(ValueError, match=f"No session metadata found for session_id {mock_session_id}"):
                await prepare_data_for_single_session_summary(
                    session_id=mock_session_id,
                    user_id=mock_user.id,
                    team_id=mock_team.id,
                    extra_summary_context=empty_context,
                )
            mock_get_db_metadata.assert_called_once_with(
                session_id=mock_session_id,
                team_id=mock_team.id,
            )

    def test_prepare_data_no_events_returns_error_data(
        self, mock_team: MagicMock, mock_raw_metadata: dict[str, Any], mock_session_id: str
    ):
        """Test that we get proper error data when no events are found (for example, for fresh real-time replays)."""
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
            with pytest.raises(ValueError, match=f"No columns found for session_id {mock_session_id}"):
                with patch("ee.session_recordings.session_summary.input_data.get_team", return_value=mock_team):
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

    @pytest.mark.asyncio
    async def test_stream_recording_summary_asgi(
        self,
        mock_user: MagicMock,
        mock_team: MagicMock,
        mock_loaded_llm_json_response: dict[str, Any],
        mock_session_id: str,
    ):
        """Test the ASGI streaming path."""
        ready_summary = serialize_to_sse_event(
            event_label="session-summary-stream", event_data=json.dumps(mock_loaded_llm_json_response)
        )
        with (
            patch("ee.session_recordings.session_summary.stream.SERVER_GATEWAY_INTERFACE", "ASGI"),
            patch(
                "ee.session_recordings.session_summary.stream.execute_summarize_session_stream",
                return_value=iter([ready_summary]),
            ) as mock_execute,
        ):
            async_gen = stream_recording_summary(session_id=mock_session_id, user_id=mock_user.id, team=mock_team)
            assert isinstance(async_gen, SyncIterableToAsync)
            results = [chunk async for chunk in async_gen]
            assert len(results) == 1
            assert results[0] == ready_summary
            mock_execute.assert_called_once_with(
                session_id=mock_session_id,
                user_id=mock_user.id,
                team=mock_team,
                extra_summary_context=None,
                local_reads_prod=False,
            )

    def test_stream_recording_summary_wsgi(
        self,
        mock_user: MagicMock,
        mock_team: MagicMock,
        mock_loaded_llm_json_response: dict[str, Any],
        mock_session_id: str,
    ):
        """Test the WSGI (non-ASGI) streaming path."""
        ready_summary = serialize_to_sse_event(
            event_label="session-summary-stream", event_data=json.dumps(mock_loaded_llm_json_response)
        )
        with (
            patch("ee.session_recordings.session_summary.stream.SERVER_GATEWAY_INTERFACE", "WSGI"),
            patch(
                "ee.session_recordings.session_summary.stream.execute_summarize_session_stream",
                return_value=iter([ready_summary]),
            ) as mock_execute,
        ):
            result_gen = stream_recording_summary(session_id=mock_session_id, user_id=mock_user.id, team=mock_team)
            results = list(result_gen)  # type: ignore[arg-type]
            assert len(results) == 1
            assert results[0] == ready_summary
            mock_execute.assert_called_once_with(
                session_id=mock_session_id,
                user_id=mock_user.id,
                team=mock_team,
                extra_summary_context=None,
                local_reads_prod=False,
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
