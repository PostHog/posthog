from io import StringIO

import pytest
from unittest.mock import MagicMock, patch

from parameterized import parameterized
from redis.exceptions import (
    AuthenticationError,
    AuthorizationError,
    BusyLoadingError,
    ConnectionError as RedisConnectionError,
    ResponseError,
)

from posthog.management.commands.redbeat_preflight import Command

MODULE = "posthog.management.commands.redbeat_preflight"


class TestRedbeatPreflightCommand:
    def run_against(self, error: Exception) -> str:
        stderr = StringIO()
        command = Command(stderr=stderr, no_color=True)
        with (
            patch(f"{MODULE}.get_redis", return_value=MagicMock()),
            patch(f"{MODULE}.find_denials", side_effect=error),
        ):
            command.handle()
        return stderr.getvalue()

    def test_an_unreachable_redis_is_skipped(self):
        message = self.run_against(RedisConnectionError("Error 111 connecting to redis:6379. Connection refused."))

        assert "Skipped, Redis did not answer" in message

    @parameterized.expand(
        [
            (AuthenticationError("WRONGPASS invalid username-password pair or user is disabled."),),
            (AuthorizationError("NOPERM this user has no permissions"),),
            (BusyLoadingError("Redis is loading the dataset in memory"),),
            (ResponseError("ACL failure in script: no permissions to run the 'get' command"),),
        ]
    )
    def test_an_error_from_a_redis_that_answered_is_not_skipped(self, error: Exception):
        with pytest.raises(type(error)):
            self.run_against(error)
