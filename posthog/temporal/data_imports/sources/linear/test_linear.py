import copy
from collections.abc import Iterable
from typing import Any, cast

import pytest
from unittest.mock import MagicMock, patch

from parameterized import parameterized

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


def _make_resumable_manager(*, saved: LinearResumeConfig | None = None) -> MagicMock:
    manager = MagicMock()
    manager.load_state.return_value = saved
    return manager


# (has_next, end_cursor) per page. Nodes are synthetic; only pagination matters.
PageSpec = tuple[bool, str | None]


class TestMakePaginatedRequest:
    @parameterized.expand(
        [
            # Fresh runs
            ("fresh_multi_page", None, [(True, "c1"), (True, "c2"), (False, None)], None, ["c1", "c2"], False),
            ("fresh_single_empty", None, [(False, None)], None, [], False),
            ("fresh_with_filter", None, [(True, "c1"), (False, None)], "2026-01-01T00:00:00Z", ["c1"], False),
            # Resume runs
            ("resume_final_page_only", "saved-c", [(False, None)], None, [], True),
            ("resume_then_more_pages", "saved-c", [(True, "c1"), (False, None)], None, ["c1"], True),
            (
                "resume_with_filter",
                "saved-c",
                [(True, "c1"), (False, None)],
                "2026-01-01T00:00:00Z",
                ["c1"],
                True,
            ),
        ]
    )
    @patch("posthog.temporal.data_imports.sources.linear.linear.make_tracked_session")
    def test_pagination_state(
        self,
        _name: str,
        saved_cursor: str | None,
        page_specs: list[PageSpec],
        filter_gte: str | None,
        expected_save_cursors: list[str],
        first_request_has_cursor: bool,
        mock_session_cls: MagicMock,
    ) -> None:
        session = MagicMock()
        responses = [_make_response([{"id": f"{i}"}], has_next, end) for i, (has_next, end) in enumerate(page_specs)]
        snapshots = _capture_post_calls(session, responses)
        mock_session_cls.return_value = session

        saved_config = LinearResumeConfig(cursor=saved_cursor) if saved_cursor is not None else None
        manager = _make_resumable_manager(saved=saved_config)
        logger = MagicMock()

        list(
            _make_paginated_request(
                access_token="tok",
                endpoint_name="issues",
                logger=logger,
                resumable_source_manager=manager,
                updated_at_gte=filter_gte,
            )
        )

        # Resume path: first request carries the saved cursor; fresh path: no cursor on first request.
        if first_request_has_cursor:
            assert snapshots[0]["cursor"] == saved_cursor
        else:
            assert "cursor" not in snapshots[0]

        # Each non-final page checkpoints the cursor of the next page.
        assert manager.save_state.call_args_list == [((LinearResumeConfig(cursor=c),),) for c in expected_save_cursors]

        # The updated_at filter, if any, must be applied on every page including the resumed first request.
        if filter_gte is not None:
            for variables in snapshots:
                assert variables["filter"] == {"updatedAt": {"gt": filter_gte}}

    @parameterized.expand([("null_end_cursor", None), ("empty_end_cursor", "")])
    @patch("posthog.temporal.data_imports.sources.linear.linear.make_tracked_session")
    def test_raises_when_has_next_page_but_cursor_missing(
        self,
        _name: str,
        bad_cursor: str | None,
        mock_session_cls: MagicMock,
    ) -> None:
        session = MagicMock()
        session.post.side_effect = [_make_response([{"id": "a"}], True, bad_cursor)]
        mock_session_cls.return_value = session

        manager = _make_resumable_manager()
        logger = MagicMock()

        with pytest.raises(Exception, match="endCursor is empty"):
            list(
                _make_paginated_request(
                    access_token="tok",
                    endpoint_name="issues",
                    logger=logger,
                    resumable_source_manager=manager,
                )
            )

        manager.save_state.assert_not_called()
        assert session.post.call_count == 1


class TestLinearSource:
    def test_source_response_wires_primary_key_and_items(self) -> None:
        manager = _make_resumable_manager()
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

    @patch("posthog.temporal.data_imports.sources.linear.linear.make_tracked_session")
    def test_get_rows_threads_manager_through(self, mock_session_cls: MagicMock) -> None:
        session = MagicMock()
        session.post.side_effect = [
            _make_response([{"id": "a"}], True, "cursor-a"),
            _make_response([{"id": "b"}], False, None),
        ]
        mock_session_cls.return_value = session

        manager = _make_resumable_manager()
        logger = MagicMock()

        response = linear_source(
            access_token="tok",
            endpoint_name="issues",
            logger=logger,
            resumable_source_manager=manager,
        )
        pages = list(cast(Iterable[Any], response.items()))

        assert pages == [[{"id": "a"}], [{"id": "b"}]]
        manager.save_state.assert_called_once_with(LinearResumeConfig(cursor="cursor-a"))
