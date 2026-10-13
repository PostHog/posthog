import pytest

import redis.exceptions
from temporalio.exceptions import ApplicationError

from posthog.temporal.common.redis_errors import is_transient_redis_error


def _raised_from(error: BaseException, cause: BaseException) -> BaseException:
    error.__cause__ = cause
    return error


@pytest.mark.parametrize(
    "error,expected",
    [
        (ValueError("Temporary failure in name resolution"), False),
        (
            redis.exceptions.ConnectionError(
                "Error -3 connecting to redis-example:6379. Temporary failure in name resolution."
            ),
            True,
        ),
        (redis.exceptions.TimeoutError("Timeout connecting to server: Temporary failure in name resolution"), True),
        # A host that never resolves is a real misconfiguration, not a blip — must keep reaching
        # error tracking.
        (
            redis.exceptions.ConnectionError("Error -2 connecting to redis-example:6379. Name or service not known."),
            False,
        ),
        # A refused connection or bad auth is a real defect, not a DNS blip.
        (redis.exceptions.ConnectionError("Error 111 connecting to redis-example:6379. Connection refused."), False),
        (redis.exceptions.AuthenticationError("invalid username-password pair"), False),
        # An activity that re-raises one typed error keeps the drop in __cause__ only.
        (
            _raised_from(
                ApplicationError("Failed to check billing limits"),
                redis.exceptions.ConnectionError(
                    "Error -3 connecting to redis-example:6379. Temporary failure in name resolution."
                ),
            ),
            True,
        ),
    ],
)
def test_is_transient_redis_error_by_message(error: BaseException, expected: bool) -> None:
    assert is_transient_redis_error(error) is expected


@pytest.mark.parametrize("suppress_context", [False, True])
def test_is_transient_redis_error_ignores_context(suppress_context: bool) -> None:
    error = KeyError("team_id")
    error.__context__ = redis.exceptions.ConnectionError(
        "Error -3 connecting to redis-example:6379. Temporary failure in name resolution."
    )
    error.__suppress_context__ = suppress_context

    assert not is_transient_redis_error(error)


@pytest.mark.parametrize("cycle_length", [1, 2])
def test_is_transient_redis_error_handles_cyclic_causes(cycle_length: int) -> None:
    errors = [ValueError("not a redis error") for _ in range(cycle_length)]
    for index, error in enumerate(errors):
        error.__cause__ = errors[(index + 1) % cycle_length]

    assert not is_transient_redis_error(errors[0])
