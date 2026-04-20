import re
import json as _json
from typing import cast

from django.http import HttpRequest, HttpResponse, JsonResponse

from posthog.models.user import User

# Paths always allowed for guests — identity, auth, account settings, static/boot assets.
ALWAYS_ALLOWED_PATTERNS: list[re.Pattern] = [
    re.compile(r"^/api/users/@me/?$"),
    re.compile(r"^/api/users/@me/two_factor.*$"),
    re.compile(r"^/api/users/@me/password/?$"),
    re.compile(r"^/api/organizations/@current/?$"),
    re.compile(r"^/api/projects/@current/?$"),
    re.compile(r"^/api/environments/@current/?$"),
    re.compile(r"^/login/?$"),
    re.compile(r"^/logout/?$"),
    re.compile(r"^/api/login/?$"),
    re.compile(r"^/api/logout/?$"),
    re.compile(r"^/reset(/.*)?$"),
    re.compile(r"^/signup/verify_email(/.*)?$"),
    re.compile(r"^/_preflight/?$"),
    re.compile(r"^/static/.*$"),
    re.compile(r"^/favicon\.ico$"),
    # The guest landing page itself must be allowed — otherwise deflection redirects to /guest
    # which gets deflected again, causing an infinite loop.
    re.compile(r"^/guest(/.*)?$"),
]


RESOURCE_PATH_PATTERNS: list[tuple[re.Pattern, str]] = [
    (re.compile(r"^/api/(?:environments|projects)/(?P<team_id>\d+)/dashboards/(?P<resource_id>\d+)/?"), "dashboard"),
    (
        re.compile(r"^/api/(?:environments|projects)/(?P<team_id>\d+)/insights/(?P<resource_id>[A-Za-z0-9]+)/?"),
        "insight",
    ),
    (
        re.compile(r"^/api/(?:environments|projects)/(?P<team_id>\d+)/notebooks/(?P<resource_id>[A-Za-z0-9-]+)/?"),
        "notebook",
    ),
]

QUERY_PATH_PATTERN = re.compile(r"^/api/(?:environments|projects)/(?P<team_id>\d+)/query/?")


class GuestDeflectionMiddleware:
    """
    Deflects guest users from every endpoint not on an explicit allowlist.
    Runs after `AuthenticationMiddleware` but before `ActiveOrganizationMiddleware` — same
    slot family as the impersonation middlewares.

    Defense-in-depth with the access-control layer: AC short-circuits guests on
    resources it covers; this middleware covers surfaces AC does not (Data Warehouse,
    Logs, Error Tracking, Experiments, Feature Flags, Cohorts, etc.).
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request: HttpRequest) -> HttpResponse:
        if not self._user_is_guest(request):
            return self.get_response(request)

        if self._is_always_allowed(request.path):
            return self.get_response(request)

        if self._is_grant_bound_allowed(request):
            return self.get_response(request)

        if self._is_query_bound_to_grant(request):
            return self.get_response(request)

        return self._deflect(request)

    def _user_is_guest(self, request: HttpRequest) -> bool:
        user = getattr(request, "user", None)
        if user is None or not user.is_authenticated:
            return False
        return user.organization_memberships.filter(is_guest=True).exists()

    def _is_always_allowed(self, path: str) -> bool:
        return any(p.match(path) for p in ALWAYS_ALLOWED_PATTERNS)

    def _is_grant_bound_allowed(self, request: HttpRequest) -> bool:
        # Grants store the URL identifier as a string (e.g., "42" for dashboards, "abc123"
        # for notebooks) mirroring AccessControl.resource_id — so we can compare the URL
        # segment directly without casts or short_id→numeric lookups.
        from posthog.models import GuestResourceGrant

        for pattern, resource in RESOURCE_PATH_PATTERNS:
            match = pattern.match(request.path)
            if not match:
                continue
            team_id = int(match.group("team_id"))
            resource_id = match.group("resource_id")
            user = cast(User, request.user)
            return GuestResourceGrant.objects.filter(
                organization_membership__user=user,
                organization_membership__is_guest=True,
                team_id=team_id,
                resource=resource,
                resource_id=resource_id,
                is_pending=False,
            ).exists()
        return False

    def _is_query_bound_to_grant(self, request: HttpRequest) -> bool:
        match = QUERY_PATH_PATTERN.match(request.path)
        if not match:
            return False
        if request.method not in {"POST", "GET"}:
            return False

        team_id = int(match.group("team_id"))
        try:
            body = _json.loads(request.body or b"{}")
        except (ValueError, UnicodeDecodeError):
            return False
        if not isinstance(body, dict):
            return False

        insight_id = body.get("insight_id")
        dashboard_id = body.get("dashboard_id")
        if insight_id is None and dashboard_id is None:
            return False

        # Grants store URL identifiers (short_id for insights, stringified PK for dashboards).
        # Query payload uses numeric PKs — we resolve short_ids via lookup.
        from posthog.models import GuestResourceGrant
        from posthog.models.insight import Insight

        user = cast(User, request.user)
        qs = GuestResourceGrant.objects.filter(
            organization_membership__user=user,
            organization_membership__is_guest=True,
            team_id=team_id,
            is_pending=False,
        )
        if insight_id is not None:
            insight_short_id = (
                Insight.objects.filter(team_id=team_id, id=insight_id).values_list("short_id", flat=True).first()
            )
            candidates = {str(insight_id)}
            if insight_short_id:
                candidates.add(insight_short_id)
            if qs.filter(resource="insight", resource_id__in=list(candidates)).exists():
                return True
            from products.dashboards.backend.models.dashboard_tile import DashboardTile

            dashboard_ids = list(
                DashboardTile.objects.filter(insight_id=insight_id).values_list("dashboard_id", flat=True)
            )
            if (
                dashboard_ids
                and qs.filter(resource="dashboard", resource_id__in=[str(d) for d in dashboard_ids]).exists()
            ):
                return True
        if dashboard_id is not None and qs.filter(resource="dashboard", resource_id=str(dashboard_id)).exists():
            return True
        return False

    def _deflect(self, request: HttpRequest) -> HttpResponse:
        if request.path.startswith("/api/"):
            return JsonResponse({"detail": "Not found"}, status=404)
        # SPA route → redirect to the guest landing (/guest). Frontend PR #3 renders it.
        # Defensive: if we're already on /guest, we must NOT redirect again (infinite loop).
        # This shouldn't happen because /guest is in ALWAYS_ALLOWED_PATTERNS, but belt-and-suspenders.
        if request.path.startswith("/guest"):
            return JsonResponse({"detail": "Not found"}, status=404)
        from django.shortcuts import redirect

        return redirect("/guest")
