from typing import cast

from django.http import HttpRequest
from django.test import RequestFactory, SimpleTestCase

from parameterized import parameterized
from rest_framework.exceptions import (
    APIException,
    AuthenticationFailed,
    NotAuthenticated,
    PermissionDenied,
    ValidationError,
)

from posthog.exceptions import ExceptionContext, exception_handler


class TestExceptionHandlerWWWAuthenticate(SimpleTestCase):
    def _request(self, *, secure: bool = True, host: str = "us.posthog.com") -> HttpRequest:
        factory = RequestFactory()
        return factory.get("/api/users/@me/", secure=secure, HTTP_HOST=host)

    @parameterized.expand(
        [
            (
                "not_authenticated_https",
                NotAuthenticated(),
                {"secure": True, "host": "us.posthog.com"},
                401,
                'Bearer resource_metadata="https://us.posthog.com/.well-known/oauth-protected-resource"',
            ),
            (
                "authentication_failed_https",
                AuthenticationFailed("bad token"),
                {"secure": True, "host": "us.posthog.com"},
                401,
                'Bearer resource_metadata="https://us.posthog.com/.well-known/oauth-protected-resource"',
            ),
            (
                "not_authenticated_http",
                NotAuthenticated(),
                {"secure": False, "host": "localhost:8000"},
                401,
                'Bearer resource_metadata="http://localhost:8000/.well-known/oauth-protected-resource"',
            ),
            (
                "permission_denied",
                PermissionDenied(),
                {"secure": True, "host": "us.posthog.com"},
                403,
                None,
            ),
            (
                "validation_error",
                ValidationError("bad"),
                {"secure": True, "host": "us.posthog.com"},
                400,
                None,
            ),
        ]
    )
    def test_www_authenticate_on_drf_exception(
        self,
        _name: str,
        exception: APIException,
        request_kwargs: dict,
        expected_status: int,
        expected_header: str | None,
    ) -> None:
        response = exception_handler(exception, {"request": self._request(**request_kwargs)})
        assert response is not None
        assert response.status_code == expected_status
        if expected_header is None:
            assert "WWW-Authenticate" not in response
        else:
            assert response["WWW-Authenticate"] == expected_header

    def test_no_request_in_context_falls_back_to_relative_path(self) -> None:
        response = exception_handler(NotAuthenticated(), cast(ExceptionContext, {}))
        assert response is not None
        assert response.status_code == 401
        assert response["WWW-Authenticate"] == 'Bearer resource_metadata="/.well-known/oauth-protected-resource"'
