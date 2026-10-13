"""Name the API operation a DRF request performs, in the form MCP tool definitions use.

An operation is the HTTP method plus the OpenAPI path template, for example
`POST /api/projects/{}/conversations/tickets/{}/notes/`. Path parameter names are erased,
because the schema hook renames them (`{parent_lookup_team_id}` becomes `{project_id}`,
`{pk}` becomes `{id}`). Environment paths name the project paths they duplicate.

The method and path are used rather than the OpenAPI `operationId`, because the published ids
are renamed and deduplicated after drf-spectacular derives them: `partial_update` names the
organization update, and the project update gets a numbered variant of the same id.
"""

from __future__ import annotations

import re
from functools import lru_cache
from typing import Any

from drf_spectacular.generators import EndpointEnumerator

_PATH_PARAMETER_RE = re.compile(r"\{[^}/]+\}")
_ENVIRONMENTS_PREFIX = "/api/environments/{}/"
_PROJECTS_PREFIX = "/api/projects/{}/"


def api_operation(method: str, path: str) -> str:
    """The operation key for a method and an OpenAPI path template."""
    path = _PATH_PARAMETER_RE.sub("{}", path)
    if path.startswith(_ENVIRONMENTS_PREFIX):
        path = _PROJECTS_PREFIX + path.removeprefix(_ENVIRONMENTS_PREFIX)
    return f"{method.upper()} {path}"


@lru_cache(maxsize=8192)
def _path_for_route(route: str) -> str:
    return EndpointEnumerator().get_path_from_regex(route)


def api_operation_for_request(request: Any) -> str | None:
    """The operation key of a routed request, or None when the request did not resolve to a view."""
    match = getattr(request, "resolver_match", None)
    if match is None:
        return None
    return api_operation(request.method, _path_for_route(match.route))


def all_api_operations() -> frozenset[str]:
    """The operation key of every routed DRF endpoint, including ones the published schema hides."""
    enumerator = EndpointEnumerator()
    return frozenset(
        api_operation(method, path) for path, _, method, _ in enumerator._get_api_endpoints(enumerator.patterns, "")
    )
