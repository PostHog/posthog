import json
import base64
from collections.abc import Iterable
from datetime import datetime
from typing import cast

import pytest
from unittest import mock

from posthog.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from posthog.temporal.data_imports.sources.firebase import firestore as firestore_module
from posthog.temporal.data_imports.sources.firebase.firestore import (
    FirebaseResumeConfig,
    _build_run_query_body,
    _document_id,
    _infer_columns_from_documents,
    _initial_incremental_value,
    _normalize_document,
    _normalize_value,
    _parse_timestamp,
    firestore_source,
)


class TestNormalizeValue:
    @pytest.mark.parametrize(
        ("firestore_value", "expected"),
        [
            ({"stringValue": "hello"}, "hello"),
            ({"booleanValue": True}, True),
            ({"booleanValue": False}, False),
            ({"integerValue": "42"}, 42),
            ({"doubleValue": 3.14}, 3.14),
            ({"nullValue": None}, None),
            (
                {"referenceValue": "projects/p/databases/(default)/documents/users/abc"},
                "projects/p/databases/(default)/documents/users/abc",
            ),
        ],
    )
    def test_scalar_values(self, firestore_value, expected):
        assert _normalize_value(firestore_value) == expected

    def test_bytes_value_is_decoded_from_base64(self):
        encoded = base64.b64encode(b"hello bytes").decode()
        assert _normalize_value({"bytesValue": encoded}) == "hello bytes"

    def test_geopoint_serializes_to_json(self):
        result = _normalize_value({"geoPointValue": {"latitude": 12.5, "longitude": -1.0}})

        assert json.loads(result) == {"latitude": 12.5, "longitude": -1.0}

    def test_array_value_recursively_normalizes(self):
        firestore_value = {
            "arrayValue": {
                "values": [
                    {"stringValue": "a"},
                    {"integerValue": "1"},
                    {"booleanValue": True},
                ]
            }
        }

        result = _normalize_value(firestore_value)

        assert json.loads(result) == ["a", 1, True]

    def test_map_value_recursively_normalizes(self):
        firestore_value = {
            "mapValue": {
                "fields": {
                    "name": {"stringValue": "Alice"},
                    "age": {"integerValue": "30"},
                    "tags": {"arrayValue": {"values": [{"stringValue": "x"}]}},
                }
            }
        }

        result = _normalize_value(firestore_value)
        parsed = json.loads(result)

        assert parsed == {"name": "Alice", "age": 30, "tags": '["x"]'}

    def test_timestamp_parsing(self):
        result = _normalize_value({"timestampValue": "2025-01-02T03:04:05.123456Z"})

        assert isinstance(result, datetime)
        assert result.year == 2025
        assert result.month == 1
        assert result.day == 2

    def test_unknown_type_returns_none(self):
        assert _normalize_value({"unknownValue": "x"}) is None

    def test_empty_dict_returns_none(self):
        assert _normalize_value({}) is None


class TestParseTimestamp:
    def test_strips_trailing_z(self):
        assert _parse_timestamp("2025-01-02T03:04:05Z") == datetime(2025, 1, 2, 3, 4, 5)

    def test_truncates_subsecond_precision_beyond_microseconds(self):
        # Firestore can return up to 9 fractional-second digits.
        parsed = _parse_timestamp("2025-01-02T03:04:05.123456789Z")
        assert parsed is not None
        assert parsed.microsecond == 123456

    def test_invalid_returns_none(self):
        assert _parse_timestamp("not-a-date") is None

    def test_empty_returns_none(self):
        assert _parse_timestamp("") is None


class TestDocumentId:
    def test_extracts_last_path_segment(self):
        document = {"name": "projects/p/databases/(default)/documents/users/abc-123"}

        assert _document_id(document) == "abc-123"

    def test_returns_empty_when_name_missing(self):
        assert _document_id({}) == ""


class TestNormalizeDocument:
    def test_emits_synthetic_columns(self):
        document = {
            "name": "projects/p/databases/(default)/documents/users/u1",
            "fields": {"name": {"stringValue": "Alice"}, "age": {"integerValue": "30"}},
            "createTime": "2025-01-01T00:00:00Z",
            "updateTime": "2025-01-02T00:00:00Z",
        }

        row = _normalize_document(document)

        assert row["_id"] == "u1"
        assert row["_create_time"] == datetime(2025, 1, 1)
        assert row["_update_time"] == datetime(2025, 1, 2)
        assert row["name"] == "Alice"
        assert row["age"] == 30

    def test_synthetic_columns_take_precedence_over_user_fields(self):
        # If a doc has a user-defined `_id` field, the synthetic _id (doc path) wins.
        document = {
            "name": "projects/p/databases/(default)/documents/users/u1",
            "fields": {"_id": {"stringValue": "hijacked"}},
            "createTime": "2025-01-01T00:00:00Z",
            "updateTime": "2025-01-02T00:00:00Z",
        }

        row = _normalize_document(document)

        assert row["_id"] == "u1"


class TestInferColumns:
    def test_infers_types_and_nullability(self):
        documents = [
            {"fields": {"name": {"stringValue": "a"}, "age": {"integerValue": "1"}}},
            {"fields": {"name": {"stringValue": "b"}}},  # no age in second doc
            {"fields": {"name": {"stringValue": "c"}, "age": {"integerValue": "3"}}},
        ]

        columns = _infer_columns_from_documents(documents)

        cols_by_name = {c[0]: c for c in columns}
        assert cols_by_name["name"] == ("name", "string", False)
        # Age is missing in the second doc — must be marked nullable.
        assert cols_by_name["age"][0] == "age"
        assert cols_by_name["age"][1] == "integer"
        assert cols_by_name["age"][2] is True

    def test_mixed_types_fall_back_to_string(self):
        documents = [
            {"fields": {"value": {"stringValue": "a"}}},
            {"fields": {"value": {"integerValue": "1"}}},
        ]

        columns = _infer_columns_from_documents(documents)
        assert columns == [("value", "string", False)]

    def test_empty_sample_returns_no_columns(self):
        assert _infer_columns_from_documents([]) == []


class TestRunQueryBody:
    def test_filters_orders_and_limits(self):
        body = _build_run_query_body(collection_id="users", after_update_time_iso="2025-01-01T00:00:00Z")

        query = body["structuredQuery"]
        assert query["from"] == [{"collectionId": "users"}]
        assert query["where"]["fieldFilter"]["op"] == "GREATER_THAN"
        assert query["where"]["fieldFilter"]["field"] == {"fieldPath": "__update_time__"}
        assert query["where"]["fieldFilter"]["value"] == {"timestampValue": "2025-01-01T00:00:00Z"}
        assert query["orderBy"][0]["direction"] == "ASCENDING"
        assert query["limit"] > 0


class TestInitialIncrementalValue:
    def test_none_yields_epoch(self):
        assert _initial_incremental_value(None) == "1970-01-01T00:00:00Z"

    def test_string_passes_through(self):
        assert _initial_incremental_value("2025-01-01T00:00:00Z") == "2025-01-01T00:00:00Z"

    def test_naive_datetime_appends_z(self):
        assert _initial_incremental_value(datetime(2025, 1, 1, 0, 0, 0)) == "2025-01-01T00:00:00Z"


def _key_info() -> dict:
    return {
        "project_id": "p",
        "private_key": "k",
        "private_key_id": "kid",
        "client_email": "svc@p.iam.gserviceaccount.com",
        "token_uri": "https://oauth2.googleapis.com/token",
    }


class TestFirestoreSourcePagination:
    def _patch_auth_and_session(self, session_mock):
        return [
            mock.patch.object(firestore_module, "_get_access_token", return_value="token"),
            mock.patch.object(firestore_module, "_build_session", return_value=session_mock),
        ]

    def _run(
        self,
        responses,
        should_use_incremental_field=False,
        db_incremental_field_last_value=None,
        resumable_can_resume=False,
        resumable_state=None,
    ):
        session = mock.MagicMock()
        get_response = mock.MagicMock()
        get_response.raise_for_status.return_value = None
        get_response.json.side_effect = responses
        session.get.return_value = get_response
        session.post.return_value = get_response

        manager = mock.MagicMock(spec=ResumableSourceManager)
        manager.can_resume.return_value = resumable_can_resume
        manager.load_state.return_value = resumable_state
        manager.save_state = mock.MagicMock()

        with self._patch_auth_and_session(session)[0]:
            with self._patch_auth_and_session(session)[1]:
                response = firestore_source(
                    key_info=_key_info(),
                    database_id="(default)",
                    collection_id="users",
                    should_use_incremental_field=should_use_incremental_field,
                    incremental_field="_update_time" if should_use_incremental_field else None,
                    db_incremental_field_last_value=db_incremental_field_last_value,
                    logger=mock.MagicMock(),
                    resumable_source_manager=manager,
                )
                rows = list(cast(Iterable[dict], response.items()))

        return rows, session, manager

    def test_full_refresh_walks_pagination_and_terminates(self):
        responses = [
            {
                "documents": [
                    {
                        "name": "projects/p/databases/(default)/documents/users/u1",
                        "fields": {"name": {"stringValue": "Alice"}},
                        "createTime": "2025-01-01T00:00:00Z",
                        "updateTime": "2025-01-01T00:00:00Z",
                    }
                ],
                "nextPageToken": "page-2",
            },
            {
                "documents": [
                    {
                        "name": "projects/p/databases/(default)/documents/users/u2",
                        "fields": {"name": {"stringValue": "Bob"}},
                        "createTime": "2025-01-02T00:00:00Z",
                        "updateTime": "2025-01-02T00:00:00Z",
                    }
                ],
                # No nextPageToken — termination.
            },
        ]

        rows, session, manager = self._run(responses)

        assert [row["_id"] for row in rows] == ["u1", "u2"]
        # Two GET requests for two pages.
        assert session.get.call_count == 2
        # State saved after the first batch (which had a nextPageToken). Not after the
        # second (terminating) page.
        manager.save_state.assert_called_once()
        saved = manager.save_state.call_args.args[0]
        assert isinstance(saved, FirebaseResumeConfig)
        assert saved.mode == "list"
        assert saved.cursor == "page-2"

    def test_full_refresh_resume_starts_from_saved_token(self):
        responses = [
            {
                "documents": [
                    {
                        "name": "projects/p/databases/(default)/documents/users/u3",
                        "fields": {"name": {"stringValue": "Carol"}},
                        "createTime": "2025-01-03T00:00:00Z",
                        "updateTime": "2025-01-03T00:00:00Z",
                    }
                ],
            },
        ]

        rows, session, _ = self._run(
            responses,
            resumable_can_resume=True,
            resumable_state=FirebaseResumeConfig(mode="list", cursor="resume-token"),
        )

        assert [row["_id"] for row in rows] == ["u3"]
        first_call_kwargs = session.get.call_args_list[0]
        assert first_call_kwargs.kwargs["params"]["pageToken"] == "resume-token"

    def test_incremental_uses_run_query_and_advances_cursor(self):
        responses = [
            [
                {
                    "document": {
                        "name": "projects/p/databases/(default)/documents/users/u1",
                        "fields": {"name": {"stringValue": "Alice"}},
                        "createTime": "2025-01-01T00:00:00Z",
                        "updateTime": "2025-01-02T00:00:00Z",
                    }
                },
                {
                    "document": {
                        "name": "projects/p/databases/(default)/documents/users/u2",
                        "fields": {"name": {"stringValue": "Bob"}},
                        "createTime": "2025-01-01T00:00:00Z",
                        "updateTime": "2025-01-03T00:00:00Z",
                    }
                },
            ],
            # Empty response — terminate.
            [],
        ]

        rows, session, manager = self._run(
            responses,
            should_use_incremental_field=True,
            db_incremental_field_last_value="2025-01-01T00:00:00Z",
        )

        assert [row["_id"] for row in rows] == ["u1", "u2"]
        # First runQuery uses the initial cursor; second uses the updated one.
        first_call_body = session.post.call_args_list[0].kwargs["json"]
        assert first_call_body["structuredQuery"]["where"]["fieldFilter"]["value"] == {
            "timestampValue": "2025-01-01T00:00:00Z"
        }
        # State saved after the batch yielded u1 and u2 — cursor moves to the latest updateTime.
        saved = manager.save_state.call_args.args[0]
        assert saved.mode == "query"
        assert saved.cursor == "2025-01-03T00:00:00Z"

    def test_incremental_resume_starts_from_saved_cursor(self):
        _, session, _ = self._run(
            [[]],  # empty response — terminate
            should_use_incremental_field=True,
            resumable_can_resume=True,
            resumable_state=FirebaseResumeConfig(mode="query", cursor="2025-06-01T00:00:00Z"),
        )

        body = session.post.call_args.kwargs["json"]
        assert body["structuredQuery"]["where"]["fieldFilter"]["value"] == {"timestampValue": "2025-06-01T00:00:00Z"}
