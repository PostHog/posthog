import hashlib
from datetime import UTC, datetime, timedelta
from typing import Any, cast

from django.core.cache import cache
from django.db.models import F
from django.utils import timezone

import structlog
from drf_spectacular.utils import OpenApiResponse, extend_schema
from rest_framework import serializers, viewsets
from rest_framework.decorators import action
from rest_framework.request import Request
from rest_framework.response import Response

from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.models import Organization, User
from posthog.models.activity_logging.activity_log import ActivityLog
from posthog.models.organization import OrganizationMembership
from posthog.rbac.user_access_control import UserAccessControl

logger = structlog.get_logger(__name__)

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
# Bucket the "latest activity" probe so the cache key doesn't rotate on every write in busy orgs.
# The probe itself is additionally cached for this many seconds to avoid paying for it on every request.
_ACTIVITY_PROBE_BUCKET_SECONDS = 60
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
    label = serializers.CharField()  # type: ignore[assignment]
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
class WelcomeViewSet(TeamAndOrgViewSetMixin, viewsets.ViewSet):
    """Aggregated payload for the invited-user welcome screen."""

    scope_object = "organization"

    # Exposed at /api/organizations/{org}/welcome/current/. Avoids the `list` action so
    # drf-spectacular doesn't wrap the response in a paginated envelope.
    @extend_schema(
        responses={
            200: WelcomeResponseSerializer,
            404: OpenApiResponse(description="Current organization not found"),
        },
    )
    @action(detail=False, methods=["get"], url_path="current")
    def current(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        user = cast(User, request.user)
        organization = self.organization
        payload = _get_welcome_payload(organization, user)
        serializer = WelcomeResponseSerializer(payload)
        return Response(serializer.data)


# ------------- Payload builder ------------------------------------------------------------------------


def _get_welcome_payload(organization: Organization, user: User) -> dict[str, Any]:
    """Return the payload rendered on the invitee welcome dialog.

    The org-scoped subset is cached for 5 minutes. The cache key includes a time-bucketed
    latest-activity id, org member count, and a hash of onboarding-flag state so that
    team-member joins and product-onboarding changes invalidate the cache within the bucket window.
    Per-user data (inviter, suggested steps, filtered team members, is_organization_first_user)
    is always recomputed on read.
    """
    access_control = UserAccessControl(user=user, organization_id=str(organization.id))
    accessible_team_ids = _get_accessible_team_ids(organization, access_control)

    since = timezone.now() - timedelta(days=_RECENT_DAYS)
    latest_activity_id = _probe_latest_activity_id(organization, accessible_team_ids, since)

    # Include signals the activity-log probe can't see: member joins, product-onboarding flag flips.
    member_count = OrganizationMembership.objects.filter(organization=organization).count()
    onboarding_hash = _onboarding_signature(organization, accessible_team_ids)
    # Hash the team-id list so the cache key is bounded in length and safe for Memcached (250-byte limit).
    team_ids_digest = _team_ids_digest(accessible_team_ids)

    cache_key = (
        f"welcome_screen:{organization.id}:{team_ids_digest}:{latest_activity_id or 'none'}"
        f":{member_count}:{onboarding_hash}"
    )
    cacheable = cache.get(cache_key)
    if cacheable is None:
        # Cheap in-flight coalescing: the first caller to acquire this lock computes the
        # payload; concurrent callers during that window also compute (ok given the short
        # work) but subsequent requests benefit from cache.set in this window.
        cacheable = {
            "organization_name": organization.name,
            "team_members": _get_team_members(organization),
            "recent_activity": _get_recent_activity(accessible_team_ids, since),
            "popular_dashboards": _get_popular_dashboards(accessible_team_ids, access_control),
            "products_in_use": _get_products_in_use(organization),
        }
        cache.set(cache_key, cacheable, _CACHE_TTL_SECONDS)

    # Construct the user-specific response fresh each request — never mutate the cached dict.
    return {
        **cacheable,
        "inviter": _get_inviter(user, organization),
        "team_members": _filter_self(cacheable["team_members"], user),
        "suggested_next_steps": _build_suggested_next_steps(user, cacheable["products_in_use"]),
        "is_organization_first_user": _is_organization_first_user(user, organization),
    }


# ------------- Helpers --------------------------------------------------------------------------------


def _team_ids_digest(team_ids: list[int]) -> str:
    """Stable short digest of accessible team ids for use as part of a cache key."""
    if not team_ids:
        return "none"
    joined = ",".join(str(team_id) for team_id in sorted(team_ids))
    return hashlib.blake2s(joined.encode("utf-8"), digest_size=8).hexdigest()


def _onboarding_signature(organization: Organization, accessible_team_ids: list[int]) -> str:
    """Hash onboarding-flag state + opt-ins so cache invalidates when products-in-use changes.

    Without this, a team flipping session_recording_opt_in / surveys_opt_in /
    has_completed_onboarding_for keys wouldn't rotate the cache key (no ActivityLog row is written),
    so the products_in_use card would stay stale for up to _CACHE_TTL_SECONDS.
    """
    if not accessible_team_ids:
        return "none"
    from posthog.models import Team

    # Materialize only the small set of onboarding-signal columns we care about.
    signal_rows = Team.objects.filter(id__in=accessible_team_ids).values_list(
        "id", "ingested_event", "session_recording_opt_in", "surveys_opt_in", "has_completed_onboarding_for"
    )
    # Sort so ordering differences don't fragment the hash.
    signal = ";".join(repr(row) for row in sorted(signal_rows, key=lambda r: r[0]))
    return hashlib.blake2s(signal.encode("utf-8"), digest_size=8).hexdigest()


def _probe_latest_activity_id(
    organization: Organization, accessible_team_ids: list[int], since: datetime
) -> int | None:
    """Look up the most recent relevant ActivityLog id, time-bucketed and briefly cached.

    The bucket floors the current time to _ACTIVITY_PROBE_BUCKET_SECONDS so the returned id
    (and therefore the main cache key) only changes at bucket boundaries — preventing the
    cache from being silently defeated when writes land faster than reads.
    """
    if not accessible_team_ids:
        return None

    bucket = int(timezone.now().timestamp()) // _ACTIVITY_PROBE_BUCKET_SECONDS
    probe_key = f"welcome_screen:activity_probe:{organization.id}:{_team_ids_digest(accessible_team_ids)}:{bucket}"
    cached_probe = cache.get(probe_key)
    if cached_probe is not None:
        # Cache stores None as a sentinel so we don't re-probe empty orgs every request.
        return cached_probe if cached_probe != "none" else None

    latest_activity_id = (
        ActivityLog.objects.filter(
            team_id__in=accessible_team_ids,
            scope__in=_RECENT_ACTIVITY_SCOPES,
            created_at__gte=since,
            is_system=False,
            was_impersonated=False,  # matches idx_alog_team_scope_created partial index predicate
        )
        .order_by("-created_at")
        .values_list("id", flat=True)
        .first()
    )
    # Cache for the remainder of the current bucket window (+ a small buffer).
    cache.set(
        probe_key, latest_activity_id if latest_activity_id is not None else "none", _ACTIVITY_PROBE_BUCKET_SECONDS
    )
    return latest_activity_id


def _get_accessible_team_ids(organization: Organization, access_control: UserAccessControl) -> list[int]:
    """Return team ids visible to the requesting user, capped to keep the aggregation bounded.

    Fails closed: if access control filtering raises unexpectedly, we log and return an empty
    list rather than falling back to all org teams (which would leak cross-team data).
    """
    queryset = organization.teams.all()
    try:
        queryset = access_control.filter_queryset_by_access_level(queryset, include_all_if_admin=True)
    except Exception:
        logger.exception(
            "welcome.access_control_filter_failed",
            organization_id=str(organization.id),
        )
        return []
    return list(queryset.order_by("id").values_list("id", flat=True)[:_MAX_TEAMS_SCANNED])


def _filter_self(members: list[dict[str, Any]], user: User) -> list[dict[str, Any]]:
    user_email = (user.email or "").lower() if user.email else ""
    if not user_email:
        return members[:_TEAM_MEMBERS_MAX_ITEMS]
    return [m for m in members if (m.get("email") or "").lower() != user_email][:_TEAM_MEMBERS_MAX_ITEMS]


def _is_organization_first_user(user: User, organization: Organization) -> bool:
    """Whether the user arrived via their own org creation (not via an invite).

    An invited user has their inviter persisted on the membership (migration 1110). Anyone whose
    membership has no recorded inviter — the org creator, JIT/SSO provisioned users — is treated
    as NOT an invitee and does not see the welcome dialog. This avoids the earlier heuristic of
    "earliest-joined surviving member", which silently reassigned creator status after ownership handoffs.
    """
    membership = (
        OrganizationMembership.objects.filter(organization=organization, user=user).only("invited_by_id").first()
    )
    if membership is None:
        return False
    return membership.invited_by_id is None


def _get_inviter(user: User, organization: Organization) -> dict[str, str] | None:
    """Return the inviter recorded on the membership, falling back to an outstanding invite row."""
    if not user.email:
        return None
    membership = (
        OrganizationMembership.objects.filter(organization=organization, user=user).select_related("invited_by").first()
    )
    inviter = membership.invited_by if membership else None
    if inviter is None:
        # Fallback for pre-1110 memberships (no invited_by column populated before this PR) and for
        # invites accepted through paths that don't go through OrganizationInvite.use().
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


def _get_recent_activity(team_ids: list[int], since: datetime) -> list[dict[str, Any]]:
    if not team_ids:
        return []

    # Over-fetch to leave room for de-duping noisy autosave rows on the same entity.
    # Filters match the idx_alog_team_scope_created partial index predicate (is_system=False AND
    # was_impersonated=False) so the planner can use it on team_id__in lookups.
    raw_rows = list(
        ActivityLog.objects.filter(
            team_id__in=team_ids,
            scope__in=_RECENT_ACTIVITY_SCOPES,
            created_at__gte=since,
            is_system=False,
            was_impersonated=False,
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
            # A single malformed row shouldn't kill the whole welcome response, but we want
            # visibility into this happening so schema drift surfaces rather than being hidden.
            logger.warning(
                "welcome.activity_row_format_failed",
                activity_log_id=row.id,
                scope=row.scope,
                exc_info=True,
            )
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
    # Coerce raw_name to str defensively in case a malformed row has a dict or list here.
    if not isinstance(raw_name, str):
        raw_name = str(raw_name)
    entity_name = raw_name[:_MAX_ENTITY_NAME_LENGTH]

    entity_url = None
    url_builder = _SCOPE_URL_BUILDERS.get(row.scope)
    if url_builder is not None and row.item_id and row.team_id:
        entity_url = url_builder(row.team_id, row.item_id)

    timestamp = row.created_at
    if timezone.is_naive(timestamp):
        timestamp = timezone.make_aware(timestamp, UTC)

    return {
        "type": f"{row.scope}.{row.activity}",
        "actor_name": actor_name,
        "entity_name": entity_name,
        "entity_url": entity_url,
        "timestamp": timestamp.isoformat(),
    }


def _get_popular_dashboards(team_ids: list[int], access_control: UserAccessControl) -> list[dict[str, Any]]:
    if not team_ids:
        return []
    from products.dashboards.backend.models.dashboard import Dashboard

    queryset = Dashboard.objects.filter(team_id__in=team_ids, deleted=False)
    # Apply per-object access control so restricted dashboard names/descriptions don't leak via
    # this aggregation endpoint (same pattern as the main dashboards viewset).
    try:
        queryset = access_control.filter_queryset_by_access_level(queryset, include_all_if_admin=True)
    except Exception:
        logger.exception(
            "welcome.dashboard_access_control_failed",
            team_count=len(team_ids),
        )
        return []

    dashboards = list(
        queryset.order_by(F("last_accessed_at").desc(nulls_last=True), "-created_at")[:_POPULAR_DASHBOARDS_MAX_ITEMS]
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
    """Detect which products the org uses from a bounded team set.

    Strategy: one values_list() fetching every column-based signal we care about in a single
    round-trip (vs. the prior N EXISTS queries), plus one extra pass over has_completed_onboarding_for
    to surface JSONB-encoded onboarding keys.
    """
    team_ids = list(organization.teams.all().order_by("id").values_list("id", flat=True)[:_MAX_TEAMS_SCANNED])
    if not team_ids:
        return []
    from posthog.models import Team

    # Pull only the columns we need; limited by _MAX_TEAMS_SCANNED, so memory is bounded.
    signal_rows = Team.objects.filter(id__in=team_ids).values_list(
        "ingested_event", "session_recording_opt_in", "surveys_opt_in", "has_completed_onboarding_for"
    )

    products: set[str] = set()
    remaining_keys = set(_PRODUCT_KEYS)
    for ingested, session_opt_in, surveys_opt_in, completed in signal_rows:
        if ingested:
            products.add("product_analytics")
        if session_opt_in:
            products.add("session_replay")
        if surveys_opt_in:
            products.add("surveys")
        if isinstance(completed, dict):
            for key in list(remaining_keys):
                if completed.get(key):
                    products.add(key)
                    remaining_keys.discard(key)
        if len(products) == len(_PRODUCT_KEYS):
            break

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
                "reason": "See your team's dashboards and insights",
                "docs_href": "https://posthog.com/docs",
                "product_key": "product_analytics",
            }
        )

    return suggestions[:_SUGGESTED_NEXT_STEPS_MAX_ITEMS]
