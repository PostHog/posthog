"""Match API requests to the MCP tools whose handlers make them.

A tool definition names its endpoints as OpenAPI path templates (`api_operations` in
`services/mcp/schema/`). A DRF permission sees a view instance, its action, and the HTTP method.
A request belongs to an operation when its path fits the template and the template resolves
through the URLconf to the same view, action, and method. The path check is cheap and runs
first. The URLconf resolution confirms a candidate, so a parameter in a template never matches
a literal segment that another route owns.
"""

from __future__ import annotations

import re
import itertools
from functools import lru_cache
from typing import Any

from django.urls import Resolver404, resolve

from posthog.api.rest_router import api_not_found
from posthog.dataclasses import frozen
from posthog.mcp_tool_definitions import McpToolApiOperation

_PATH_PARAMETER = re.compile(r"\{[^}]+\}")
# Route patterns constrain parameters differently (`\d+`, a UUID, `[^/.]+`), so a template is
# tried with each kind of value until one resolves.
_PARAMETER_CANDIDATES = ("1", "00000000-0000-0000-0000-000000000001", "placeholder")
# Project-scoped viewsets are served under both prefixes, and the OpenAPI schema names only one.
_ENVIRONMENTS_PREFIX = re.compile(r"^/api/environments/")


@frozen
class ApiOperationKey:
    view_class: type
    # The viewset action, or the lowercase HTTP method for a view that is not a viewset.
    action: str
    method: str


def api_operation_key_for_view(view: Any, method: str) -> ApiOperationKey:
    """The key of the operation a DRF view is serving."""
    method = method.upper()
    return ApiOperationKey(view_class=type(view), action=getattr(view, "action", None) or method.lower(), method=method)


@lru_cache(maxsize=4096)
def resolve_api_operation(operation: McpToolApiOperation) -> ApiOperationKey | None:
    """The key a request to this endpoint gets, or None when no DRF view serves it."""
    method = operation.method.upper()
    parts = _PATH_PARAMETER.split(operation.path)
    for values in itertools.product(_PARAMETER_CANDIDATES, repeat=len(parts) - 1):
        path = "".join(itertools.chain.from_iterable(itertools.zip_longest(parts, values, fillvalue="")))
        try:
            match = resolve(path)
        except Resolver404:
            continue
        # The URLconf ends in a catch-all that answers 404 for any `/api/` path, so a hit on it
        # means these values fit no real route.
        if match.func is api_not_found:
            continue
        view_class = getattr(match.func, "cls", None)
        if view_class is None:
            return None
        actions: dict[str, str] | None = getattr(match.func, "actions", None)
        if actions is None:
            return ApiOperationKey(view_class=view_class, action=method.lower(), method=method)
        action = actions.get(method.lower())
        if action is None:
            return None
        return ApiOperationKey(view_class=view_class, action=action, method=method)
    return None


@lru_cache(maxsize=4096)
def _path_pattern(path_template: str) -> re.Pattern[str]:
    parts = _PATH_PARAMETER.split(_normalize_path(path_template).rstrip("/"))
    parameters = _PATH_PARAMETER.findall(path_template)
    pattern = re.escape(parts[0])
    for parameter, part in zip(parameters, parts[1:]):
        pattern += (".+" if parameter == "{file_path}" else "[^/]+") + re.escape(part)
    return re.compile(pattern + "/?")


def _normalize_path(path: str) -> str:
    return _ENVIRONMENTS_PREFIX.sub("/api/projects/", path)


def request_matches_operation(*, view: Any, method: str, path: str, operation: McpToolApiOperation) -> bool:
    """Whether a request served by `view` is a call to `operation`."""
    if operation.method.upper() != method.upper():
        return False
    if _path_pattern(operation.path).fullmatch(_normalize_path(path)) is None:
        return False
    return resolve_api_operation(operation) == api_operation_key_for_view(view, method)
