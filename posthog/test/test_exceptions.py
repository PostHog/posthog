from random import Random

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

from posthog.exceptions import ClickHouseAtCapacity, ClickHouseQueryTimeOut, QueryRanConcurrently, exception_handler


class TestQueryRetryAfter(SimpleTestCase):
    @parameterized.expand(
        [
            ("capacity", ClickHouseAtCapacity, 0, 503, "17"),
            ("capacity_minimum", ClickHouseAtCapacity, 31, 503, "5"),
            ("capacity_maximum", ClickHouseAtCapacity, 12, 503, "20"),
            ("timeout", ClickHouseQueryTimeOut, 0, 504, None),
            ("single_flight_follower", QueryRanConcurrently, 0, 503, None),
        ]
    )
    def test_retry_after_is_only_advertised_for_capacity(
        self,
        _name: str,
        exception_type: type[APIException],
        seed: int,
        expected_status: int,
        expected_retry_after: str | None,
    ) -> None:
        with patch("random.randint", side_effect=Random(seed).randint):
            response = exception_handler(exception_type(), {"request": RequestFactory().post("/api/projects/1/query/")})
        assert response is not None
        self.assertEqual(response.status_code, expected_status)
        self.assertEqual(response.get("Retry-After"), expected_retry_after)

    def test_capacity_retry_after_varies_between_errors_but_is_stable_for_each_error(self) -> None:
        with patch("random.randint", side_effect=Random(0).randint):
            for expected_retry_after in ("17", "18", "6"):
                exception = ClickHouseAtCapacity(detail="Try again later.", code="busy")
                for _ in range(2):
                    response = exception_handler(
                        exception, {"request": RequestFactory().post("/api/projects/1/query/")}
                    )
                    assert response is not None
                    self.assertEqual(response.status_code, 503)
                    self.assertEqual(response["Retry-After"], expected_retry_after)
                    self.assertEqual(response.data["detail"], "Try again later.")
                    self.assertEqual(response.data["code"], "busy")


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
