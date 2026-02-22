from unittest.mock import MagicMock

from django.http import HttpRequest, HttpResponse
from django.test import TestCase

from posthog.models.scoping import get_current_team_id
from posthog.models.scoping.middleware import TeamScopingMiddleware


class TestTeamScopingMiddleware(TestCase):
    def test_sets_team_id_for_authenticated_user(self):
        """Middleware sets team_id from authenticated user."""
        captured_team_id = None

        def get_response(request: HttpRequest) -> HttpResponse:
            nonlocal captured_team_id
            captured_team_id = get_current_team_id()
            return HttpResponse("OK")

        middleware = TeamScopingMiddleware(get_response)

        request = HttpRequest()
        request.user = MagicMock()
        request.user.is_authenticated = True
        request.user.current_team_id = 42

        middleware(request)

        assert captured_team_id == 42

    def test_resets_team_id_after_request(self):
        """Middleware resets team_id after request completes."""

        def get_response(request: HttpRequest) -> HttpResponse:
            return HttpResponse("OK")

        middleware = TeamScopingMiddleware(get_response)

        request = HttpRequest()
        request.user = MagicMock()
        request.user.is_authenticated = True
        request.user.current_team_id = 42

        middleware(request)

        # After the request, team_id should be reset to None
        assert get_current_team_id() is None

    def test_resets_team_id_on_exception(self):
        """Middleware resets team_id even if request handler raises."""

        def get_response(request: HttpRequest) -> HttpResponse:
            raise ValueError("test error")

        middleware = TeamScopingMiddleware(get_response)

        request = HttpRequest()
        request.user = MagicMock()
        request.user.is_authenticated = True
        request.user.current_team_id = 42

        try:
            middleware(request)
        except ValueError:
            pass

        # Team_id should still be reset
        assert get_current_team_id() is None

    def test_no_team_id_for_unauthenticated_user(self):
        """Middleware does not set team_id for unauthenticated users."""
        captured_team_id = "not_set"

        def get_response(request: HttpRequest) -> HttpResponse:
            nonlocal captured_team_id
            captured_team_id = get_current_team_id()
            return HttpResponse("OK")

        middleware = TeamScopingMiddleware(get_response)

        request = HttpRequest()
        request.user = MagicMock()
        request.user.is_authenticated = False

        middleware(request)

        assert captured_team_id is None

    def test_no_team_id_when_user_has_no_current_team(self):
        """Middleware handles users without current_team_id."""
        captured_team_id = "not_set"

        def get_response(request: HttpRequest) -> HttpResponse:
            nonlocal captured_team_id
            captured_team_id = get_current_team_id()
            return HttpResponse("OK")

        middleware = TeamScopingMiddleware(get_response)

        request = HttpRequest()
        request.user = MagicMock()
        request.user.is_authenticated = True
        request.user.current_team_id = None

        middleware(request)

        assert captured_team_id is None

    def test_handles_request_without_user(self):
        """Middleware handles requests without user attribute."""
        captured_team_id = "not_set"

        def get_response(request: HttpRequest) -> HttpResponse:
            nonlocal captured_team_id
            captured_team_id = get_current_team_id()
            return HttpResponse("OK")

        middleware = TeamScopingMiddleware(get_response)

        request = HttpRequest()
        # No user attribute set

        middleware(request)

        assert captured_team_id is None

    def test_preserves_existing_context(self):
        """Middleware properly nests with existing team context."""
        from posthog.models.scoping import team_scope

        captured_team_ids: list[int | None] = []

        def get_response(request: HttpRequest) -> HttpResponse:
            captured_team_ids.append(get_current_team_id())
            return HttpResponse("OK")

        middleware = TeamScopingMiddleware(get_response)

        # Set up an outer context (simulating nested middleware or test setup)
        with team_scope(100):
            request = HttpRequest()
            request.user = MagicMock()
            request.user.is_authenticated = True
            request.user.current_team_id = 42

            middleware(request)

            # After middleware, outer context should be restored
            assert get_current_team_id() == 100

        # Request handler should have seen the inner team_id
        assert captured_team_ids == [42]
