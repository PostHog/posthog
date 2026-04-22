from typing import Any

from unittest.mock import MagicMock, patch

from parameterized import parameterized

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
    @parameterized.expand(
        [
            (
                "multi_page_saves_each_non_final_cursor",
                [
                    _make_page([{"ts": "1700000000.000001"}], next_cursor="cursor_page_2"),
                    _make_page([{"ts": "1700000001.000001"}], next_cursor="cursor_page_3"),
                    _make_page([{"ts": "1700000002.000001"}], next_cursor=""),
                ],
                None,
                3,
                [
                    SlackResumeConfig(channel_id="C123", next_cursor="cursor_page_2", oldest_ts=None),
                    SlackResumeConfig(channel_id="C123", next_cursor="cursor_page_3", oldest_ts=None),
                ],
            ),
            (
                "single_page_does_not_save",
                [_make_page([{"ts": "1700000000.000001"}], next_cursor="")],
                None,
                1,
                [],
            ),
            (
                "oldest_ts_is_persisted_in_state",
                [
                    _make_page([{"ts": "1700000000.000001"}], next_cursor="cursor_page_2"),
                    _make_page([{"ts": "1700000001.000001"}], next_cursor=""),
                ],
                "1699000000.0",
                2,
                [SlackResumeConfig(channel_id="C123", next_cursor="cursor_page_2", oldest_ts="1699000000.0")],
            ),
            (
                "empty_first_page_is_noop",
                [_make_page([], next_cursor="")],
                None,
                0,
                [],
            ),
            (
                "multi_page_saves_after_thread_replies_are_drained",
                # page 1 has a parent with 2 replies -> conversations.replies is called
                # between page 1 and page 2. save_state must fire only after the replies
                # have been yielded, producing exactly one save with cursor_page_2.
                [
                    _make_page(
                        [{"ts": "1700000000.000001", "reply_count": 2}],
                        next_cursor="cursor_page_2",
                    ),
                    _make_page(
                        [
                            # conversations.replies includes the parent; it gets filtered.
                            {"ts": "1700000000.000001", "thread_ts": "1700000000.000001"},
                            {"ts": "1700000000.000002", "thread_ts": "1700000000.000001"},
                            {"ts": "1700000000.000003", "thread_ts": "1700000000.000001"},
                        ],
                        next_cursor="",
                    ),
                    _make_page([{"ts": "1700000001.000001"}], next_cursor=""),
                ],
                None,
                4,  # 1 parent + 2 replies from page 1 + 1 message on page 2
                [SlackResumeConfig(channel_id="C123", next_cursor="cursor_page_2", oldest_ts=None)],
            ),
        ]
    )
    def test_fresh_run(
        self,
        _name: str,
        pages: list[dict[str, Any]],
        oldest_ts: str | None,
        expected_item_count: int,
        expected_save_calls: list[SlackResumeConfig],
    ) -> None:
        resume_mgr = MagicMock(spec=ResumableSourceManager)
        resume_mgr.load_state.return_value = None

        responses = [_make_response(p) for p in pages]
        with patch(
            "posthog.temporal.data_imports.sources.slack.slack._slack_get",
            side_effect=responses,
        ):
            items = list(_channel_messages_generator("token", "C123", resume_mgr, oldest_ts=oldest_ts))

        assert len(items) == expected_item_count
        assert resume_mgr.save_state.call_count == len(expected_save_calls)
        actual_save_args = [call.args[0] for call in resume_mgr.save_state.call_args_list]
        assert actual_save_args == expected_save_calls

    def test_resume_starts_from_saved_cursor_and_skips_initial_request(self) -> None:
        resume_mgr = MagicMock(spec=ResumableSourceManager)
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
