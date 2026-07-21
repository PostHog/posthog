from unittest.mock import patch

from django.http import HttpRequest
from django.test import RequestFactory, SimpleTestCase, override_settings

from parameterized import parameterized
from rest_framework.exceptions import (
    APIException,
    AuthenticationFailed,
    NotAuthenticated,
    PermissionDenied,
    ValidationError,
)

from posthog.clickhouse.client.limit import ConcurrencyLimitExceeded
from posthog.exceptions import CONCURRENCY_LIMIT_USER_MESSAGE, exception_handler


@override_settings(SITE_URL="https://us.posthog.com")
class TestExceptionHandlerWWWAuthenticate(SimpleTestCase):
    def _request(self, *, secure: bool = True, host: str = "us.posthog.com") -> HttpRequest:
        factory = RequestFactory()
        return factory.get("/api/users/@me/", secure=secure, HTTP_HOST=host)

    @parameterized.expand(
        [
            (
                "not_authenticated",
                NotAuthenticated(),
                401,
                'Bearer resource_metadata="https://us.posthog.com/.well-known/oauth-protected-resource"',
            ),
            (
                "authentication_failed",
                AuthenticationFailed("bad token"),
                401,
                'Bearer resource_metadata="https://us.posthog.com/.well-known/oauth-protected-resource"',
            ),
            (
                "permission_denied",
                PermissionDenied(),
                403,
                None,
            ),
            (
                "validation_error",
                ValidationError("bad"),
                400,
                None,
            ),
        ]
    )
    def test_www_authenticate_on_drf_exception(
        self,
        _name: str,
        exception: APIException,
        expected_status: int,
        expected_header: str | None,
    ) -> None:
        response = exception_handler(exception, {"request": self._request()})
        assert response is not None
        assert response.status_code == expected_status
        if expected_header is None:
            assert "WWW-Authenticate" not in response
        else:
            assert response["WWW-Authenticate"] == expected_header

    def test_hint_ignores_host_header(self) -> None:
        """A spoofed Host header must not steer the discovery URL away from SITE_URL."""
        response = exception_handler(NotAuthenticated(), {"request": self._request(host="attacker.example")})
        assert response is not None
        assert (
            response["WWW-Authenticate"]
            == 'Bearer resource_metadata="https://us.posthog.com/.well-known/oauth-protected-resource"'
        )

    def test_concurrency_limit_exceeded_becomes_clean_throttle_without_capture(self) -> None:
        # A saturated query limiter used to reach the handler as an unhandled exception: a 500
        # response plus an error-tracking capture. It must instead render as a 429 throttle and
        # never be reported. Guards every DRF entry point that drives a query, not just /query.
        exc = ConcurrencyLimitExceeded("Exceeded maximum concurrency limit: 6 for key: app:dashboard_query")
        with patch("posthog.exceptions.capture_exception") as mock_capture:
            response = exception_handler(exc, {"request": self._request()})

        assert response is not None
        assert response.status_code == 429
        assert response.data["type"] == "throttled_error"
        assert response.data["detail"] == CONCURRENCY_LIMIT_USER_MESSAGE
        mock_capture.assert_not_called()
