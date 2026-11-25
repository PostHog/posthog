from collections.abc import Callable, Mapping
from datetime import UTC, datetime
from typing import Any

from django.http import HttpRequest, HttpResponseBase

import structlog

from posthog.api.scope_resolution import CURRENT_ALIAS

logger = structlog.get_logger(__name__)

CURRENT_ALIAS_DEPRECATED_AT = datetime(2026, 11, 25, tzinfo=UTC)
# RFC 9745 gives the Deprecation header a structured-field date: "@" and Unix seconds.
CURRENT_ALIAS_DEPRECATION = f"@{int(CURRENT_ALIAS_DEPRECATED_AT.timestamp())}"


def add_current_alias_deprecation_headers(
    request: HttpRequest,
    response: HttpResponseBase,
    *,
    parent_kwargs: Callable[[], Mapping[str, Any]],
    resolved_parents: Callable[[], Mapping[str, Any]],
) -> None:
    """Mark a response to `/api/{projects,environments,organizations}/@current/...` as deprecated.

    A successful response also links the same request with the id that `@current` resolved to, so a caller can
    switch to it. A refused one gets no link, because the project it resolved to is not one the caller can use.
    """
    segments = request.path.strip("/").split("/")
    if len(segments) < 3 or segments[0] != "api" or segments[2] != CURRENT_ALIAS:
        return

    response["Deprecation"] = CURRENT_ALIAS_DEPRECATION
    if not 200 <= response.status_code < 300:
        return

    try:
        resolved_id = _resolved_alias_id(parent_kwargs, resolved_parents)
    except Exception:
        logger.warning("current_alias_successor_failed", exc_info=True)
        return
    if resolved_id is None:
        return

    segments[2] = str(resolved_id)
    successor = "/" + "/".join(segments) + ("/" if request.path.endswith("/") else "")
    query_string = request.META.get("QUERY_STRING", "")
    if query_string:
        successor = f"{successor}?{query_string}"
    response["Link"] = f'<{successor}>; rel="successor-version"'


def _resolved_alias_id(
    parent_kwargs: Callable[[], Mapping[str, Any]], resolved_parents: Callable[[], Mapping[str, Any]]
) -> Any:
    # A detail route such as /api/projects/@current/ holds the alias in `pk`, which no parent lookup resolves.
    aliased = [lookup for lookup, value in parent_kwargs().items() if value == CURRENT_ALIAS]
    if len(aliased) != 1:
        return None
    return resolved_parents().get(aliased[0])
