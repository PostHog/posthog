from collections.abc import Generator
from typing import Any

import requests

from posthog.temporal.data_imports.pipelines.pipeline.typings import SourceResponse


def _headers(deploy_key: str) -> dict[str, str]:
    return {
        "Authorization": f"Convex {deploy_key}",
        "Content-Type": "application/json",
    }


def get_json_schemas(deploy_url: str, deploy_key: str) -> dict[str, Any]:
    url = f"{deploy_url.rstrip('/')}/api/json_schemas"
    response = requests.get(
        url, headers=_headers(deploy_key), params={"deltaSchema": "true", "format": "json"}, timeout=30
    )
    response.raise_for_status()
    return response.json()


def list_snapshot(deploy_url: str, deploy_key: str, table_name: str) -> Generator[list[dict[str, Any]], None, int]:
    """Paginate through a full table snapshot.

    Yields batches of documents. Returns the snapshot cursor (as the generator return value)
    which can be used as the starting cursor for document_deltas.
    """
    base_url = f"{deploy_url.rstrip('/')}/api/list_snapshot"
    cursor: int | None = None
    snapshot: int | None = None

    while True:
        params: dict[str, Any] = {"tableName": table_name, "format": "json"}
        if cursor is not None:
            params["cursor"] = cursor
        if snapshot is not None:
            params["snapshot"] = snapshot

        response = requests.get(base_url, headers=_headers(deploy_key), params=params, timeout=60)
        response.raise_for_status()
        data = response.json()

        values = data.get("values", [])
        if values:
            yield values

        snapshot = data.get("snapshot", snapshot)
        cursor = data.get("cursor")
        has_more = data.get("hasMore", False)

        if not has_more:
            return snapshot or 0


def document_deltas(
    deploy_url: str, deploy_key: str, table_name: str, cursor: int
) -> Generator[list[dict[str, Any]], None, int]:
    """Paginate through incremental document changes since a cursor.

    Yields batches of changed documents. Returns the new cursor.
    Deleted documents have _deleted=True.
    """
    base_url = f"{deploy_url.rstrip('/')}/api/document_deltas"
    current_cursor = cursor

    while True:
        params: dict[str, Any] = {"tableName": table_name, "cursor": current_cursor, "format": "json"}

        response = requests.get(base_url, headers=_headers(deploy_key), params=params, timeout=60)
        response.raise_for_status()
        data = response.json()

        values = data.get("values", [])
        if values:
            yield values

        current_cursor = data.get("cursor", current_cursor)
        has_more = data.get("hasMore", False)

        if not has_more:
            return current_cursor


def validate_credentials(deploy_url: str, deploy_key: str) -> tuple[bool, str | None]:
    try:
        get_json_schemas(deploy_url, deploy_key)
        return True, None
    except requests.exceptions.HTTPError as e:
        if e.response is not None:
            try:
                error_data = e.response.json()
                if error_data.get("code") == "StreamingExportNotEnabled":
                    return (
                        False,
                        "Streaming export requires the Convex Professional plan. See https://www.convex.dev/plans to upgrade.",
                    )
            except Exception:
                pass
            if e.response.status_code in (401, 403):
                return False, "Invalid deploy key. Check your Convex deploy key and try again."
        return False, str(e)
    except requests.exceptions.ConnectionError:
        return False, "Could not connect to the Convex deployment. Check your deployment URL and try again."
    except requests.exceptions.RequestException as e:
        return False, str(e)


def convex_source(
    deploy_url: str,
    deploy_key: str,
    table_name: str,
    team_id: int,
    job_id: str,
    should_use_incremental_field: bool,
    db_incremental_field_last_value: Any | None,
) -> SourceResponse:
    def items_generator():
        if should_use_incremental_field and db_incremental_field_last_value is not None:
            cursor = int(db_incremental_field_last_value)
            yield from document_deltas(deploy_url, deploy_key, table_name, cursor)
        else:
            yield from list_snapshot(deploy_url, deploy_key, table_name)

    return SourceResponse(
        name=table_name,
        items=items_generator,
        primary_keys=["_id"],
        partition_count=1,
        partition_size=1,
        partition_mode="datetime",
        partition_format="day",
        partition_keys=["_ts"],
    )
