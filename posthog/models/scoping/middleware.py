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

    Add to MIDDLEWARE in settings.py:
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
                token = set_current_team_id(team_id)

        try:
            response = self.get_response(request)
        finally:
            # Always reset the context, even if an exception occurred
            if token is not None:
                reset_current_team_id(token)

        return response


def team_scoping_middleware(
    get_response: Callable[[HttpRequest], HttpResponse],
) -> Callable[[HttpRequest], HttpResponse]:
    """
    Function-based middleware for team scoping.

    Alternative to the class-based middleware above.
    """

    def middleware(request: HttpRequest) -> HttpResponse:
        token = None

        if hasattr(request, "user") and request.user.is_authenticated:
            team_id = getattr(request.user, "current_team_id", None)
            if team_id is not None:
                token = set_current_team_id(team_id)

        try:
            return get_response(request)
        finally:
            if token is not None:
                reset_current_team_id(token)

    return middleware
