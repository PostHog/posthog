"""
Middleware to set the current team_id in context for automatic query scoping.
"""

from collections.abc import Callable

from django.http import HttpRequest, HttpResponse

from posthog.models.scoping import reset_current_team_id, set_current_team_id


class TeamScopingMiddleware:
    """
    Fallback middleware that sets team_id from the authenticated user's
    "current" team. Used for non-DRF code paths (admin, management views,
    etc.) where there's no URL-derived team_id.

    DRF nested viewsets (TeamAndOrgViewSetMixin) override this in initial()
    using the URL's team_id — the team being acted on. This avoids the same
    class of bug as #50899: user.current_team_id can differ from the team
    in the URL, and trusting it here would silently mismatch.

    Zero extra queries: only reads current_team_id (the integer FK column
    already loaded on the User object). parent_team_id is resolved lazily
    by the manager only when a PERSONS_DB_MODELS query actually happens.

    Add to MIDDLEWARE in settings.py after AuthenticationMiddleware:
        'posthog.models.scoping.middleware.TeamScopingMiddleware',
    """

    def __init__(self, get_response: Callable[[HttpRequest], HttpResponse]) -> None:
        self.get_response = get_response

    def __call__(self, request: HttpRequest) -> HttpResponse:
        token = None

        # Set team context if user is authenticated and has a current team.
        # Only reads current_team_id (the integer FK column) — no extra query.
        # parent_team_id is resolved lazily by the manager only when a
        # PERSONS_DB_MODELS query actually happens (rare).
        if hasattr(request, "user") and request.user.is_authenticated:
            team_id = getattr(request.user, "current_team_id", None)
            if team_id is not None:
                token = set_current_team_id(team_id)

        try:
            response = self.get_response(request)
        finally:
            # Always reset the context, even if an exception occurred
            if token is not None:
                reset_current_team_id(token)

        return response
