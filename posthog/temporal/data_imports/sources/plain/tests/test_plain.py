from datetime import UTC, datetime

import pytest
from unittest import mock

import requests

from posthog.temporal.data_imports.sources.plain.plain import (
    PlainRetryableError,
    _datetime_to_plain_iso8601,
    _fetch_thread_timeline_entries,
    _fetch_timeline_entries,
    _flatten_datetime,
    _flatten_node,
    _flatten_timeline_entry,
    _parse_plain_datetime,
    plain_source,
    validate_credentials,
)


class TestFlattenDatetime:
    def test_unwraps_iso8601(self):
        result = _flatten_datetime({"createdAt": {"iso8601": "2024-01-15T10:30:00Z"}})
        assert result == {"createdAt": "2024-01-15T10:30:00Z"}

    def test_preserves_non_iso_dicts(self):
        result = _flatten_datetime({"email": {"email": "a@b.com", "isVerified": True}})
        assert result == {"email": {"email": "a@b.com", "isVerified": True}}

    def test_flattens_lists_of_dicts(self):
        result = _flatten_datetime({"items": [{"createdAt": {"iso8601": "2024-01-01T00:00:00Z"}}]})
        assert result == {"items": [{"createdAt": "2024-01-01T00:00:00Z"}]}

    def test_preserves_scalar_values(self):
        result = _flatten_datetime({"id": "abc", "count": 42, "enabled": True})
        assert result == {"id": "abc", "count": 42, "enabled": True}


class TestFlattenNode:
    def test_flattens_customer_node(self):
        node = {
            "id": "c_1",
            "fullName": "Alice",
            "email": {"email": "alice@example.com", "isVerified": True},
            "createdAt": {"iso8601": "2024-01-01T00:00:00Z"},
            "updatedAt": {"iso8601": "2024-02-01T00:00:00Z"},
            "assignedToUser": {"id": "u_1", "fullName": "Bob", "email": "bob@example.com"},
            "createdBy": {"actorType": "user", "userId": "u_2"},
            "company": {"id": "co_1", "name": "Acme"},
        }
        result = _flatten_node(node)

        assert result["id"] == "c_1"
        assert result["email"] == "alice@example.com"
        assert result["emailIsVerified"] is True
        assert result["createdAt"] == "2024-01-01T00:00:00Z"
        assert result["updatedAt"] == "2024-02-01T00:00:00Z"
        assert result["assignedToUserId"] == "u_1"
        assert result["assignedToUserName"] == "Bob"
        assert result["createdByType"] == "user"
        assert result["createdById"] == "u_2"
        assert result["companyId"] == "co_1"
        assert result["companyName"] == "Acme"

    def test_flattens_thread_with_labels_and_message_info(self):
        node = {
            "id": "t_1",
            "customer": {"id": "c_1", "fullName": "Alice", "email": {"email": "alice@example.com"}},
            "labels": [
                {"id": "l_1", "labelType": {"name": "bug"}},
                {"id": "l_2", "labelType": {"name": "urgent"}},
            ],
            "firstInboundMessageInfo": {"timestamp": {"iso8601": "2024-01-01T01:00:00Z"}},
            "lastOutboundMessageInfo": None,
        }
        result = _flatten_node(node)

        assert result["customerId"] == "c_1"
        assert result["customerEmail"] == "alice@example.com"
        assert result["labelIds"] == ["l_1", "l_2"]
        assert result["labelNames"] == ["bug", "urgent"]
        assert result["firstInboundMessageAt"] == "2024-01-01T01:00:00Z"
        assert result["lastOutboundMessageAt"] is None

    def test_preserves_null_assigned_user(self):
        node = {"id": "t_1", "assignedToUser": None}
        result = _flatten_node(node)

        assert result["assignedToUser"] is None
        assert "assignedToUserId" not in result
        assert "assignedToUserName" not in result


class TestFlattenTimelineEntry:
    def test_chat_entry(self):
        entry = {
            "id": "te_1",
            "timestamp": {"iso8601": "2024-01-01T00:00:00Z"},
            "actor": {"actorType": "customer", "customerId": "c_1"},
            "entry": {"__typename": "ChatEntry", "chatId": "chat_1", "text": "hello"},
        }
        result = _flatten_timeline_entry(entry, thread_id="t_1")

        assert result["threadId"] == "t_1"
        assert result["createdAt"] == "2024-01-01T00:00:00Z"
        assert result["actorType"] == "customer"
        assert result["actorId"] == "c_1"
        assert result["entryType"] == "ChatEntry"
        assert result["chatId"] == "chat_1"
        assert result["text"] == "hello"

    def test_email_entry(self):
        entry = {
            "id": "te_2",
            "timestamp": {"iso8601": "2024-01-01T00:00:00Z"},
            "actor": {"actorType": "user", "userId": "u_1"},
            "entry": {
                "__typename": "EmailEntry",
                "emailId": "email_1",
                "subject": "hi",
                "textContent": "body",
                "to": {"email": "to@example.com", "name": "To"},
                "from": {"email": "from@example.com", "name": "From"},
            },
        }
        result = _flatten_timeline_entry(entry, thread_id="t_1")

        assert result["entryType"] == "EmailEntry"
        assert result["emailId"] == "email_1"
        assert result["subject"] == "hi"
        assert result["text"] == "body"
        assert result["toEmail"] == "to@example.com"
        assert result["fromEmail"] == "from@example.com"

    def test_note_entry(self):
        entry = {
            "id": "te_3",
            "timestamp": {"iso8601": "2024-01-01T00:00:00Z"},
            "actor": {"actorType": "user", "userId": "u_1"},
            "entry": {"__typename": "NoteEntry", "noteId": "note_1", "text": "internal"},
        }
        result = _flatten_timeline_entry(entry, thread_id="t_1")

        assert result["entryType"] == "NoteEntry"
        assert result["noteId"] == "note_1"
        assert result["text"] == "internal"


class TestPlainSourcePipeline:
    def test_unknown_endpoint_raises(self):
        with pytest.raises(ValueError, match="Unknown Plain endpoint: made_up"):
            plain_source(api_key="k", endpoint_name="made_up", logger=mock.MagicMock())

    def test_returns_source_response_with_partition_metadata(self):
        response = plain_source(api_key="k", endpoint_name="customers", logger=mock.MagicMock())

        assert response.name == "customers"
        assert response.primary_keys == ["id"]
        assert response.partition_mode == "datetime"
        assert response.partition_format == "week"
        assert response.partition_keys == ["createdAt"]


class TestValidateCredentials:
    @mock.patch("posthog.temporal.data_imports.sources.plain.plain.make_tracked_session")
    def test_success(self, mock_post):
        mock_post.return_value.post.return_value = mock.MagicMock(
            status_code=200,
            ok=True,
            json=lambda: {"data": {"myWorkspace": {"id": "w_1", "name": "Acme"}}},
        )

        is_valid, error = validate_credentials("valid_key")

        assert is_valid is True
        assert error is None

    @mock.patch("posthog.temporal.data_imports.sources.plain.plain.make_tracked_session")
    def test_returns_error_from_graphql_errors(self, mock_post):
        mock_post.return_value.post.return_value = mock.MagicMock(
            status_code=200,
            ok=True,
            json=lambda: {"errors": [{"message": "Unauthorized"}]},
        )

        is_valid, error = validate_credentials("bad_key")

        assert is_valid is False
        assert error is not None
        assert "Unauthorized" in error

    @mock.patch("posthog.temporal.data_imports.sources.plain.plain.make_tracked_session")
    def test_handles_request_exception(self, mock_post):
        mock_post.return_value.post.side_effect = requests.ConnectionError("down")

        is_valid, error = validate_credentials("any_key")

        assert is_valid is False
        assert error == "down"


class TestPlainRetryableError:
    def test_is_exception(self):
        assert issubclass(PlainRetryableError, Exception)


class TestDatetimeHelpers:
    def test_datetime_to_plain_iso8601_uses_z_suffix(self):
        assert _datetime_to_plain_iso8601(datetime(2024, 1, 15, 10, 30, 0, tzinfo=UTC)) == "2024-01-15T10:30:00Z"

    def test_datetime_to_plain_iso8601_assumes_utc_for_naive(self):
        assert _datetime_to_plain_iso8601(datetime(2024, 1, 15, 10, 30, 0)) == "2024-01-15T10:30:00Z"

    def test_parse_plain_datetime_from_string(self):
        assert _parse_plain_datetime("2024-01-15T10:30:00Z") == datetime(2024, 1, 15, 10, 30, 0, tzinfo=UTC)

    def test_parse_plain_datetime_passthrough_datetime(self):
        dt = datetime(2024, 1, 15, 10, 30, 0, tzinfo=UTC)
        assert _parse_plain_datetime(dt) is dt

    def test_parse_plain_datetime_none(self):
        assert _parse_plain_datetime(None) is None


class TestTimelineEntryIncrementalFilter:
    """Verify incremental filtering compares datetimes, not ISO-8601 strings."""

    def _make_execute(self, pages):
        calls = iter(pages)

        def execute(_query, _variables):
            return next(calls)

        return execute

    def test_filters_older_entries_by_datetime(self):
        execute = self._make_execute(
            [
                {
                    "data": {
                        "thread": {
                            "timelineEntries": {
                                "edges": [
                                    {
                                        "node": {
                                            "id": "te_old",
                                            "timestamp": {"iso8601": "2024-01-01T00:00:00Z"},
                                            "actor": {"actorType": "customer", "customerId": "c_1"},
                                            "entry": {"__typename": "ChatEntry", "chatId": "c", "text": "old"},
                                        }
                                    },
                                    {
                                        "node": {
                                            "id": "te_new",
                                            "timestamp": {"iso8601": "2024-02-01T00:00:00Z"},
                                            "actor": {"actorType": "customer", "customerId": "c_1"},
                                            "entry": {"__typename": "ChatEntry", "chatId": "c", "text": "new"},
                                        }
                                    },
                                ],
                                "pageInfo": {"hasNextPage": False, "endCursor": None},
                            }
                        }
                    }
                }
            ]
        )

        pages = list(
            _fetch_thread_timeline_entries(
                execute,
                thread_id="t_1",
                logger=mock.MagicMock(),
                created_at_gte=datetime(2024, 1, 15, tzinfo=UTC),
            )
        )

        assert len(pages) == 1
        assert [e["id"] for e in pages[0]] == ["te_new"]

    def test_includes_entries_with_null_created_at(self):
        execute = self._make_execute(
            [
                {
                    "data": {
                        "thread": {
                            "timelineEntries": {
                                "edges": [
                                    {
                                        "node": {
                                            "id": "te_null",
                                            # No timestamp field at all -> createdAt becomes absent
                                            "actor": {"actorType": "customer", "customerId": "c_1"},
                                            "entry": {"__typename": "ChatEntry", "chatId": "c", "text": "x"},
                                        }
                                    }
                                ],
                                "pageInfo": {"hasNextPage": False, "endCursor": None},
                            }
                        }
                    }
                }
            ]
        )

        pages = list(
            _fetch_thread_timeline_entries(
                execute,
                thread_id="t_1",
                logger=mock.MagicMock(),
                created_at_gte=datetime(2024, 1, 15, tzinfo=UTC),
            )
        )

        assert len(pages) == 1
        assert [e["id"] for e in pages[0]] == ["te_null"]


class TestFetchTimelineEntriesStreaming:
    def test_sends_updatedat_filter_when_incremental(self):
        recorded = []

        def execute(query, variables):
            recorded.append((query, dict(variables)))
            if "ThreadIdsList" in query or "threads" in query:
                return {"data": {"threads": {"edges": [], "pageInfo": {"hasNextPage": False, "endCursor": None}}}}
            raise AssertionError("unexpected query")

        list(
            _fetch_timeline_entries(
                execute,
                logger=mock.MagicMock(),
                created_at_gte=datetime(2024, 1, 15, 10, 30, 0, tzinfo=UTC),
            )
        )

        assert recorded, "expected threads query to be issued"
        _, variables = recorded[0]
        assert variables["filter"] == {"updatedAt": {"gte": "2024-01-15T10:30:00Z"}}

    def test_streams_thread_pages_without_buffering_all_ids(self):
        executed_queries: list[str] = []

        def execute(query, _variables):
            executed_queries.append(query)
            # First threads page: returns one thread id then no next page.
            if "ThreadIdsList" in query:
                return {
                    "data": {
                        "threads": {
                            "edges": [{"node": {"id": "t_1"}}],
                            "pageInfo": {"hasNextPage": False, "endCursor": None},
                        }
                    }
                }
            # Timeline entries for t_1.
            return {
                "data": {
                    "thread": {
                        "timelineEntries": {
                            "edges": [
                                {
                                    "node": {
                                        "id": "te_1",
                                        "timestamp": {"iso8601": "2024-02-01T00:00:00Z"},
                                        "actor": {"actorType": "customer", "customerId": "c_1"},
                                        "entry": {"__typename": "ChatEntry", "chatId": "c", "text": "x"},
                                    }
                                }
                            ],
                            "pageInfo": {"hasNextPage": False, "endCursor": None},
                        }
                    }
                }
            }

        pages = list(_fetch_timeline_entries(execute, logger=mock.MagicMock()))

        assert len(pages) == 1
        assert [e["id"] for e in pages[0]] == ["te_1"]
        # Threads query first, then TIMELINE_ENTRIES_QUERY after we've seen the first edge — no second threads page expected.
        assert "ThreadIdsList" in executed_queries[0]
