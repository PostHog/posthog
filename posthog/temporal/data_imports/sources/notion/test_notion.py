import copy
from collections.abc import Iterable
from typing import Any, cast

import pytest
from unittest.mock import MagicMock, patch

from parameterized import parameterized

from posthog.temporal.data_imports.sources.notion.notion import (
    NotionResumeConfig,
    _flatten_database_row,
    _flatten_property,
    _paginate,
    notion_source,
    validate_credentials,
)
from posthog.temporal.data_imports.sources.notion.settings import NOTION_API_URL, database_rows_schema_name


def _make_response(results: list[dict[str, Any]], has_more: bool, next_cursor: str | None) -> MagicMock:
    response = MagicMock()
    response.status_code = 200
    response.ok = True
    response.json.return_value = {
        "results": results,
        "has_more": has_more,
        "next_cursor": next_cursor,
    }
    return response


def _capture_post_calls(session: MagicMock, responses: list[MagicMock]) -> list[dict[str, Any]]:
    """Snapshot the JSON body sent on each POST so we can assert per-page state."""
    snapshots: list[dict[str, Any]] = []
    response_iter = iter(responses)

    def side_effect(*_args: object, **kwargs: object) -> MagicMock:
        json_body = kwargs.get("json")
        snapshots.append(copy.deepcopy(json_body) if json_body is not None else {})
        return next(response_iter)

    session.post.side_effect = side_effect
    return snapshots


def _make_resumable_manager(*, saved: NotionResumeConfig | None = None) -> MagicMock:
    manager = MagicMock()
    manager.load_state.return_value = saved
    return manager


# (has_more, next_cursor) per page
PageSpec = tuple[bool, str | None]


class TestPaginate:
    @parameterized.expand(
        [
            # (test_id, saved_cursor, page_specs, expected_save_cursors, first_request_has_cursor)
            ("fresh_multi_page", None, [(True, "c1"), (True, "c2"), (False, None)], ["c1", "c2"], False),
            ("fresh_single_page", None, [(False, None)], [], False),
            ("resume_then_more", "saved-c", [(True, "c1"), (False, None)], ["c1"], True),
            ("resume_final_page", "saved-c", [(False, None)], [], True),
        ]
    )
    @patch("posthog.temporal.data_imports.sources.notion.notion._execute_request")
    def test_pagination_state(
        self,
        _name: str,
        saved_cursor: str | None,
        page_specs: list[PageSpec],
        expected_save_cursors: list[str],
        first_request_has_cursor: bool,
        mock_execute: MagicMock,
    ) -> None:
        snapshots: list[dict[str, Any]] = []

        def side_effect(_sess: object, _method: object, _url: object, body: dict[str, Any]) -> dict[str, Any]:
            snapshots.append(copy.deepcopy(body))
            has_more, next_cursor = page_specs[len(snapshots) - 1]
            return {
                "results": [{"id": f"r{len(snapshots) - 1}"}],
                "has_more": has_more,
                "next_cursor": next_cursor,
            }

        mock_execute.side_effect = side_effect

        sess = MagicMock()
        saved = NotionResumeConfig(cursor=saved_cursor) if saved_cursor is not None else None
        manager = _make_resumable_manager(saved=saved)
        logger = MagicMock()

        list(
            _paginate(
                sess=sess,
                method="POST",
                url=f"{NOTION_API_URL}/search",
                body={"filter": {"property": "object", "value": "page"}},
                logger=logger,
                resumable_source_manager=manager,
            )
        )

        # Resume: first request carries the saved cursor; fresh: no start_cursor on first call.
        if first_request_has_cursor:
            assert snapshots[0]["start_cursor"] == saved_cursor
        else:
            assert "start_cursor" not in snapshots[0]

        # Each non-final page checkpoints the next page's cursor.
        assert manager.save_state.call_args_list == [((NotionResumeConfig(cursor=c),),) for c in expected_save_cursors]

        # The body filter is preserved across all paginated calls.
        for body in snapshots:
            assert body["filter"] == {"property": "object", "value": "page"}
            assert body["page_size"] == 100

    @parameterized.expand([("null_next_cursor", None), ("empty_next_cursor", "")])
    @patch("posthog.temporal.data_imports.sources.notion.notion._execute_request")
    def test_raises_when_has_more_but_cursor_missing(
        self,
        _name: str,
        bad_cursor: str | None,
        mock_execute: MagicMock,
    ) -> None:
        mock_execute.return_value = {
            "results": [{"id": "x"}],
            "has_more": True,
            "next_cursor": bad_cursor,
        }

        sess = MagicMock()
        manager = _make_resumable_manager()
        logger = MagicMock()

        with pytest.raises(Exception, match="next_cursor is empty"):
            list(
                _paginate(
                    sess=sess,
                    method="POST",
                    url=f"{NOTION_API_URL}/search",
                    body={},
                    logger=logger,
                    resumable_source_manager=manager,
                )
            )

        manager.save_state.assert_not_called()


class TestNotionSource:
    @patch("posthog.temporal.data_imports.sources.notion.notion._make_session")
    def test_pages_endpoint_filters_search_results_client_side_when_incremental(
        self, mock_make_session: MagicMock
    ) -> None:
        # `/search` does not support server-side time filters. Verify we drop rows whose
        # last_edited_time is at or before the cutoff.
        session = MagicMock()
        page_old = {"id": "old", "last_edited_time": "2026-01-01T00:00:00Z"}
        page_keep = {"id": "keep", "last_edited_time": "2026-03-01T00:00:00Z"}
        _capture_post_calls(session, [_make_response([page_old, page_keep], False, None)])
        mock_make_session.return_value = session

        manager = _make_resumable_manager()
        logger = MagicMock()

        response = notion_source(
            access_token="tok",
            endpoint_name="pages",
            logger=logger,
            resumable_source_manager=manager,
            should_use_incremental_field=True,
            db_incremental_field_last_value="2026-02-01T00:00:00Z",
        )

        pages = list(cast(Iterable[Any], response.items()))
        assert pages == [[page_keep]]

    @patch("posthog.temporal.data_imports.sources.notion.notion._make_session")
    def test_database_rows_endpoint_uses_server_side_filter_and_flattens(self, mock_make_session: MagicMock) -> None:
        # `/databases/{id}/query` supports a server-side last_edited_time filter — verify it's
        # set on the request body, and that the rows come back flattened.
        session = MagicMock()
        row = {
            "id": "row-1",
            "object": "page",
            "created_time": "2026-01-15T00:00:00Z",
            "last_edited_time": "2026-04-01T00:00:00Z",
            "url": "https://www.notion.so/row-1",
            "archived": False,
            "parent": {"type": "database_id", "database_id": "abc"},
            "properties": {
                "Name": {
                    "type": "title",
                    "title": [{"plain_text": "Hello "}, {"plain_text": "world"}],
                },
                "Score": {"type": "number", "number": 42},
            },
        }
        snapshots = _capture_post_calls(session, [_make_response([row], False, None)])
        mock_make_session.return_value = session

        manager = _make_resumable_manager()
        logger = MagicMock()

        schema_name = database_rows_schema_name("dbid-1234")
        response = notion_source(
            access_token="tok",
            endpoint_name=schema_name,
            logger=logger,
            resumable_source_manager=manager,
            should_use_incremental_field=True,
            db_incremental_field_last_value="2026-02-01T00:00:00Z",
        )

        batches = list(cast(Iterable[Any], response.items()))
        assert len(batches) == 1
        flat = batches[0][0]
        assert flat["id"] == "row-1"
        assert flat["Name"] == "Hello world"
        assert flat["Score"] == 42
        assert flat["_raw_properties"] == row["properties"]

        body = snapshots[0]
        assert body["filter"] == {
            "timestamp": "last_edited_time",
            "last_edited_time": {"after": "2026-02-01T00:00:00Z"},
        }
        assert body["page_size"] == 100

    def test_unknown_endpoint_raises(self) -> None:
        manager = _make_resumable_manager()
        logger = MagicMock()
        with pytest.raises(ValueError, match="Unknown Notion endpoint"):
            notion_source(
                access_token="tok",
                endpoint_name="not_a_real_endpoint",
                logger=logger,
                resumable_source_manager=manager,
            )

    def test_source_response_metadata_for_pages(self) -> None:
        manager = _make_resumable_manager()
        logger = MagicMock()
        response = notion_source(
            access_token="tok",
            endpoint_name="pages",
            logger=logger,
            resumable_source_manager=manager,
        )
        assert response.name == "pages"
        assert response.primary_keys == ["id"]
        assert response.partition_keys == ["created_time"]


class TestFlattenProperty:
    @parameterized.expand(
        [
            (
                "title_concatenates_spans",
                {"type": "title", "title": [{"plain_text": "Hello "}, {"plain_text": "world"}]},
                "Hello world",
            ),
            ("number_passthrough", {"type": "number", "number": 17}, 17),
            ("select_returns_name", {"type": "select", "select": {"name": "In progress"}}, "In progress"),
            (
                "multi_select_returns_names",
                {"type": "multi_select", "multi_select": [{"name": "a"}, {"name": "b"}]},
                ["a", "b"],
            ),
            ("date_returns_start", {"type": "date", "date": {"start": "2026-04-01"}}, "2026-04-01"),
            ("checkbox_passthrough", {"type": "checkbox", "checkbox": True}, True),
            ("url_passthrough", {"type": "url", "url": "https://example.com"}, "https://example.com"),
            ("null_value_returns_none", {"type": "select", "select": None}, None),
            ("unknown_type_returns_none", {"type": "weird_new_type", "weird_new_type": "x"}, None),
        ]
    )
    def test_flatten(self, _name: str, prop: dict[str, Any], expected: Any) -> None:
        assert _flatten_property(prop) == expected


class TestFlattenDatabaseRow:
    def test_preserves_top_level_fields_and_raw_properties(self) -> None:
        row = {
            "id": "abc",
            "object": "page",
            "created_time": "2026-01-01T00:00:00Z",
            "last_edited_time": "2026-02-01T00:00:00Z",
            "archived": False,
            "url": "https://www.notion.so/abc",
            "parent": {"type": "database_id"},
            "properties": {"Name": {"type": "title", "title": [{"plain_text": "x"}]}},
        }
        flat = _flatten_database_row(row)
        assert flat["id"] == "abc"
        assert flat["Name"] == "x"
        assert flat["_raw_properties"] == row["properties"]
        assert flat["url"] == "https://www.notion.so/abc"


class TestValidateCredentials:
    @patch("posthog.temporal.data_imports.sources.notion.notion._make_session")
    def test_returns_true_on_200(self, mock_make_session: MagicMock) -> None:
        session = MagicMock()
        ok = MagicMock()
        ok.status_code = 200
        session.get.return_value = ok
        mock_make_session.return_value = session

        valid, error = validate_credentials("tok")
        assert valid is True
        assert error is None

    @patch("posthog.temporal.data_imports.sources.notion.notion._make_session")
    def test_returns_false_on_401(self, mock_make_session: MagicMock) -> None:
        session = MagicMock()
        unauthorized = MagicMock()
        unauthorized.status_code = 401
        unauthorized.reason = "Unauthorized"
        unauthorized.json.return_value = {"message": "API token is invalid"}
        session.get.return_value = unauthorized
        mock_make_session.return_value = session

        valid, error = validate_credentials("tok")
        assert valid is False
        assert error is not None
        assert "401" in error
        assert "API token is invalid" in error
