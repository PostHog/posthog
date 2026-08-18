from django.db import InterfaceError, OperationalError
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

from posthog.exceptions import exception_handler


def _operational_error_with_sqlstate(sqlstate: str) -> OperationalError:
    cause = Exception("server-raised failure")
    cause.sqlstate = sqlstate  # type: ignore[attr-defined]
    error = OperationalError("operator intervention")
    error.__cause__ = cause
    return error


def _transient_masked_by_keyerror() -> OperationalError:
    # Reproduces the real chain: Django's FK descriptor raises KeyError on a cache miss, the
    # pool-wait timeout fires inside that except block, so the KeyError lands in __context__ and
    # would otherwise become the reported error.
    error = OperationalError("query_wait_timeout")
    error.__context__ = KeyError("current_organization")
    return error


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


@override_settings(DEBUG=False)
class TestExceptionHandlerTransientDatabaseError(SimpleTestCase):
    def _request(self) -> HttpRequest:
        return RequestFactory().get("/api/organizations/@current/integrations/")

    @parameterized.expand(
        [
            ("query_wait_timeout", OperationalError("query_wait_timeout")),
            ("server_closed", OperationalError("server closed the connection unexpectedly")),
            ("interface_error", InterfaceError("connection reset by peer")),
            ("sqlstate_57P01", _operational_error_with_sqlstate("57P01")),
            ("masked_by_keyerror_context", _transient_masked_by_keyerror()),
        ]
    )
    def test_transient_db_error_maps_to_retryable_503(self, _name: str, exception: Exception) -> None:
        response = exception_handler(exception, {"request": self._request()})
        assert response is not None
        assert response.status_code == 503
        assert response["Retry-After"] == "1"
        assert response.data["code"] == "database_unavailable"

    def test_interface_error_without_marker_is_not_mapped(self) -> None:
        # "connection already closed" is not in the transient markers, so this must not be
        # silently swallowed as retryable.
        response = exception_handler(InterfaceError("some unrelated interface failure"), {"request": self._request()})
        if response is not None:
            assert response.status_code != 503
            assert "Retry-After" not in response

    def test_persistent_db_error_is_not_mapped(self) -> None:
        response = exception_handler(
            OperationalError("duplicate key value violates unique constraint"), {"request": self._request()}
        )
        if response is not None:
            assert response.status_code != 503
            assert "Retry-After" not in response
