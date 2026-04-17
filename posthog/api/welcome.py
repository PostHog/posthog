from datetime import timedelta
from typing import Any, cast

from django.core.cache import cache
from django.db.models import F, Q
from django.utils import timezone

from drf_spectacular.utils import OpenApiResponse, extend_schema, inline_serializer
from rest_framework import serializers, viewsets
from rest_framework.request import Request
from rest_framework.response import Response

from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.models import Organization, User
from posthog.models.activity_logging.activity_log import ActivityLog
from posthog.models.organization import OrganizationMembership, is_organization_first_user

# Keys on Team.has_completed_onboarding_for are ProductKey values mapped to booleans.
# Fallback presence-of-data checks supplement the onboarding signal.
_PRODUCT_KEYS = [
    "product_analytics",
    "session_replay",
    "feature_flags",
    "experiments",
    "surveys",
    "error_tracking",
    "data_warehouse",
    "llm_analytics",
    "web_analytics",
]

# Activity log scopes surfaced in the "what your team has been doing" card.
_RECENT_ACTIVITY_SCOPES = ["Insight", "Dashboard", "Notebook", "Experiment", "FeatureFlag", "Survey"]

_SCOPE_URL_BUILDERS = {
    "Insight": lambda team_id, item_id: f"/project/{team_id}/insights/{item_id}",
    "Dashboard": lambda team_id, item_id: f"/project/{team_id}/dashboard/{item_id}",
    "Notebook": lambda team_id, item_id: f"/project/{team_id}/notebooks/{item_id}",
    "Experiment": lambda team_id, item_id: f"/project/{team_id}/experiments/{item_id}",
    "FeatureFlag": lambda team_id, item_id: f"/project/{team_id}/feature_flags/{item_id}",
    "Survey": lambda team_id, item_id: f"/project/{team_id}/surveys/{item_id}",
}

_RECENT_ACTIVITY_MAX_ITEMS = 10
_POPULAR_DASHBOARDS_MAX_ITEMS = 3
_TEAM_MEMBERS_MAX_ITEMS = 8
_SUGGESTED_NEXT_STEPS_MAX_ITEMS = 3
_RECENT_DAYS = 30
_CACHE_TTL_SECONDS = 5 * 60


@extend_schema(tags=["platform_features"])
class WelcomeViewSet(TeamAndOrgViewSetMixin, viewsets.GenericViewSet):
    """Aggregated payload for the invited-user welcome screen."""

    scope_object = "organization"
    queryset = Organization.objects.none()

    @extend_schema(
        responses={
            200: inline_serializer(
                name="WelcomeResponse",
                fields={
                    "organization_name": serializers.CharField(),
                    "inviter": serializers.DictField(allow_null=True),
                    "team_members": serializers.ListField(child=serializers.DictField()),
                    "recent_activity": serializers.ListField(child=serializers.DictField()),
                    "popular_dashboards": serializers.ListField(child=serializers.DictField()),
                    "products_in_use": serializers.ListField(child=serializers.CharField()),
                    "suggested_next_steps": serializers.ListField(child=serializers.DictField()),
                    "is_organization_first_user": serializers.BooleanField(),
                },
            ),
            404: OpenApiResponse(description="Current organization not found"),
        },
    )
    def list(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        user = cast(User, request.user)
        organization = self.organization
        payload = _get_welcome_payload(organization, user)
        return Response(payload)


def _get_welcome_payload(organization: Organization, user: User) -> dict[str, Any]:
    """Cached per-org for 5 minutes, keyed on the most recent relevant activity log id so it invalidates naturally."""
    team_ids = list(organization.teams.values_list("id", flat=True))
    latest_activity_id = (
        ActivityLog.objects.filter(
            Q(organization_id=organization.id) | Q(team_id__in=team_ids),
            scope__in=_RECENT_ACTIVITY_SCOPES,
        )
        .order_by("-created_at")
        .values_list("id", flat=True)
        .first()
    )
    cache_key = f"welcome_screen:{organization.id}:{latest_activity_id or 'none'}"
    cached = cache.get(cache_key)
    is_first_user = is_organization_first_user(user, organization)
    if cached is not None:
        # Per-user data must still be recomputed because the cache is per-org.
        payload = dict(cached)
        payload["inviter"] = _get_inviter(user, organization)
        payload["suggested_next_steps"] = _build_suggested_next_steps(user, payload.get("products_in_use", []))
        payload["team_members"] = _filter_self(payload.get("team_members", []), user)
        payload["is_organization_first_user"] = is_first_user
        return payload

    team_members = _get_team_members(organization)
    payload = {
        "organization_name": organization.name,
        "team_members": team_members,
        "recent_activity": _get_recent_activity(organization, team_ids),
        "popular_dashboards": _get_popular_dashboards(team_ids),
        "products_in_use": _get_products_in_use(organization),
    }
    cache.set(cache_key, payload, _CACHE_TTL_SECONDS)

    payload["inviter"] = _get_inviter(user, organization)
    payload["team_members"] = _filter_self(team_members, user)
    payload["suggested_next_steps"] = _build_suggested_next_steps(user, payload["products_in_use"])
    payload["is_organization_first_user"] = is_first_user
    return payload


def _filter_self(members: list[dict[str, Any]], user: User) -> list[dict[str, Any]]:
    return [member for member in members if member.get("email") != user.email][:_TEAM_MEMBERS_MAX_ITEMS]


def _get_inviter(user: User, organization: Organization) -> dict[str, str] | None:
    invite = (
        organization.invites.filter(target_email__iexact=user.email, created_by__isnull=False)
        .select_related("created_by")
        .order_by("-created_at")
        .first()
    )
    if invite is None or invite.created_by is None:
        return None
    return {
        "name": invite.created_by.first_name or invite.created_by.email,
        "email": invite.created_by.email,
    }


def _get_team_members(organization: Organization) -> list[dict[str, Any]]:
    recent_threshold = timezone.now() - timedelta(days=7)
    today_threshold = timezone.now() - timedelta(hours=24)

    # Fetch one extra to account for filtering out the current user downstream.
    memberships = (
        OrganizationMembership.objects.filter(organization=organization, user__is_active=True)
        .select_related("user")
        .order_by(F("user__last_login").desc(nulls_last=True), "-joined_at")[: _TEAM_MEMBERS_MAX_ITEMS + 1]
    )

    members: list[dict[str, Any]] = []
    for membership in memberships:
        member_user = membership.user
        last_login = member_user.last_login

        if last_login is None:
            last_active = "inactive"
        elif last_login >= today_threshold:
            last_active = "today"
        elif last_login >= recent_threshold:
            last_active = "this_week"
        else:
            last_active = "inactive"

        members.append(
            {
                "name": member_user.first_name or member_user.email,
                "email": member_user.email,
                "avatar": None,
                "role": OrganizationMembership.Level(membership.level).label,
                "last_active": last_active,
            }
        )
    return members


def _get_recent_activity(organization: Organization, team_ids: list[int]) -> list[dict[str, Any]]:
    if not team_ids:
        return []

    since = timezone.now() - timedelta(days=_RECENT_DAYS)
    # Over-fetch to leave room for de-duping noisy autosave rows on the same entity.
    raw_rows = list(
        ActivityLog.objects.filter(
            Q(organization_id=organization.id) | Q(team_id__in=team_ids),
            scope__in=_RECENT_ACTIVITY_SCOPES,
            created_at__gte=since,
        )
        .exclude(is_system=True)
        .select_related("user")
        .order_by("-created_at")[: _RECENT_ACTIVITY_MAX_ITEMS * 4]
    )

    seen: set[tuple[str, str | None]] = set()
    results: list[dict[str, Any]] = []
    for row in raw_rows:
        dedupe_key = (row.scope, row.item_id)
        if dedupe_key in seen:
            continue
        seen.add(dedupe_key)

        user = row.user
        actor_name = (user.first_name or user.email) if user is not None else "Someone"
        detail = row.detail if isinstance(row.detail, dict) else {}
        entity_name = detail.get("name") or detail.get("short_id") or row.scope

        entity_url = None
        url_builder = _SCOPE_URL_BUILDERS.get(row.scope)
        if url_builder is not None and row.item_id and row.team_id:
            entity_url = url_builder(row.team_id, row.item_id)

        results.append(
            {
                "type": f"{row.scope}.{row.activity}",
                "actor_name": actor_name,
                "entity_name": entity_name,
                "entity_url": entity_url,
                "timestamp": row.created_at.isoformat(),
            }
        )
        if len(results) >= _RECENT_ACTIVITY_MAX_ITEMS:
            break
    return results


def _get_popular_dashboards(team_ids: list[int]) -> list[dict[str, Any]]:
    if not team_ids:
        return []
    from products.dashboards.backend.models.dashboard import Dashboard

    dashboards = list(
        Dashboard.objects.filter(team_id__in=team_ids, deleted=False).order_by(
            F("last_accessed_at").desc(nulls_last=True), "-created_at"
        )[:_POPULAR_DASHBOARDS_MAX_ITEMS]
    )
    return [
        {
            "id": dashboard.id,
            "name": dashboard.name or f"Dashboard #{dashboard.id}",
            "description": dashboard.description or "",
            "team_id": dashboard.team_id,
            "url": f"/project/{dashboard.team_id}/dashboard/{dashboard.id}",
        }
        for dashboard in dashboards
    ]


def _get_products_in_use(organization: Organization) -> list[str]:
    products: set[str] = set()
    for team in organization.teams.only(
        "id",
        "has_completed_onboarding_for",
        "session_recording_opt_in",
        "ingested_event",
        "surveys_opt_in",
    ):
        onboarded = team.has_completed_onboarding_for or {}
        if isinstance(onboarded, dict):
            for key in _PRODUCT_KEYS:
                if onboarded.get(key):
                    products.add(key)
        if team.ingested_event:
            products.add("product_analytics")
        if team.session_recording_opt_in:
            products.add("session_replay")
        if getattr(team, "surveys_opt_in", False):
            products.add("surveys")

    return sorted(products)


def _build_suggested_next_steps(user: User, products_in_use: list[str]) -> list[dict[str, str]]:
    role = (user.role_at_organization or "").lower() if user.role_at_organization else ""
    team_id = user.current_team_id
    suggestions: list[dict[str, str]] = []

    if "session_replay" in products_in_use and role in {"product", "designer", ""}:
        href = f"/project/{team_id}/replay/home" if team_id else "/replay/home"
        suggestions.append(
            {
                "label": "Watch a recent recording",
                "href": href,
                "reason": "Your team uses Session replay",
                "docs_href": "https://posthog.com/docs/session-replay",
                "product_key": "session_replay",
            }
        )

    if "feature_flags" in products_in_use and role in {"engineering", "engineer", ""}:
        href = f"/project/{team_id}/feature_flags" if team_id else "/feature_flags"
        suggestions.append(
            {
                "label": "See active feature flags",
                "href": href,
                "reason": "Your team uses Feature flags",
                "docs_href": "https://posthog.com/docs/feature-flags",
                "product_key": "feature_flags",
            }
        )

    if "experiments" in products_in_use and role in {"product", "engineering", "engineer", ""}:
        href = f"/project/{team_id}/experiments" if team_id else "/experiments"
        suggestions.append(
            {
                "label": "Explore running experiments",
                "href": href,
                "reason": "Your team uses Experiments",
                "docs_href": "https://posthog.com/docs/experiments",
                "product_key": "experiments",
            }
        )

    if not suggestions:
        href = f"/project/{team_id}" if team_id else "/"
        suggestions.append(
            {
                "label": "Explore the project home",
                "href": href,
                "reason": "A good place to start",
                "docs_href": "https://posthog.com/docs",
                "product_key": "product_analytics",
            }
        )

    return suggestions[:_SUGGESTED_NEXT_STEPS_MAX_ITEMS]
