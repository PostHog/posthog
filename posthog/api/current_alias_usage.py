import hashlib
from enum import StrEnum

from django.conf import settings
from django.core.cache import caches
from django.http import HttpRequest

import structlog
import posthoganalytics

from posthog.api.scope_resolution import CURRENT_ALIAS, scope_resolution
from posthog.auth import OAuthAccessTokenAuthentication
from posthog.clickhouse.query_tagging import get_query_tag_value
from posthog.event_usage import get_request_analytics_properties, sanitize_header_value
from posthog.models.activity_logging.utils import activity_storage
from posthog.synthetic_user import SyntheticUser

logger = structlog.get_logger(__name__)

dedupe_cache = caches["current_alias_usage"]

CURRENT_ALIAS_REQUESTS_METRIC = "api.current_alias.requests"
CURRENT_ALIAS_USED_EVENT = "api current alias used"
# One event per caller and route each day identifies who to contact; the metric keeps the volume.
ATTRIBUTION_DEDUPE_SECONDS = 24 * 60 * 60
# Session calls come from PostHog's own web app, which is fixed in code, so they get no event.
UNATTRIBUTED_ACCESS_METHODS = frozenset({"session", "anonymous"})
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


def _oauth_application_id() -> str | None:
    # The OAuth authenticator records the token's application as the request's activity credential.
    # CHQueries runs inside ActivityLoggingMiddleware, so the credential is still set here.
    credential = activity_storage.get_credential()
    if credential is None or credential.type != OAuthAccessTokenAuthentication.activity_credential_type:
        return None
    return credential.id


def _record(request: HttpRequest, *, scope: CurrentAliasScope, route: str, status_class: str) -> None:
    user = request.user
    # The authenticator's tag can be missing when the middleware reads it, so an Authorization header alone marks a
    # credential caller rather than a session.
    access_method = str(
        get_query_tag_value("access_method")
        or ("credential" if request.headers.get("Authorization") else None)
        or ("session" if user.is_authenticated else "anonymous")
    )
    source = str(get_query_tag_value("source") or "")
    token_in_query = any(param in request.GET for param in TOKEN_QUERY_PARAMS)
    method = request.method or ""
    resolution = scope_resolution(request)
    project_from = resolution.source.value if resolution else ""
    credential_pins_scope = bool(resolution) and (
        resolution.credential_pins_organization
        if scope == CurrentAliasScope.ORGANIZATION
        else resolution.credential_pins_project
    )

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
                "project_from": project_from,
                "credential_pins_scope": credential_pins_scope,
                "status_class": status_class,
            },
        )

    if access_method in UNATTRIBUTED_ACCESS_METHODS or scope == CurrentAliasScope.PERSONAL_API_KEY:
        return

    # Synthetic principals such as team secret tokens share one pk, so their distinct_id is what tells callers apart.
    distinct_id = getattr(user, "distinct_id", None)
    if not distinct_id:
        return
    api_key_mask = get_query_tag_value("api_key_mask")
    oauth_application_id = _oauth_application_id()
    dedupe_parts = (
        distinct_id,
        scope.value,
        route,
        method,
        access_method,
        token_in_query,
        api_key_mask,
        oauth_application_id,
    )
    dedupe_key = "current_alias_use:" + hashlib.sha256(repr(dedupe_parts).encode()).hexdigest()
    if not dedupe_cache.add(dedupe_key, True, timeout=ATTRIBUTION_DEDUPE_SECONDS):
        return

    # Foreign key columns give the ids without a query. `object` admits SyntheticUser, which request.user omits.
    principal: object = request.user
    if isinstance(principal, SyntheticUser):
        team_id, organization_id = principal.team.pk, principal.team.organization_id
    else:
        team_id, organization_id = (
            getattr(user, "current_team_id", None),
            getattr(user, "current_organization_id", None),
        )
    groups = {"instance": settings.SITE_URL}
    if organization_id:
        groups["organization"] = str(organization_id)

    posthoganalytics.capture(
        distinct_id=distinct_id,
        event=CURRENT_ALIAS_USED_EVENT,
        properties={
            **get_request_analytics_properties(request),
            "scope": scope.value,
            "route": route,
            "method": method,
            "status_class": status_class,
            "access_method": access_method,
            "token_in_query": token_in_query,
            "project_from": project_from,
            "credential_pins_scope": credential_pins_scope,
            "api_key_mask": api_key_mask,
            "api_key_label": get_query_tag_value("api_key_label"),
            "oauth_application_id": oauth_application_id,
            "origin": sanitize_header_value(request.headers.get("Origin")),
            "team_id": team_id,
        },
        groups=groups,
    )
