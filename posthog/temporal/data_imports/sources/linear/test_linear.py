import copy
from typing import Any

from unittest.mock import MagicMock, patch

from posthog.temporal.data_imports.sources.linear.linear import (
    LinearResumeConfig,
    _make_paginated_request,
    linear_source,
)


def _make_response(nodes: list[dict[str, Any]], has_next_page: bool, end_cursor: str | None) -> MagicMock:
    response = MagicMock()
    response.status_code = 200
    response.ok = True
    response.json.return_value = {
        "data": {
            "issues": {
                "nodes": nodes,
                "pageInfo": {"hasNextPage": has_next_page, "endCursor": end_cursor},
            }
        }
    }
    return response


def _capture_post_calls(session: MagicMock, responses: list[MagicMock]) -> list[dict[str, Any]]:
    """Configure session.post to record a deep-copied snapshot of variables at each call.

    The paginator mutates a single `variables` dict across pages, so recorded calls all
    reference the same object. Snapshotting here gives us a per-call view for assertions.
    """
    snapshots: list[dict[str, Any]] = []
    response_iter = iter(responses)

    def side_effect(*_args: object, **kwargs: object) -> MagicMock:
        json_payload = kwargs.get("json")
        variables = json_payload.get("variables") if isinstance(json_payload, dict) else None
        snapshots.append(copy.deepcopy(variables) if variables is not None else {})
        return next(response_iter)

    session.post.side_effect = side_effect
    return snapshots


def _make_resumable_manager(*, can_resume: bool = False, saved: LinearResumeConfig | None = None) -> MagicMock:
    manager = MagicMock()
    manager.can_resume.return_value = can_resume
    manager.load_state.return_value = saved
    return manager


class TestMakePaginatedRequest:
    @patch("posthog.temporal.data_imports.sources.linear.linear.requests.Session")
    def test_fresh_run_saves_cursor_after_each_page_with_next(self, mock_session_cls: MagicMock) -> None:
        session = MagicMock()
        snapshots = _capture_post_calls(
            session,
            [
                _make_response([{"id": "1"}], True, "cursor-1"),
                _make_response([{"id": "2"}], True, "cursor-2"),
                _make_response([{"id": "3"}], False, None),
            ],
        )
        mock_session_cls.return_value = session

        manager = _make_resumable_manager(can_resume=False)
        logger = MagicMock()

        pages = list(
            _make_paginated_request(
                access_token="tok",
                endpoint_name="issues",
                logger=logger,
                resumable_source_manager=manager,
            )
        )

        assert pages == [[{"id": "1"}], [{"id": "2"}], [{"id": "3"}]]
        manager.load_state.assert_not_called()
        # Saved after page 1 and page 2 (both had hasNextPage=True), not after the final page.
        assert manager.save_state.call_args_list == [
            ((LinearResumeConfig(cursor="cursor-1"),),),
            ((LinearResumeConfig(cursor="cursor-2"),),),
        ]
        # First request must NOT carry a cursor; subsequent ones do.
        assert "cursor" not in snapshots[0]
        assert snapshots[1]["cursor"] == "cursor-1"
        assert snapshots[2]["cursor"] == "cursor-2"

    @patch("posthog.temporal.data_imports.sources.linear.linear.requests.Session")
    def test_resume_seeds_cursor_from_saved_state(self, mock_session_cls: MagicMock) -> None:
        session = MagicMock()
        snapshots = _capture_post_calls(
            session,
            [_make_response([{"id": "42"}], False, None)],
        )
        mock_session_cls.return_value = session

        manager = _make_resumable_manager(can_resume=True, saved=LinearResumeConfig(cursor="saved-cursor"))
        logger = MagicMock()

        pages = list(
            _make_paginated_request(
                access_token="tok",
                endpoint_name="issues",
                logger=logger,
                resumable_source_manager=manager,
            )
        )

        assert pages == [[{"id": "42"}]]
        manager.load_state.assert_called_once()
        # The very first request should carry the resumed cursor, not start over.
        assert snapshots[0]["cursor"] == "saved-cursor"
        # Final page — no save on a page that has no next.
        manager.save_state.assert_not_called()

    @patch("posthog.temporal.data_imports.sources.linear.linear.requests.Session")
    def test_empty_single_page_does_not_save_state(self, mock_session_cls: MagicMock) -> None:
        session = MagicMock()
        session.post.return_value = _make_response([], False, None)
        mock_session_cls.return_value = session

        manager = _make_resumable_manager(can_resume=False)
        logger = MagicMock()

        pages = list(
            _make_paginated_request(
                access_token="tok",
                endpoint_name="issues",
                logger=logger,
                resumable_source_manager=manager,
            )
        )

        assert pages == [[]]
        manager.save_state.assert_not_called()

    @patch("posthog.temporal.data_imports.sources.linear.linear.requests.Session")
    def test_incremental_filter_preserved_across_pages(self, mock_session_cls: MagicMock) -> None:
        session = MagicMock()
        snapshots = _capture_post_calls(
            session,
            [
                _make_response([{"id": "1"}], True, "cursor-1"),
                _make_response([{"id": "2"}], False, None),
            ],
        )
        mock_session_cls.return_value = session

        manager = _make_resumable_manager(can_resume=False)
        logger = MagicMock()

        list(
            _make_paginated_request(
                access_token="tok",
                endpoint_name="issues",
                logger=logger,
                resumable_source_manager=manager,
                updated_at_gte="2026-01-01T00:00:00Z",
            )
        )

        for variables in snapshots:
            assert variables["filter"] == {"updatedAt": {"gt": "2026-01-01T00:00:00Z"}}


class TestLinearSource:
    def test_source_response_wires_primary_key_and_items(self) -> None:
        manager = _make_resumable_manager(can_resume=False)
        logger = MagicMock()

        response = linear_source(
            access_token="tok",
            endpoint_name="issues",
            logger=logger,
            resumable_source_manager=manager,
        )

        assert response.name == "issues"
        assert response.primary_keys == ["id"]
        assert callable(response.items)

    @patch("posthog.temporal.data_imports.sources.linear.linear.requests.Session")
    def test_get_rows_threads_manager_through(self, mock_session_cls: MagicMock) -> None:
        session = MagicMock()
        session.post.side_effect = [
            _make_response([{"id": "a"}], True, "cursor-a"),
            _make_response([{"id": "b"}], False, None),
        ]
        mock_session_cls.return_value = session

        manager = _make_resumable_manager(can_resume=False)
        logger = MagicMock()

        response = linear_source(
            access_token="tok",
            endpoint_name="issues",
            logger=logger,
            resumable_source_manager=manager,
        )
        pages = list(response.items())

        assert pages == [[{"id": "a"}], [{"id": "b"}]]
        manager.save_state.assert_called_once_with(LinearResumeConfig(cursor="cursor-a"))
