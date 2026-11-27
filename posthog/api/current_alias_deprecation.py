from datetime import UTC, datetime
from urllib.parse import quote

from django.http import HttpRequest, HttpResponseBase, QueryDict
from django.utils.http import http_date

from posthog.api.request_scope import request_scope_shadow
from posthog.api.scope_resolution import CURRENT_ALIAS

CURRENT_ALIAS_DEPRECATED_AT = datetime(2026, 11, 25, tzinfo=UTC)
CURRENT_ALIAS_SUNSET_AT = datetime(2027, 4, 30, 23, 59, 59, tzinfo=UTC)
CURRENT_ALIAS_DOCS_URL = "https://posthog.com/docs/api/current-alias-deprecation"
# RFC 9745 gives the Deprecation header a structured-field date: "@" and Unix seconds.
CURRENT_ALIAS_DEPRECATION = f"@{int(CURRENT_ALIAS_DEPRECATED_AT.timestamp())}"
CURRENT_ALIAS_SUNSET = http_date(CURRENT_ALIAS_SUNSET_AT.timestamp())
# personal_api_keys/@current names the key that signs the request, so it stays.
DEPRECATED_COLLECTIONS = frozenset({"projects", "environments", "organizations"})
# Query parameters that carry a credential. A successor link goes back in a response header, so it leaves them out.
CREDENTIAL_QUERY_PARAMS = ("personal_api_key", "token", "api_key")


def successor_url(path: str, query: QueryDict) -> str:
    """Build a successor link from a decoded request path and the request's query, without credentials.

    The path is escaped again because Django decodes it: an encoded `?` or newline in an id would otherwise move part
    of the path into the query or make the header invalid.
    """
    kept = query.copy()
    for name in CREDENTIAL_QUERY_PARAMS:
        kept.pop(name, None)
    # The safe characters of Django's escape_uri_path, which this module can't import: contracts modules reach it.
    escaped_path = quote(path, safe="/:@&+$,-_.!~*'()")
    return f"{escaped_path}?{kept.urlencode()}" if kept else escaped_path


def add_current_alias_deprecation_headers(request: HttpRequest, response: HttpResponseBase) -> None:
    """Mark a response to `/api/{projects,environments,organizations}/@current/...` as deprecated.

    A successful response also links the same request with the id the view used, which the request scope resolver
    recorded, so a caller can switch to it. A refused one gets no successor, because that id is not one the caller
    can use.
    """
    segments = request.path.strip("/").split("/")
    if len(segments) < 3 or segments[0] != "api" or segments[1] not in DEPRECATED_COLLECTIONS:
        return
    if segments[2] != CURRENT_ALIAS:
        return

    response["Deprecation"] = CURRENT_ALIAS_DEPRECATION
    response["Sunset"] = CURRENT_ALIAS_SUNSET
    links = [f'<{CURRENT_ALIAS_DOCS_URL}>; rel="deprecation"']
    successor = _successor(request, response, segments)
    if successor is not None:
        links.insert(0, f'<{successor}>; rel="successor-version"')
    response["Link"] = ", ".join(links)


def _successor(request: HttpRequest, response: HttpResponseBase, segments: list[str]) -> str | None:
    if not 200 <= response.status_code < 300:
        return None
    # A detail route such as /api/projects/@current/ has no scoped parent, so the resolver records nothing for it.
    shadow = request_scope_shadow(request)
    if shadow is None:
        return None

    path = "/" + "/".join([*segments[:2], shadow.current_scope_id, *segments[3:]])
    if request.path.endswith("/"):
        path += "/"
    return successor_url(path, request.GET)
