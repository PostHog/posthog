from typing import Any

from unittest.mock import MagicMock, patch

from parameterized import parameterized

from posthog.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from posthog.temporal.data_imports.sources.common.webhook_s3 import WebhookSourceManager
from posthog.temporal.data_imports.sources.slack.slack import (
    SlackResumeConfig,
    _channel_messages_generator,
    _fetch_all_channels,
    _fetch_channels_by_type,
    slack_source,
)


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


def _make_channel_page(channels: list[dict[str, Any]], next_cursor: str = "") -> dict[str, Any]:
    return {
        "ok": True,
        "channels": channels,
        "response_metadata": {"next_cursor": next_cursor},
    }


class TestFetchChannelsByType:
    @parameterized.expand(
        [
            (
                "public_with_authed_user_ignores_user_scoping",
                "public_channel",
                "U_INSTALLER",
                "https://slack.com/api/conversations.list",
                False,
            ),
            (
                "private_with_authed_user_scopes_to_installer",
                "private_channel",
                "U_INSTALLER",
                "https://slack.com/api/users.conversations",
                True,
            ),
            (
                "private_without_authed_user_omits_user_param",
                "private_channel",
                None,
                "https://slack.com/api/users.conversations",
                False,
            ),
        ]
    )
    def test_routes_to_expected_endpoint(
        self,
        _name: str,
        channel_type: str,
        authed_user: str | None,
        expected_url: str,
        expects_user_param: bool,
    ) -> None:
        responses = [_make_response(_make_channel_page([{"id": "X1", "name": "x"}]))]
        with patch(
            "posthog.temporal.data_imports.sources.slack.slack._slack_get",
            side_effect=responses,
        ) as mock_get:
            channels = _fetch_channels_by_type("token", channel_type, authed_user=authed_user)

        assert channels == [{"id": "X1", "name": "x"}]
        assert mock_get.call_args.args[0] == expected_url
        params = mock_get.call_args.kwargs["params"]
        assert params["types"] == channel_type
        if expects_user_param:
            assert params["user"] == authed_user
        else:
            assert "user" not in params

    def test_paginates_until_cursor_empty(self) -> None:
        pages = [
            _make_channel_page([{"id": "C1", "name": "a"}], next_cursor="page2"),
            _make_channel_page([{"id": "C2", "name": "b"}], next_cursor=""),
        ]
        responses = [_make_response(p) for p in pages]
        with patch(
            "posthog.temporal.data_imports.sources.slack.slack._slack_get",
            side_effect=responses,
        ) as mock_get:
            channels = _fetch_channels_by_type("token", "public_channel")

        assert [c["id"] for c in channels] == ["C1", "C2"]
        assert mock_get.call_count == 2
        assert mock_get.call_args_list[1].kwargs["params"]["cursor"] == "page2"


class TestFetchAllChannels:
    def test_combines_public_and_private(self) -> None:
        pages = [
            _make_channel_page([{"id": "C1", "name": "general"}], next_cursor=""),
            _make_channel_page([{"id": "G1", "name": "secret"}], next_cursor=""),
        ]
        responses = [_make_response(p) for p in pages]
        with patch(
            "posthog.temporal.data_imports.sources.slack.slack._slack_get",
            side_effect=responses,
        ) as mock_get:
            channels = _fetch_all_channels("token", authed_user="U_INSTALLER")

        assert [c["id"] for c in channels] == ["C1", "G1"]
        assert mock_get.call_count == 2
        first_url, second_url = mock_get.call_args_list[0].args[0], mock_get.call_args_list[1].args[0]
        assert first_url == "https://slack.com/api/conversations.list"
        assert second_url == "https://slack.com/api/users.conversations"
        # public call must not carry user= scoping; private call must
        assert "user" not in mock_get.call_args_list[0].kwargs["params"]
        assert mock_get.call_args_list[1].kwargs["params"]["user"] == "U_INSTALLER"


class TestSlackSourceChannelsEndpoint:
    def _build_source(self, authed_user: str | None) -> Any:
        return slack_source(
            access_token="token",
            endpoint="$channels",
            team_id=1,
            job_id="job-1",
            webhook_source_manager=MagicMock(spec=WebhookSourceManager),
            resumable_source_manager=MagicMock(spec=ResumableSourceManager),
            authed_user=authed_user,
        )

    @parameterized.expand(
        [
            (
                "with_authed_user",
                "U_INSTALLER",
                [{"id": "C1", "name": "general"}, {"id": "G1", "name": "secret"}],
            ),
            (
                "without_authed_user",
                None,
                [],
            ),
        ]
    )
    def test_uses_fetch_all_channels_and_threads_authed_user(
        self,
        _name: str,
        authed_user: str | None,
        sample: list[dict[str, Any]],
    ) -> None:
        with patch(
            "posthog.temporal.data_imports.sources.slack.slack._fetch_all_channels",
            return_value=sample,
        ) as mock_fetch:
            response = self._build_source(authed_user=authed_user)
            items = list(response.items())

        assert items == sample
        mock_fetch.assert_called_once_with("token", authed_user)
