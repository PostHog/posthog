from datetime import timedelta
from typing import Any, cast

from django.core.cache import cache
from django.db.models import F
from django.utils import timezone

from drf_spectacular.utils import OpenApiResponse, extend_schema
from rest_framework import serializers, viewsets
from rest_framework.request import Request
from rest_framework.response import Response

from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.models import Organization, User
from posthog.models.activity_logging.activity_log import ActivityLog
from posthog.models.organization import OrganizationMembership, is_organization_first_user
from posthog.rbac.user_access_control import UserAccessControl

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
_MAX_TEAMS_SCANNED = 200
_MAX_ENTITY_NAME_LENGTH = 200


# ------------- Response serializers -----------------------------------------------------------------


class _WelcomeInviterSerializer(serializers.Serializer):
    name = serializers.CharField()
    email = serializers.EmailField()


class _WelcomeTeamMemberSerializer(serializers.Serializer):
    name = serializers.CharField()
    email = serializers.EmailField()
    avatar = serializers.CharField(allow_null=True)
    role = serializers.CharField()
    last_active = serializers.ChoiceField(choices=["today", "this_week", "inactive", "never"])


class _WelcomeRecentActivitySerializer(serializers.Serializer):
    type = serializers.CharField(help_text="Scope.activity pair, e.g. 'Insight.created'.")
    actor_name = serializers.CharField()
    entity_name = serializers.CharField()
    entity_url = serializers.CharField(allow_null=True)
    timestamp = serializers.DateTimeField()


class _WelcomePopularDashboardSerializer(serializers.Serializer):
    id = serializers.IntegerField()
    name = serializers.CharField()
    description = serializers.CharField(allow_blank=True)
    team_id = serializers.IntegerField()
    url = serializers.CharField()


class _WelcomeSuggestedStepSerializer(serializers.Serializer):
    label = serializers.CharField()
    href = serializers.CharField()
    reason = serializers.CharField(allow_blank=True)
    docs_href = serializers.CharField(required=False)
    product_key = serializers.CharField(required=False)


class WelcomeResponseSerializer(serializers.Serializer):
    organization_name = serializers.CharField()
    inviter = _WelcomeInviterSerializer(allow_null=True)
    team_members = _WelcomeTeamMemberSerializer(many=True)
    recent_activity = _WelcomeRecentActivitySerializer(many=True)
    popular_dashboards = _WelcomePopularDashboardSerializer(many=True)
    products_in_use = serializers.ListField(child=serializers.CharField())
    suggested_next_steps = _WelcomeSuggestedStepSerializer(many=True)
    is_organization_first_user = serializers.BooleanField()


# ------------- Viewset --------------------------------------------------------------------------------


@extend_schema(tags=["platform_features"])
class WelcomeViewSet(TeamAndOrgViewSetMixin, viewsets.GenericViewSet):
    """Aggregated payload for the invited-user welcome screen."""

    scope_object = "organization"
    queryset = Organization.objects.none()

    @extend_schema(
        responses={
            200: WelcomeResponseSerializer,
            404: OpenApiResponse(description="Current organization not found"),
        },
    )
    def list(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        user = cast(User, request.user)
        organization = self.organization
        payload = _get_welcome_payload(organization, user)
        return Response(payload)


# ------------- Payload builder ------------------------------------------------------------------------


def _get_welcome_payload(organization: Organization, user: User) -> dict[str, Any]:
    """Return the payload rendered on the invitee welcome dialog.

    The org-scoped subset is cached for 5 minutes keyed on the most recent activity log id so it
    invalidates naturally after team activity. Per-user data is always recomputed on read so that
    (a) the same cache entry is safe to serve to multiple users, and (b) access control is applied
    to each reader independently.
    """
    access_control = UserAccessControl(user=user, organization_id=str(organization.id))
    accessible_team_ids = _get_accessible_team_ids(organization, access_control)

    since = timezone.now() - timedelta(days=_RECENT_DAYS)
    latest_activity_id = (
        ActivityLog.objects.filter(
            team_id__in=accessible_team_ids,
            scope__in=_RECENT_ACTIVITY_SCOPES,
            created_at__gte=since,
            is_system=False,
        )
        .order_by("-created_at")
        .values_list("id", flat=True)
        .first()
        if accessible_team_ids
        else None
    )
    cache_key = (
        f"welcome_screen:{organization.id}:{','.join(map(str, accessible_team_ids))}:{latest_activity_id or 'none'}"
    )
    cacheable = cache.get(cache_key)
    if cacheable is None:
        cacheable = {
            "organization_name": organization.name,
            "team_members": _get_team_members(organization),
            "recent_activity": _get_recent_activity(accessible_team_ids, since),
            "popular_dashboards": _get_popular_dashboards(accessible_team_ids),
            "products_in_use": _get_products_in_use(organization),
        }
        cache.set(cache_key, cacheable, _CACHE_TTL_SECONDS)

    # Construct the user-specific response fresh each request — never mutate the cached dict.
    return {
        **cacheable,
        "inviter": _get_inviter(user, organization),
        "team_members": _filter_self(cacheable["team_members"], user),
        "suggested_next_steps": _build_suggested_next_steps(user, cacheable["products_in_use"]),
        "is_organization_first_user": is_organization_first_user(user, organization),
    }


# ------------- Helpers --------------------------------------------------------------------------------


def _get_accessible_team_ids(organization: Organization, access_control: UserAccessControl) -> list[int]:
    """Return team ids visible to the requesting user, capped to keep the aggregation bounded."""
    queryset = organization.teams.all()
    try:
        queryset = access_control.filter_queryset_by_access_level(queryset, include_all_if_admin=True)
    except Exception:
        # Defensive — access control subsystem may raise for orgs without the advanced-permissions feature.
        pass
    return list(queryset.order_by("id").values_list("id", flat=True)[:_MAX_TEAMS_SCANNED])


def _filter_self(members: list[dict[str, Any]], user: User) -> list[dict[str, Any]]:
    user_email = (user.email or "").lower()
    return [m for m in members if (m.get("email") or "").lower() != user_email][:_TEAM_MEMBERS_MAX_ITEMS]


def _get_inviter(user: User, organization: Organization) -> dict[str, str] | None:
    """Return the inviter recorded on the membership, falling back to an outstanding invite row."""
    membership = (
        OrganizationMembership.objects.filter(organization=organization, user=user)
        .select_related("invited_by")
        .only("invited_by__first_name", "invited_by__email", "invited_by__id")
        .first()
    )
    inviter = getattr(membership, "invited_by", None) if membership else None
    if inviter is None:
        # Fallback for pre-1102 memberships or invites accepted through legacy paths — look up a lingering invite.
        invite = (
            organization.invites.filter(target_email__iexact=user.email, created_by__isnull=False)
            .select_related("created_by")
            .order_by("-created_at")
            .first()
        )
        inviter = invite.created_by if invite is not None else None
    if inviter is None:
        return None
    return {
        "name": inviter.first_name or (inviter.email.split("@", 1)[0] if inviter.email else "A teammate"),
        "email": inviter.email,
    }


def _get_team_members(organization: Organization) -> list[dict[str, Any]]:
    now = timezone.now()
    today_threshold = now - timedelta(hours=24)
    recent_threshold = now - timedelta(days=7)

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
            last_active = "never"
        elif last_login >= today_threshold:
            last_active = "today"
        elif last_login >= recent_threshold:
            last_active = "this_week"
        else:
            last_active = "inactive"

        # Fall back to the local-part of the email rather than the whole address to avoid leaking raw emails in the UI.
        display_name = member_user.first_name or (
            member_user.email.split("@", 1)[0] if member_user.email else "A teammate"
        )
        members.append(
            {
                "name": display_name,
                "email": member_user.email,
                "avatar": None,
                "role": OrganizationMembership.Level(membership.level).label,
                "last_active": last_active,
            }
        )
    return members


def _get_recent_activity(team_ids: list[int], since) -> list[dict[str, Any]]:
    if not team_ids:
        return []

    # Over-fetch to leave room for de-duping noisy autosave rows on the same entity.
    # Using filter(is_system=False) (not exclude(is_system=True)) so the partial indexes on activity_log
    # that are conditioned on is_system=False are actually usable.
    raw_rows = list(
        ActivityLog.objects.filter(
            team_id__in=team_ids,
            scope__in=_RECENT_ACTIVITY_SCOPES,
            created_at__gte=since,
            is_system=False,
        )
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

        try:
            entity = _format_activity_row(row, team_ids)
        except Exception:
            # A single malformed row shouldn't kill the whole welcome response.
            continue
        if entity is None:
            continue
        results.append(entity)
        if len(results) >= _RECENT_ACTIVITY_MAX_ITEMS:
            break
    return results


def _format_activity_row(row: ActivityLog, team_ids: list[int]) -> dict[str, Any] | None:
    if row.team_id not in team_ids:
        return None

    member_user = row.user
    if member_user is not None:
        actor_name = member_user.first_name or (
            member_user.email.split("@", 1)[0] if member_user.email else "A teammate"
        )
    else:
        actor_name = "Someone"

    detail = row.detail if isinstance(row.detail, dict) else {}
    raw_name = detail.get("name") or detail.get("short_id") or row.scope
    entity_name = (str(raw_name) if raw_name is not None else row.scope)[:_MAX_ENTITY_NAME_LENGTH]

    entity_url = None
    url_builder = _SCOPE_URL_BUILDERS.get(row.scope)
    if url_builder is not None and row.item_id and row.team_id:
        entity_url = url_builder(row.team_id, row.item_id)

    timestamp = row.created_at
    if timezone.is_naive(timestamp):
        timestamp = timezone.make_aware(timestamp, timezone.utc)

    return {
        "type": f"{row.scope}.{row.activity}",
        "actor_name": actor_name,
        "entity_name": entity_name,
        "entity_url": entity_url,
        "timestamp": timestamp.isoformat(),
    }


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
            "name": (dashboard.name or f"Dashboard #{dashboard.id}")[:_MAX_ENTITY_NAME_LENGTH],
            "description": (dashboard.description or "")[:_MAX_ENTITY_NAME_LENGTH],
            "team_id": dashboard.team_id,
            "url": f"/project/{dashboard.team_id}/dashboard/{dashboard.id}",
        }
        for dashboard in dashboards
    ]


def _get_products_in_use(organization: Organization) -> list[str]:
    """Detect which products the org uses via a handful of bounded EXISTS queries.

    Replaces an earlier implementation that iterated every team row in Python, which scaled
    O(teams) and loaded all has_completed_onboarding_for JSONB blobs into memory.
    """
    # Resolve the team IDs first — we need an unsliced queryset to pass to .filter() below.
    team_ids = list(organization.teams.all().order_by("id").values_list("id", flat=True)[:_MAX_TEAMS_SCANNED])
    if not team_ids:
        return []
    from posthog.models import Team

    teams_qs = Team.objects.filter(id__in=team_ids)
    products: set[str] = set()

    # Presence-of-data heuristics — each is a single indexed EXISTS.
    if teams_qs.filter(ingested_event=True).exists():
        products.add("product_analytics")
    if teams_qs.filter(session_recording_opt_in=True).exists():
        products.add("session_replay")
    if teams_qs.filter(surveys_opt_in=True).exists():
        products.add("surveys")

    # Onboarding-flag signal — has_completed_onboarding_for is JSONB, so check per-key via EXISTS.
    for key in _PRODUCT_KEYS:
        if key in products:
            continue
        if teams_qs.filter(has_completed_onboarding_for__has_key=key).exists():
            products.add(key)

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
                "reason": "See your team's dashboards and insights.",
                "docs_href": "https://posthog.com/docs",
                "product_key": "product_analytics",
            }
        )

    return suggestions[:_SUGGESTED_NEXT_STEPS_MAX_ITEMS]
