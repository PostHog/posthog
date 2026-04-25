import re
import logging
from collections.abc import Generator
from typing import Any
from urllib.parse import urlparse

import requests
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential_jitter

from posthog.temporal.data_imports.pipelines.pipeline.typings import SourceResponse

logger = logging.getLogger(__name__)

_CONVEX_CLOUD_HOST_RE = re.compile(r"^[a-z0-9][a-z0-9-]*\.convex\.cloud$")

_TRANSIENT_STATUS_CODES = frozenset({502, 503, 504})


class _ConvexTransientError(Exception):
    """Raised for transient Convex responses (5xx) so the retry layer kicks in."""

    pass


@retry(
    retry=retry_if_exception_type((requests.exceptions.ConnectionError, _ConvexTransientError)),
    stop=stop_after_attempt(5),
    wait=wait_exponential_jitter(initial=1, max=30),
    reraise=True,
)
def _get_with_retry(url: str, **kwargs: Any) -> requests.Response:
    """GET with retries on transient connection / proxy errors and 502/503/504 responses.

    Non-transient HTTP responses (4xx, including the 400 InvalidWindowToReadDocuments and
    401/403 auth errors) are returned to the caller unchanged so the existing handling
    in get_non_retryable_errors stays effective.
    """
    response = requests.get(url, **kwargs)
    if response.status_code in _TRANSIENT_STATUS_CODES:
        raise _ConvexTransientError(f"Convex returned transient status {response.status_code}")
    return response


class InvalidDeployUrlError(Exception):
    """Raised when the deploy URL does not meet Convex security requirements."""

    pass


def validate_deploy_url(deploy_url: str) -> str:
    """Validate and normalize a Convex deployment URL.

    Enforces https scheme, host matching *.convex.cloud, no query/fragment.
    Returns the validated base URL (scheme + host, no trailing slash).
    """
    parsed = urlparse(deploy_url.strip())

    if parsed.scheme != "https":
        raise InvalidDeployUrlError(
            "Deployment URL must use the https scheme (e.g. https://your-deployment-123.convex.cloud)."
        )

    host = (parsed.hostname or "").lower()
    if not host or not _CONVEX_CLOUD_HOST_RE.match(host):
        raise InvalidDeployUrlError(f"Deployment URL host must match <deployment-name>.convex.cloud, got: {host!r}.")

    if parsed.query:
        raise InvalidDeployUrlError("Deployment URL must not contain query parameters.")

    if parsed.fragment:
        raise InvalidDeployUrlError("Deployment URL must not contain a URL fragment.")

    return f"https://{host}"


def _headers(deploy_key: str) -> dict[str, str]:
    return {
        "Authorization": f"Convex {deploy_key}",
        "Content-Type": "application/json",
    }


def get_json_schemas(deploy_url: str, deploy_key: str) -> dict[str, Any]:
    url = f"{deploy_url.rstrip('/')}/api/json_schemas"
    response = _get_with_retry(
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

        response = _get_with_retry(base_url, headers=_headers(deploy_key), params=params, timeout=60)
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


class InvalidWindowError(Exception):
    """Raised when the delta cursor is older than Convex's retention window."""

    pass


def document_deltas(
    deploy_url: str, deploy_key: str, table_name: str, cursor: int
) -> Generator[list[dict[str, Any]], None, int]:
    """Paginate through incremental document changes since a cursor.

    Yields batches of changed documents. Returns the new cursor.
    Deleted documents have _deleted=True.

    Raises InvalidWindowError if the cursor is older than Convex's retention window (~30 days).
    """
    base_url = f"{deploy_url.rstrip('/')}/api/document_deltas"
    current_cursor = cursor

    while True:
        params: dict[str, Any] = {"tableName": table_name, "cursor": current_cursor, "format": "json"}

        response = _get_with_retry(base_url, headers=_headers(deploy_key), params=params, timeout=60)

        if response.status_code == 400:
            error_data = response.json()
            if error_data.get("code") == "InvalidWindowToReadDocuments":
                raise InvalidWindowError(
                    f"Delta cursor for table '{table_name}' is older than Convex's ~30 day retention window. "
                    f"Please trigger a full resync of this source."
                )
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
        clean_url = validate_deploy_url(deploy_url)
    except InvalidDeployUrlError as e:
        return False, str(e)
    try:
        get_json_schemas(clean_url, deploy_key)
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


def _normalize_timestamps(batch: list[dict[str, Any]]) -> list[dict[str, Any]]:
    for row in batch:
        creation_time = row.get("_creationTime")
        if isinstance(creation_time, (int, float)) and creation_time > 1e12:
            row["_creationTime"] = int(creation_time / 1000)
    return batch


def convex_source(
    deploy_url: str,
    deploy_key: str,
    table_name: str,
    team_id: int,
    job_id: str,
    should_use_incremental_field: bool,
    db_incremental_field_last_value: Any | None,
) -> SourceResponse:
    clean_url = validate_deploy_url(deploy_url)

    def items_generator():
        if should_use_incremental_field and db_incremental_field_last_value is not None:
            cursor = int(db_incremental_field_last_value)
            for batch in document_deltas(clean_url, deploy_key, table_name, cursor):
                yield _normalize_timestamps(batch)
        else:
            for batch in list_snapshot(clean_url, deploy_key, table_name):
                yield _normalize_timestamps(batch)

    return SourceResponse(
        name=table_name,
        items=items_generator,
        primary_keys=["_id"],
        partition_count=1,
        partition_size=1,
        partition_mode="datetime",
        partition_format="week",
        partition_keys=["_creationTime"],
    )
