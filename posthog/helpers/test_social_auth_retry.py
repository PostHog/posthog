from collections.abc import Callable

from unittest.mock import MagicMock, patch

from django.test import SimpleTestCase

import requests
from parameterized import parameterized
from social_core.backends.base import BaseAuth
from social_core.exceptions import AuthConnectionError, AuthFailed

from posthog.helpers.social_auth_retry import install


def _http_error(status_code: int) -> requests.HTTPError:
    response = requests.Response()
    response.status_code = status_code
    return requests.HTTPError(f"{status_code} error", response=response)


def _connection_error() -> AuthConnectionError:
    return AuthConnectionError(
        MagicMock(), "HTTPSConnectionPool(host='www.googleapis.com', port=443): Tunnel connection failed: 429"
    )


class TestSocialAuthRetry(SimpleTestCase):
    def setUp(self) -> None:
        super().setUp()
        sleep = patch("tenacity.nap.time.sleep")
        sleep.start()
        self.addCleanup(sleep.stop)

        self.backend = MagicMock(spec=BaseAuth)
        self.backend.name = "google-oauth2"

    def _install_over(self, *results: object) -> MagicMock:
        provider = MagicMock(side_effect=results)

        def unretried_request(_self: BaseAuth, *args: object, **kwargs: object) -> object:
            return provider(*args, **kwargs)

        patcher = patch.object(BaseAuth, "request", unretried_request)
        patcher.start()
        self.addCleanup(patcher.stop)
        install()
        return provider

    @parameterized.expand(
        [
            ("proxy_shed_the_connection", _connection_error),
            ("provider_rate_limited_the_call", lambda: _http_error(429)),
        ]
    )
    def test_replays_a_transient_failure_until_it_succeeds(self, _name: str, build_error: Callable[[], Exception]):
        expected = requests.Response()
        provider = self._install_over(build_error(), build_error(), expected)

        assert BaseAuth.request(self.backend, "https://oauth2.googleapis.com/token") is expected
        assert provider.call_count == 3

    @parameterized.expand(
        [
            ("provider_rejected_the_request", lambda: _http_error(400)),
            ("provider_refused_the_credentials", lambda: AuthFailed(MagicMock(), "invalid_grant")),
        ]
    )
    def test_does_not_replay_a_permanent_failure(self, _name: str, build_error: Callable[[], Exception]):
        error = build_error()
        provider = self._install_over(error)

        with self.assertRaises(type(error)):
            BaseAuth.request(self.backend, "https://oauth2.googleapis.com/token")
        assert provider.call_count == 1

    def test_installing_twice_does_not_nest_the_retries(self):
        provider = self._install_over(_connection_error(), _connection_error(), _connection_error())
        install()

        with self.assertRaises(AuthConnectionError):
            BaseAuth.request(self.backend, "https://oauth2.googleapis.com/token")
        assert provider.call_count == 3
