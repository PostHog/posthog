"""
Middleware to set the current team_id in context for automatic query scoping.
"""

from collections.abc import Callable

from django.http import HttpRequest, HttpResponse

from posthog.models.scoping import reset_current_team_id, set_current_team_id


class TeamScopingMiddleware:
    """
    Middleware that sets the current team_id from the authenticated user.

    This enables automatic team scoping for all database queries within the request.
    Models using TeamScopedManager will automatically filter by this team_id.

    Also caches the parent_team_id to avoid extra database queries for PERSONS_DB_MODELS.

    Add to MIDDLEWARE in settings.py after AuthenticationMiddleware:
        'posthog.models.scoping.middleware.TeamScopingMiddleware',
    """

    def __init__(self, get_response: Callable[[HttpRequest], HttpResponse]) -> None:
        self.get_response = get_response

    def __call__(self, request: HttpRequest) -> HttpResponse:
        token = None

        # Set team context if user is authenticated and has a current team
        if hasattr(request, "user") and request.user.is_authenticated:
            team_id = getattr(request.user, "current_team_id", None)
            if team_id is not None:
                # Cache parent_team_id to avoid extra queries for PERSONS_DB_MODELS
                parent_team_id = self._get_parent_team_id(request.user)
                token = set_current_team_id(team_id, parent_team_id)

        try:
            response = self.get_response(request)
        finally:
            # Always reset the context, even if an exception occurred
            if token is not None:
                reset_current_team_id(token)

        return response

    def _get_parent_team_id(self, user) -> int | None:
        """Get parent_team_id from the user's current team if available."""
        current_team = getattr(user, "current_team", None)
        if current_team is not None:
            return getattr(current_team, "parent_team_id", None)
        return None
