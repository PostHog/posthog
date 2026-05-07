import json
import base64
import dataclasses
from collections.abc import Iterator
from datetime import datetime
from typing import Any, Optional

import requests
from google.auth.transport.requests import Request as GoogleRequest
from google.oauth2 import service_account
from structlog.types import FilteringBoundLogger

from posthog.temporal.data_imports.naming_convention import NamingConvention
from posthog.temporal.data_imports.pipelines.pipeline.typings import SourceResponse
from posthog.temporal.data_imports.sources.common.http import make_tracked_session
from posthog.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from posthog.temporal.data_imports.sources.firebase.settings import (
    DEFAULT_DATABASE_ID,
    FIRESTORE_BASE_URL,
    FIRESTORE_SCOPE,
    LIST_PAGE_SIZE,
    REQUEST_TIMEOUT_SECONDS,
    SCHEMA_INFERENCE_SAMPLE_SIZE,
)

from products.data_warehouse.backend.types import IncrementalField, IncrementalFieldType


@dataclasses.dataclass
class FirebaseResumeConfig:
    """Cursor for resuming a Firestore sync.

    `mode` distinguishes a full-refresh `documents.list` page token from an
    incremental `runQuery` cursor (the last seen `updateTime` ISO string).
    """

    mode: str
    cursor: str


def validate_service_account_credentials(key_info: dict[str, str]) -> None:
    """Exchange a service-account JSON for an OAuth2 access token to confirm the
    key is valid. Raises with a friendly message on failure."""
    if not key_info.get("project_id"):
        raise ValueError("Service account key must contain a project_id")

    try:
        credentials = service_account.Credentials.from_service_account_info(key_info, scopes=[FIRESTORE_SCOPE])
        credentials.refresh(GoogleRequest())
    except Exception as e:
        raise ValueError(f"Failed to authenticate with provided Firebase service account key: {e}") from e


def _get_access_token(key_info: dict[str, str]) -> str:
    credentials = service_account.Credentials.from_service_account_info(key_info, scopes=[FIRESTORE_SCOPE])
    credentials.refresh(GoogleRequest())
    return credentials.token


def _build_session(access_token: str) -> requests.Session:
    return make_tracked_session(headers={"Authorization": f"Bearer {access_token}"})


def _project_id(key_info: dict[str, str]) -> str:
    project_id = key_info.get("project_id")
    if not project_id:
        raise ValueError("Service account key must contain a project_id")
    return project_id


def _documents_path(project_id: str, database_id: str) -> str:
    return f"{FIRESTORE_BASE_URL}/projects/{project_id}/databases/{database_id}/documents"


def list_collection_ids(
    key_info: dict[str, str],
    database_id: str = DEFAULT_DATABASE_ID,
) -> list[str]:
    """Enumerate top-level collections via Firestore's `:listCollectionIds` RPC.

    The endpoint paginates with `nextPageToken`; we walk every page so partial
    listings don't masquerade as the full collection set."""
    project_id = _project_id(key_info)
    access_token = _get_access_token(key_info)
    session = _build_session(access_token)

    url = f"{_documents_path(project_id, database_id)}:listCollectionIds"
    collection_ids: list[str] = []
    page_token: str | None = None
    try:
        while True:
            body: dict[str, Any] = {"pageSize": 100}
            if page_token:
                body["pageToken"] = page_token
            response = session.post(url, json=body, timeout=REQUEST_TIMEOUT_SECONDS)
            response.raise_for_status()
            payload = response.json()
            collection_ids.extend(payload.get("collectionIds", []))
            page_token = payload.get("nextPageToken")
            if not page_token:
                break
    finally:
        session.close()

    return collection_ids


def get_collection_schemas(
    key_info: dict[str, str],
    database_id: str = DEFAULT_DATABASE_ID,
    collection_names: list[str] | None = None,
) -> dict[str, dict[str, Any]]:
    """Return inferred schema info per collection.

    Each value is a dict with `columns` (list of (name, type, nullable))
    and `incremental_fields` (list of `IncrementalField`). Always includes
    the synthetic `_id`, `_create_time`, `_update_time` columns; Firestore
    doesn't expose real schemas, so further columns are inferred from a
    bounded sample of documents."""
    project_id = _project_id(key_info)
    access_token = _get_access_token(key_info)
    session = _build_session(access_token)

    try:
        all_collections = list_collection_ids(key_info, database_id=database_id)
        if collection_names is not None:
            wanted = set(collection_names)
            all_collections = [c for c in all_collections if c in wanted]

        result: dict[str, dict[str, Any]] = {}
        for collection_id in all_collections:
            sample = _sample_collection(
                session=session,
                project_id=project_id,
                database_id=database_id,
                collection_id=collection_id,
                limit=SCHEMA_INFERENCE_SAMPLE_SIZE,
            )
            inferred_columns = _infer_columns_from_documents(sample)
            base_columns: list[tuple[str, str, bool]] = [
                ("_id", "string", False),
                ("_create_time", "timestamp", False),
                ("_update_time", "timestamp", False),
            ]
            seen = {name for name, _, _ in base_columns}
            columns = base_columns + [c for c in inferred_columns if c[0] not in seen]
            result[collection_id] = {
                "columns": columns,
                "incremental_fields": _build_incremental_fields(),
            }
        return result
    finally:
        session.close()


def _build_incremental_fields() -> list[IncrementalField]:
    return [
        IncrementalField(
            label="_update_time",
            type=IncrementalFieldType.Timestamp,
            field="_update_time",
            field_type=IncrementalFieldType.Timestamp,
            is_indexed=True,
        )
    ]


def _sample_collection(
    session: requests.Session,
    project_id: str,
    database_id: str,
    collection_id: str,
    limit: int,
) -> list[dict[str, Any]]:
    url = f"{_documents_path(project_id, database_id)}/{collection_id}"
    params = {"pageSize": min(limit, LIST_PAGE_SIZE)}
    response = session.get(url, params=params, timeout=REQUEST_TIMEOUT_SECONDS)
    response.raise_for_status()
    payload = response.json()
    documents = payload.get("documents", []) or []
    return documents[:limit]


_FIRESTORE_TYPE_TO_INTERNAL = {
    "stringValue": "string",
    "booleanValue": "boolean",
    "integerValue": "integer",
    "doubleValue": "double",
    "timestampValue": "timestamp",
    "nullValue": "string",
    "bytesValue": "string",
    "referenceValue": "string",
    "geoPointValue": "string",
    "arrayValue": "string",
    "mapValue": "string",
}


def _infer_columns_from_documents(documents: list[dict[str, Any]]) -> list[tuple[str, str, bool]]:
    """Infer (column_name, type, nullable) tuples from a sample of docs.

    A field is `nullable=True` if any sampled doc lacks it or sets it to null.
    Type is taken from the first non-null occurrence; mixed types fall back to
    `string` since we serialize the raw value to JSON anyway."""
    field_observations: dict[str, set[str]] = {}
    field_seen_in: dict[str, int] = {}
    total_docs = len(documents)
    for doc in documents:
        fields = doc.get("fields") or {}
        for field_name, value in fields.items():
            field_seen_in[field_name] = field_seen_in.get(field_name, 0) + 1
            value_type = next(iter(value.keys()), "stringValue") if isinstance(value, dict) else "stringValue"
            field_observations.setdefault(field_name, set()).add(value_type)

    columns: list[tuple[str, str, bool]] = []
    for field_name, type_set in sorted(field_observations.items()):
        type_set_no_null = type_set - {"nullValue"}
        if len(type_set_no_null) == 1:
            firestore_type = next(iter(type_set_no_null))
        elif len(type_set_no_null) == 0:
            firestore_type = "nullValue"
        else:
            firestore_type = "stringValue"
        internal_type = _FIRESTORE_TYPE_TO_INTERNAL.get(firestore_type, "string")
        nullable = field_seen_in.get(field_name, 0) < total_docs or "nullValue" in type_set
        columns.append((field_name, internal_type, nullable))
    return columns


def _normalize_value(value: dict[str, Any]) -> Any:
    """Unwrap a single Firestore tagged-union value into a Python primitive.

    Maps and arrays serialize to JSON strings so they fit ClickHouse columnar
    storage cleanly. Scalars (string, bool, int, double, timestamp) round-trip
    as native types. Bytes decode from base64 to a UTF-8 string."""
    if not isinstance(value, dict) or not value:
        return None
    key = next(iter(value.keys()))
    raw = value[key]
    if key == "nullValue":
        return None
    if key == "stringValue":
        return raw
    if key == "booleanValue":
        return bool(raw)
    if key == "integerValue":
        return int(raw)
    if key == "doubleValue":
        return float(raw)
    if key == "timestampValue":
        return _parse_timestamp(raw)
    if key == "bytesValue":
        try:
            return base64.b64decode(raw).decode("utf-8", errors="replace")
        except Exception:
            return raw
    if key == "referenceValue":
        return raw
    if key == "geoPointValue":
        return json.dumps({"latitude": raw.get("latitude"), "longitude": raw.get("longitude")})
    if key == "arrayValue":
        items = raw.get("values", []) if isinstance(raw, dict) else []
        return json.dumps([_normalize_value(v) for v in items], default=str)
    if key == "mapValue":
        fields = raw.get("fields", {}) if isinstance(raw, dict) else {}
        return json.dumps({k: _normalize_value(v) for k, v in fields.items()}, default=str)
    return None


def _parse_timestamp(value: str) -> datetime | None:
    if not value:
        return None
    # Firestore returns RFC3339 with up to nanosecond precision and a trailing Z.
    # Python's fromisoformat requires microseconds, so trim if needed.
    cleaned = value.rstrip("Z")
    # Trim any sub-microsecond digits.
    if "." in cleaned:
        head, _, frac = cleaned.partition(".")
        # Keep up to 6 digits of fractional seconds.
        cleaned = f"{head}.{frac[:6]}" if frac else head
    try:
        return datetime.fromisoformat(cleaned)
    except ValueError:
        return None


def _document_id(document: dict[str, Any]) -> str:
    name = document.get("name", "") or ""
    return name.rsplit("/", 1)[-1] if name else ""


def _normalize_document(document: dict[str, Any]) -> dict[str, Any]:
    """Flatten a Firestore document into a row.

    Always emits `_id`, `_create_time`, `_update_time`, plus one column per
    top-level field. Nested maps/arrays land as JSON strings."""
    fields = document.get("fields", {}) or {}
    row: dict[str, Any] = {
        "_id": _document_id(document),
        "_create_time": _parse_timestamp(document.get("createTime", "")),
        "_update_time": _parse_timestamp(document.get("updateTime", "")),
    }
    for field_name, value in fields.items():
        # Don't clobber the synthetic columns if the doc itself has fields with
        # the same names — prefer the system metadata which is unambiguous.
        if field_name in row:
            continue
        row[field_name] = _normalize_value(value)
    return row


def _iter_full_refresh(
    session: requests.Session,
    project_id: str,
    database_id: str,
    collection_id: str,
    resume_token: Optional[str],
    resumable_source_manager: ResumableSourceManager[FirebaseResumeConfig],
    logger: FilteringBoundLogger,
) -> Iterator[dict[str, Any]]:
    url = f"{_documents_path(project_id, database_id)}/{collection_id}"
    page_token = resume_token
    while True:
        params: dict[str, Any] = {"pageSize": LIST_PAGE_SIZE}
        if page_token:
            params["pageToken"] = page_token
        response = session.get(url, params=params, timeout=REQUEST_TIMEOUT_SECONDS)
        response.raise_for_status()
        payload = response.json()
        documents = payload.get("documents", []) or []
        for doc in documents:
            yield _normalize_document(doc)
        next_page_token = payload.get("nextPageToken")
        if not next_page_token:
            break
        # Save state AFTER yielding the batch so a crash re-yields the last
        # batch (merge dedupes on _id) rather than skipping it.
        resumable_source_manager.save_state(FirebaseResumeConfig(mode="list", cursor=next_page_token))
        logger.debug(f"Saved resume token for collection={collection_id}, page_token={next_page_token}")
        page_token = next_page_token


def _iter_incremental(
    session: requests.Session,
    project_id: str,
    database_id: str,
    collection_id: str,
    last_update_time_iso: str,
    resumable_source_manager: ResumableSourceManager[FirebaseResumeConfig],
    logger: FilteringBoundLogger,
) -> Iterator[dict[str, Any]]:
    """Stream documents updated after `last_update_time_iso` via `:runQuery`.

    Firestore's `runQuery` returns one element per document inline rather than
    in pages, but it always orders deterministically — we cursor by re-issuing
    the same query with `startAt` set to the last-seen document. We bound each
    issue at LIST_PAGE_SIZE to keep memory predictable and to give the
    resumable manager a place to save state."""
    url = f"{_documents_path(project_id, database_id)}:runQuery"
    cursor_iso = last_update_time_iso
    while True:
        body = _build_run_query_body(collection_id=collection_id, after_update_time_iso=cursor_iso)
        response = session.post(url, json=body, timeout=REQUEST_TIMEOUT_SECONDS)
        response.raise_for_status()
        payload = response.json()
        # `runQuery` returns an array of {document?: {...}, readTime: ...}; the
        # first element may be empty when the result set is empty.
        documents = [item.get("document") for item in payload if item.get("document")]
        if not documents:
            break
        new_cursor: str | None = None
        for doc in documents:
            yield _normalize_document(doc)
            update_time = doc.get("updateTime")
            if update_time:
                new_cursor = update_time
        if not new_cursor or new_cursor == cursor_iso:
            break
        resumable_source_manager.save_state(FirebaseResumeConfig(mode="query", cursor=new_cursor))
        logger.debug(f"Saved incremental cursor for collection={collection_id}, update_time={new_cursor}")
        cursor_iso = new_cursor
        if len(documents) < LIST_PAGE_SIZE:
            break


def _build_run_query_body(collection_id: str, after_update_time_iso: str) -> dict[str, Any]:
    return {
        "structuredQuery": {
            "from": [{"collectionId": collection_id}],
            "where": {
                "fieldFilter": {
                    "field": {"fieldPath": "__update_time__"},
                    "op": "GREATER_THAN",
                    "value": {"timestampValue": after_update_time_iso},
                }
            },
            "orderBy": [
                {"field": {"fieldPath": "__update_time__"}, "direction": "ASCENDING"},
                {"field": {"fieldPath": "__name__"}, "direction": "ASCENDING"},
            ],
            "limit": LIST_PAGE_SIZE,
        }
    }


def _initial_incremental_value(db_incremental_field_last_value: Optional[Any]) -> str:
    if db_incremental_field_last_value is None:
        return "1970-01-01T00:00:00Z"
    if isinstance(db_incremental_field_last_value, datetime):
        return db_incremental_field_last_value.isoformat() + (
            "Z" if db_incremental_field_last_value.tzinfo is None else ""
        )
    return str(db_incremental_field_last_value)


def firestore_source(
    key_info: dict[str, str],
    database_id: str,
    collection_id: str,
    should_use_incremental_field: bool,
    incremental_field: Optional[str],
    db_incremental_field_last_value: Optional[Any],
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[FirebaseResumeConfig],
) -> SourceResponse:
    """Top-level pipeline entry. Returns a `SourceResponse` whose `items`
    callable performs the actual REST iteration on demand."""
    project_id = _project_id(key_info)
    use_incremental = should_use_incremental_field and incremental_field == "_update_time"

    def get_rows() -> Iterator[dict[str, Any]]:
        # New session per run so the access token reflects current expiry. The
        # token lasts ~1 hour; long syncs may need a refresh — the tracked
        # session adapter retries 5xx for us, but a 401 must be handled here.
        access_token = _get_access_token(key_info)
        session = _build_session(access_token)
        try:
            resume_state: FirebaseResumeConfig | None = None
            if resumable_source_manager.can_resume():
                resume_state = resumable_source_manager.load_state()
                if resume_state is not None:
                    logger.info(f"Resuming Firestore sync for collection={collection_id}, mode={resume_state.mode}")

            if use_incremental:
                cursor = (
                    resume_state.cursor
                    if resume_state and resume_state.mode == "query"
                    else _initial_incremental_value(db_incremental_field_last_value)
                )
                yield from _iter_incremental(
                    session=session,
                    project_id=project_id,
                    database_id=database_id,
                    collection_id=collection_id,
                    last_update_time_iso=cursor,
                    resumable_source_manager=resumable_source_manager,
                    logger=logger,
                )
            else:
                token = resume_state.cursor if resume_state and resume_state.mode == "list" else None
                yield from _iter_full_refresh(
                    session=session,
                    project_id=project_id,
                    database_id=database_id,
                    collection_id=collection_id,
                    resume_token=token,
                    resumable_source_manager=resumable_source_manager,
                    logger=logger,
                )
        finally:
            session.close()

    return SourceResponse(
        name=NamingConvention.normalize_identifier(collection_id),
        items=get_rows,
        primary_keys=["_id"],
        sort_mode="asc",
        partition_keys=["_create_time"],
        partition_mode="datetime",
        partition_format="month",
    )
