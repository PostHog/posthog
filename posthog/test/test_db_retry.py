from unittest.mock import patch

from django.db import InterfaceError, OperationalError
from django.test import SimpleTestCase

from posthog.db_retry import retry_dropped_connection


class FakeConnection:
    def __init__(self, errors_occurred: bool = False, in_atomic_block: bool = False) -> None:
        self.errors_occurred = errors_occurred
        self.in_atomic_block = in_atomic_block
        self.closed = False

    def close(self) -> None:
        self.closed = True


class TestRetryDroppedConnection(SimpleTestCase):
    def _run(self, read, connections: list[FakeConnection] | None = None):
        registry = patch("posthog.db_retry.connections")
        with registry as mocked:
            mocked.all.return_value = connections or []
            return retry_dropped_connection("test", read)

    def test_retries_once_on_a_dropped_connection_and_returns_the_second_result(self) -> None:
        attempts = []

        def read() -> str:
            attempts.append(None)
            if len(attempts) == 1:
                raise OperationalError("server closed the connection unexpectedly")
            return "served"

        failed = FakeConnection(errors_occurred=True)
        healthy = FakeConnection()

        assert self._run(read, [failed, healthy]) == "served"
        assert len(attempts) == 2
        assert failed.closed
        assert not healthy.closed

    def test_reraises_when_the_connection_drops_twice(self) -> None:
        attempts = []

        def read() -> None:
            attempts.append(None)
            raise InterfaceError("connection already closed")

        with self.assertRaises(InterfaceError):
            self._run(read, [FakeConnection(errors_occurred=True)])
        assert len(attempts) == 2

    def test_does_not_retry_a_failure_that_a_fresh_connection_would_not_clear(self) -> None:
        attempts = []

        def read() -> None:
            attempts.append(None)
            raise OperationalError("query_wait_timeout")

        with self.assertRaises(OperationalError):
            self._run(read, [FakeConnection(errors_occurred=True)])
        assert len(attempts) == 1

    def test_does_not_retry_inside_an_atomic_block(self) -> None:
        # The transaction went down with the connection, so a retry can only fail again.
        attempts = []

        def read() -> None:
            attempts.append(None)
            raise OperationalError("server closed the connection unexpectedly")

        failed = FakeConnection(errors_occurred=True, in_atomic_block=True)

        with self.assertRaises(OperationalError):
            self._run(read, [failed])
        assert len(attempts) == 1
        assert not failed.closed
