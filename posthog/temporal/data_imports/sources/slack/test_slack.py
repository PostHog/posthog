from typing import Any

from unittest.mock import MagicMock, patch

from posthog.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from posthog.temporal.data_imports.sources.slack.slack import SlackResumeConfig, _channel_messages_generator


def _make_response(payload: dict[str, Any]) -> MagicMock:
    response = MagicMock()
    response.json.return_value = payload
    response.raise_for_status.return_value = None
    response.status_code = 200
    return response


def _make_page(messages: list[dict[str, Any]], next_cursor: str = "") -> dict[str, Any]:
    return {
        "ok": True,
        "messages": messages,
        "response_metadata": {"next_cursor": next_cursor},
    }


class TestChannelMessagesGeneratorResumable:
    def test_fresh_run_saves_state_after_each_non_final_page(self) -> None:
        resume_mgr = MagicMock(spec=ResumableSourceManager)
        resume_mgr.can_resume.return_value = False

        pages = [
            _make_page([{"ts": "1700000000.000001"}], next_cursor="cursor_page_2"),
            _make_page([{"ts": "1700000001.000001"}], next_cursor="cursor_page_3"),
            _make_page([{"ts": "1700000002.000001"}], next_cursor=""),
        ]
        responses = [_make_response(p) for p in pages]

        with patch(
            "posthog.temporal.data_imports.sources.slack.slack._slack_get",
            side_effect=responses,
        ):
            items = list(_channel_messages_generator("token", "C123", resume_mgr, oldest_ts=None))

        assert len(items) == 3
        assert resume_mgr.save_state.call_count == 2
        assert resume_mgr.save_state.call_args_list[0].args[0] == SlackResumeConfig(
            channel_id="C123", next_cursor="cursor_page_2", oldest_ts=None
        )
        assert resume_mgr.save_state.call_args_list[1].args[0] == SlackResumeConfig(
            channel_id="C123", next_cursor="cursor_page_3", oldest_ts=None
        )

    def test_fresh_run_single_page_does_not_save(self) -> None:
        resume_mgr = MagicMock(spec=ResumableSourceManager)
        resume_mgr.can_resume.return_value = False

        pages = [_make_page([{"ts": "1700000000.000001"}], next_cursor="")]
        responses = [_make_response(p) for p in pages]

        with patch(
            "posthog.temporal.data_imports.sources.slack.slack._slack_get",
            side_effect=responses,
        ):
            items = list(_channel_messages_generator("token", "C123", resume_mgr, oldest_ts=None))

        assert len(items) == 1
        resume_mgr.save_state.assert_not_called()

    def test_fresh_run_with_oldest_ts_persists_it(self) -> None:
        resume_mgr = MagicMock(spec=ResumableSourceManager)
        resume_mgr.can_resume.return_value = False

        pages = [
            _make_page([{"ts": "1700000000.000001"}], next_cursor="cursor_page_2"),
            _make_page([{"ts": "1700000001.000001"}], next_cursor=""),
        ]
        responses = [_make_response(p) for p in pages]

        with patch(
            "posthog.temporal.data_imports.sources.slack.slack._slack_get",
            side_effect=responses,
        ):
            list(_channel_messages_generator("token", "C123", resume_mgr, oldest_ts="1699000000.0"))

        resume_mgr.save_state.assert_called_once_with(
            SlackResumeConfig(channel_id="C123", next_cursor="cursor_page_2", oldest_ts="1699000000.0")
        )

    def test_resume_starts_from_saved_cursor_and_skips_initial_request(self) -> None:
        resume_mgr = MagicMock(spec=ResumableSourceManager)
        resume_mgr.can_resume.return_value = True
        resume_mgr.load_state.return_value = SlackResumeConfig(
            channel_id="C123", next_cursor="saved_cursor", oldest_ts="1699000000.0"
        )

        pages = [_make_page([{"ts": "1700000500.000001"}], next_cursor="")]
        responses = [_make_response(p) for p in pages]

        with patch(
            "posthog.temporal.data_imports.sources.slack.slack._slack_get",
            side_effect=responses,
        ) as mock_get:
            items = list(_channel_messages_generator("token", "C123", resume_mgr, oldest_ts=None))

        assert len(items) == 1
        assert mock_get.call_count == 1
        call_kwargs = mock_get.call_args.kwargs
        assert call_kwargs["params"]["cursor"] == "saved_cursor"
        assert call_kwargs["params"]["oldest"] == "1699000000.0"
        resume_mgr.save_state.assert_not_called()

    def test_resume_state_for_different_channel_is_ignored(self) -> None:
        resume_mgr = MagicMock(spec=ResumableSourceManager)
        resume_mgr.can_resume.return_value = True
        resume_mgr.load_state.return_value = SlackResumeConfig(
            channel_id="C_OTHER", next_cursor="wrong_cursor", oldest_ts="9999"
        )

        pages = [_make_page([{"ts": "1700000000.000001"}], next_cursor="")]
        responses = [_make_response(p) for p in pages]

        with patch(
            "posthog.temporal.data_imports.sources.slack.slack._slack_get",
            side_effect=responses,
        ) as mock_get:
            list(_channel_messages_generator("token", "C123", resume_mgr, oldest_ts="original_oldest"))

        call_kwargs = mock_get.call_args.kwargs
        assert "cursor" not in call_kwargs["params"]
        assert call_kwargs["params"]["oldest"] == "original_oldest"

    def test_empty_first_page_yields_nothing_and_saves_nothing(self) -> None:
        resume_mgr = MagicMock(spec=ResumableSourceManager)
        resume_mgr.can_resume.return_value = False

        pages = [_make_page([], next_cursor="")]
        responses = [_make_response(p) for p in pages]

        with patch(
            "posthog.temporal.data_imports.sources.slack.slack._slack_get",
            side_effect=responses,
        ):
            items = list(_channel_messages_generator("token", "C123", resume_mgr, oldest_ts=None))

        assert items == []
        resume_mgr.save_state.assert_not_called()
