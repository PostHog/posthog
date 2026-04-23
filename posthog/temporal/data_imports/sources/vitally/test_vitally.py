from typing import Any, Optional

from unittest.mock import MagicMock, patch

from parameterized import parameterized

from posthog.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from posthog.temporal.data_imports.sources.vitally.vitally import VitallyResumeConfig, get_messages


def _make_response(json_data: dict[str, Any], status_code: int = 200) -> MagicMock:
    response = MagicMock()
    response.status_code = status_code
    response.ok = 200 <= status_code < 300
    response.json.return_value = json_data
    return response


def _make_manager(can_resume: bool = False, state: Optional[VitallyResumeConfig] = None) -> MagicMock:
    manager = MagicMock(spec=ResumableSourceManager)
    manager.can_resume.return_value = can_resume
    manager.load_state.return_value = state
    return manager


def _session_send_effects(pages: list[dict[str, Any]]) -> list[MagicMock]:
    return [_make_response(page) for page in pages]


def _run_get_messages(
    session_cls_mock: MagicMock,
    manager: MagicMock,
    pages: list[dict[str, Any]],
    *,
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Any = None,
) -> tuple[list[dict[str, Any]], list[str | None]]:
    """Drive get_messages against a mocked session, returning yielded messages
    and the list of `from` query params captured per request (the request object
    is mutated in place, so we snapshot on each send)."""
    session = session_cls_mock.return_value.__enter__.return_value
    responses = _session_send_effects(pages)
    response_iter = iter(responses)
    sent_from_params: list[str | None] = []

    def _send(prepared_request: Any) -> MagicMock:
        sent_from_params.append(prepared_request.params.get("from"))
        return next(response_iter)

    session.send.side_effect = _send
    session.prepare_request.side_effect = lambda req: req

    logger = MagicMock()
    messages = list(
        get_messages(
            secret_token="token",
            region="EU",
            subdomain=None,
            db_incremental_field_last_value=db_incremental_field_last_value,
            should_use_incremental_field=should_use_incremental_field,
            logger=logger,
            resumable_source_manager=manager,
        )
    )
    return messages, sent_from_params


class TestGetMessagesResume:
    def test_fresh_run_saves_cursor_on_each_subsequent_page(self) -> None:
        manager = _make_manager(can_resume=False)
        pages: list[dict[str, Any]] = [
            {"results": [], "next": "cursor-page-2"},
            {"results": [], "next": "cursor-page-3"},
            {"results": [], "next": None},
        ]

        with patch("posthog.temporal.data_imports.sources.vitally.vitally.requests.Session") as session_cls:
            _, from_params = _run_get_messages(session_cls, manager, pages)

        manager.can_resume.assert_called_once()
        manager.load_state.assert_not_called()
        saved_cursors = [call.args[0].cursor for call in manager.save_state.call_args_list]
        # First page has no cursor yet (no save); pages 2 and 3 each save their own cursor
        assert saved_cursors == ["cursor-page-2", "cursor-page-3"]
        # Initial request has no `from`; subsequent requests carry the advancing cursor
        assert from_params == [None, "cursor-page-2", "cursor-page-3"]

    def test_single_page_without_next_does_not_save_state(self) -> None:
        manager = _make_manager(can_resume=False)
        pages: list[dict[str, Any]] = [{"results": [], "next": None}]

        with patch("posthog.temporal.data_imports.sources.vitally.vitally.requests.Session") as session_cls:
            _run_get_messages(session_cls, manager, pages)

        manager.save_state.assert_not_called()
        manager.load_state.assert_not_called()

    def test_resume_seeds_paginator_and_skips_initial_request(self) -> None:
        manager = _make_manager(can_resume=True, state=VitallyResumeConfig(cursor="cursor-resume"))
        pages: list[dict[str, Any]] = [{"results": [], "next": None}]

        with patch("posthog.temporal.data_imports.sources.vitally.vitally.requests.Session") as session_cls:
            _, from_params = _run_get_messages(session_cls, manager, pages)

        # On resume we re-fetch the saved cursor page, then terminate
        assert from_params == ["cursor-resume"]
        manager.load_state.assert_called_once()
        # Before fetching the resumed page, state is re-saved so a second restart still works
        assert [call.args[0].cursor for call in manager.save_state.call_args_list] == ["cursor-resume"]

    def test_resume_continues_paginating_and_saves_next_cursor(self) -> None:
        manager = _make_manager(can_resume=True, state=VitallyResumeConfig(cursor="cursor-resume"))
        pages: list[dict[str, Any]] = [
            {"results": [], "next": "cursor-after-resume"},
            {"results": [], "next": None},
        ]

        with patch("posthog.temporal.data_imports.sources.vitally.vitally.requests.Session") as session_cls:
            _, from_params = _run_get_messages(session_cls, manager, pages)

        assert from_params == ["cursor-resume", "cursor-after-resume"]
        saved_cursors = [call.args[0].cursor for call in manager.save_state.call_args_list]
        assert saved_cursors == ["cursor-resume", "cursor-after-resume"]

    @parameterized.expand(
        [
            ("empty_first_page", [{"results": [], "next": None}], []),
            (
                "final_page_clears_has_next",
                [
                    {"results": [], "next": "c1"},
                    {"results": [], "next": None},
                ],
                ["c1"],
            ),
        ]
    )
    def test_fresh_run_edge_cases(
        self,
        _name: str,
        pages: list[dict[str, Any]],
        expected_saved_cursors: list[str],
    ) -> None:
        manager = _make_manager(can_resume=False)

        with patch("posthog.temporal.data_imports.sources.vitally.vitally.requests.Session") as session_cls:
            _, _ = _run_get_messages(session_cls, manager, pages)

        saved_cursors = [call.args[0].cursor for call in manager.save_state.call_args_list]
        assert saved_cursors == expected_saved_cursors

    def test_yields_messages_from_conversations(self) -> None:
        manager = _make_manager(can_resume=False)
        pages = [
            {
                "results": [{"id": "conv-1", "updatedAt": "2026-01-01T00:00:00Z"}],
                "next": None,
            }
        ]

        conv_response = MagicMock()
        conv_response.raise_for_status = MagicMock()
        conv_response.json.return_value = {
            "messages": [{"id": "m1"}, {"id": "m2"}],
        }
        conv_response.status_code = 200
        conv_response.text = ""

        with (
            patch("posthog.temporal.data_imports.sources.vitally.vitally.requests.Session") as session_cls,
            patch(
                "posthog.temporal.data_imports.sources.vitally.vitally.requests.get",
                return_value=conv_response,
            ),
        ):
            messages, _ = _run_get_messages(session_cls, manager, pages)

        assert [m["id"] for m in messages] == ["m1", "m2"]
        # conversation_updated_at must be copied onto each message
        assert all(m["conversation_updated_at"] == "2026-01-01T00:00:00Z" for m in messages)
        # Single-page run without a `next` link never saves resume state
        manager.save_state.assert_not_called()
