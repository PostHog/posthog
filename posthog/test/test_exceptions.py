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

from posthog.exceptions import ClickHouseAtCapacity, DatabaseSchemaUnavailable, QueryRanConcurrently, exception_handler


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


class TestServiceUnavailableCodes(SimpleTestCase):
    @parameterized.expand(
        [
            ("capacity", ClickHouseAtCapacity(), "clickhouse_at_capacity"),
            ("single_flight_follower", QueryRanConcurrently(), "query_ran_concurrently"),
            ("schema", DatabaseSchemaUnavailable(), "database_schema_unavailable"),
        ]
    )
    def test_each_503_carries_its_own_code(self, _name: str, exception: APIException, expected_code: str) -> None:
        request = RequestFactory().get("/api/environments/1/query/")
        response = exception_handler(exception, {"request": request})
        assert response is not None
        assert response.status_code == 503
        assert response.data["code"] == expected_code
