from django.http import HttpRequest
from django.test import RequestFactory, SimpleTestCase

from rest_framework.exceptions import AuthenticationFailed, NotAuthenticated, PermissionDenied, ValidationError

from posthog.exceptions import exception_handler


class TestExceptionHandlerWWWAuthenticate(SimpleTestCase):
    def _request(self, *, secure: bool = False, host: str = "testserver") -> HttpRequest:
        factory = RequestFactory()
        return factory.get("/api/users/@me/", secure=secure, HTTP_HOST=host)

    def test_not_authenticated_includes_resource_metadata_hint(self) -> None:
        request = self._request(secure=True, host="us.posthog.com")
        response = exception_handler(NotAuthenticated(), {"request": request})
        assert response is not None
        assert response.status_code == 401
        assert (
            response["WWW-Authenticate"]
            == 'Bearer resource_metadata="https://us.posthog.com/.well-known/oauth-protected-resource"'
        )

    def test_authentication_failed_includes_resource_metadata_hint(self) -> None:
        request = self._request(secure=True, host="us.posthog.com")
        response = exception_handler(AuthenticationFailed("bad token"), {"request": request})
        assert response is not None
        assert response.status_code == 401
        assert (
            response["WWW-Authenticate"]
            == 'Bearer resource_metadata="https://us.posthog.com/.well-known/oauth-protected-resource"'
        )

    def test_permission_denied_does_not_set_www_authenticate(self) -> None:
        request = self._request(secure=True, host="us.posthog.com")
        response = exception_handler(PermissionDenied(), {"request": request})
        assert response is not None
        assert response.status_code == 403
        assert "WWW-Authenticate" not in response

    def test_validation_error_does_not_set_www_authenticate(self) -> None:
        request = self._request(secure=True, host="us.posthog.com")
        response = exception_handler(ValidationError("bad"), {"request": request})
        assert response is not None
        assert response.status_code == 400
        assert "WWW-Authenticate" not in response

    def test_http_request_uses_http_scheme(self) -> None:
        request = self._request(secure=False, host="localhost:8000")
        response = exception_handler(NotAuthenticated(), {"request": request})
        assert response is not None
        assert (
            response["WWW-Authenticate"]
            == 'Bearer resource_metadata="http://localhost:8000/.well-known/oauth-protected-resource"'
        )

    def test_no_request_in_context_falls_back_to_relative_path(self) -> None:
        response = exception_handler(NotAuthenticated(), {})
        assert response is not None
        assert response.status_code == 401
        assert (
            response["WWW-Authenticate"]
            == 'Bearer resource_metadata="/.well-known/oauth-protected-resource"'
        )
