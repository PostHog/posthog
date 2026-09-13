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

from posthog.exceptions import (
    CLICKHOUSE_CAPACITY_RETRY_AFTER_SECONDS,
    ClickHouseAtCapacity,
    ClickHouseQueryTimeOut,
    exception_handler,
)


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

    @parameterized.expand(
        [
            # A 503 capacity failure is transient cluster load, so advertise a fixed back-off window.
            ("at_capacity", ClickHouseAtCapacity(), 503, str(CLICKHOUSE_CAPACITY_RETRY_AFTER_SECONDS)),
            # A 504 timeout is a repeatable per-query failure, so it must not carry a fixed Retry-After:
            # the client would just rerun the same expensive query, and the failure breaker can serve it
            # with a much longer reopen window than a fixed 30s.
            ("query_timeout", ClickHouseQueryTimeOut(), 504, None),
        ]
    )
    def test_retry_after_on_clickhouse_capacity_responses(
        self,
        _name: str,
        exception: APIException,
        expected_status: int,
        expected_retry_after: str | None,
    ) -> None:
        # Without Retry-After, API clients retry blind during a capacity event and worsen the pileup.
        response = exception_handler(exception, {"request": self._request()})
        assert response is not None
        assert response.status_code == expected_status
        if expected_retry_after is None:
            assert "Retry-After" not in response
        else:
            assert response["Retry-After"] == expected_retry_after

    def test_hint_ignores_host_header(self) -> None:
        """A spoofed Host header must not steer the discovery URL away from SITE_URL."""
        response = exception_handler(NotAuthenticated(), {"request": self._request(host="attacker.example")})
        assert response is not None
        assert (
            response["WWW-Authenticate"]
            == 'Bearer resource_metadata="https://us.posthog.com/.well-known/oauth-protected-resource"'
        )
