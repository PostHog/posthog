import hashlib
from enum import StrEnum

from django.core.cache import caches
from django.http import HttpRequest

import structlog
import posthoganalytics

from posthog.clickhouse.query_tagging import get_query_tag_value
from posthog.event_usage import get_request_analytics_properties, report_user_action, sanitize_header_value

logger = structlog.get_logger(__name__)

dedupe_cache = caches["current_alias_usage"]

CURRENT_ALIAS = "@current"
CURRENT_ALIAS_REQUESTS_METRIC = "api.current_alias.requests"
CURRENT_ALIAS_USED_EVENT = "api current alias used"
# One event per caller and route each day is enough to find who to contact, while the
# metric keeps the full request volume.
ATTRIBUTION_DEDUPE_SECONDS = 24 * 60 * 60
TOKEN_QUERY_PARAMS = ("token", "api_key")


class CurrentAliasScope(StrEnum):
    ORGANIZATION = "organization"
    PROJECT = "project"
    PERSONAL_API_KEY = "personal_api_key"


_SCOPE_BY_COLLECTION: dict[str, CurrentAliasScope] = {
    "organizations": CurrentAliasScope.ORGANIZATION,
    "projects": CurrentAliasScope.PROJECT,
    "environments": CurrentAliasScope.PROJECT,
    "personal_api_keys": CurrentAliasScope.PERSONAL_API_KEY,
}


def current_alias_scope(path: str) -> CurrentAliasScope | None:
    segments = path.strip("/").split("/")
    if len(segments) < 3 or segments[0] != "api" or segments[2] != CURRENT_ALIAS:
        return None
    return _SCOPE_BY_COLLECTION.get(segments[1])


def record_current_alias_use(request: HttpRequest, *, route: str, status_class: str) -> None:
    scope = current_alias_scope(request.path)
    if scope is None:
        return
    # Analytics must never fail the request it observes.
    try:
        _record(request, scope=scope, route=route, status_class=status_class)
    except Exception:
        logger.warning("current_alias_usage_record_failed", exc_info=True)


def _record(request: HttpRequest, *, scope: CurrentAliasScope, route: str, status_class: str) -> None:
    user = request.user
    access_method = str(get_query_tag_value("access_method") or ("session" if user.is_authenticated else "anonymous"))
    source = str(get_query_tag_value("source") or "")
    token_in_query = any(param in request.GET for param in TOKEN_QUERY_PARAMS)
    method = request.method or ""

    client = posthoganalytics.default_client
    if client is not None:
        client.metrics.count(
            CURRENT_ALIAS_REQUESTS_METRIC,
            1,
            attributes={
                "scope": scope.value,
                "route": route,
                "method": method,
                "access_method": access_method,
                "source": source,
                "token_in_query": token_in_query,
                "status_class": status_class,
            },
        )

    if not user.is_authenticated:
        return

    api_key_mask = get_query_tag_value("api_key_mask")
    # Synthetic principals such as team secret tokens share one pk, so their distinct_id is what tells callers apart.
    caller = getattr(user, "distinct_id", None) or user.pk
    dedupe_parts = (caller, scope.value, route, method, access_method, token_in_query, api_key_mask)
    dedupe_key = "current_alias_use:" + hashlib.sha256(repr(dedupe_parts).encode()).hexdigest()
    if not dedupe_cache.add(dedupe_key, True, timeout=ATTRIBUTION_DEDUPE_SECONDS):
        return

    report_user_action(
        user,
        CURRENT_ALIAS_USED_EVENT,
        {
            "scope": scope.value,
            "route": route,
            "method": method,
            "status_class": status_class,
            "access_method": access_method,
            "token_in_query": token_in_query,
            "api_key_mask": api_key_mask,
            "api_key_label": get_query_tag_value("api_key_label"),
            "origin": sanitize_header_value(request.headers.get("Origin")),
        },
        analytics_props=get_request_analytics_properties(request),
    )
