from unittest import mock

from django.db import OperationalError, ProgrammingError
from django.test import SimpleTestCase

from posthog.db_backends.failopen.base import CircuitOpenError, DatabaseWrapper
from posthog.db_circuit_breaker import BreakerDecision

ALIAS = "visual_review_db_reader"


class TestFailOpenBackend(SimpleTestCase):
    def setUp(self) -> None:
        super().setUp()
        self.wrapper = DatabaseWrapper.__new__(DatabaseWrapper)
        self.wrapper.connection = None
        self.wrapper.alias = ALIAS

        self.breaker = mock.Mock()
        breaker_patch = mock.patch("posthog.db_backends.failopen.base.get_circuit_breaker", return_value=self.breaker)
        breaker_patch.start()
        self.addCleanup(breaker_patch.stop)

        self.super_patch = mock.patch("posthog.db_backends.failopen.base.PostgresDatabaseWrapper.ensure_connection")
        self.super_ensure = self.super_patch.start()
        self.addCleanup(self.super_patch.stop)

    def test_open_breaker_raises_without_connecting(self) -> None:
        self.breaker.before_connect.return_value = BreakerDecision(allowed=False, is_probe=False)

        with self.assertRaises(CircuitOpenError):
            self.wrapper.ensure_connection()

        self.super_ensure.assert_not_called()
        self.breaker.record_failure.assert_not_called()
        self.breaker.record_success.assert_not_called()

    def test_successful_connection_records_success(self) -> None:
        self.breaker.before_connect.return_value = BreakerDecision(allowed=True, is_probe=True)

        self.wrapper.ensure_connection()

        self.super_ensure.assert_called_once()
        self.breaker.record_success.assert_called_once_with(ALIAS, was_probe=True)
        self.breaker.record_failure.assert_not_called()

    def test_connection_failure_records_failure_and_reraises(self) -> None:
        self.breaker.before_connect.return_value = BreakerDecision(allowed=True, is_probe=False)
        self.super_ensure.side_effect = OperationalError("connection refused")

        with self.assertRaises(OperationalError):
            self.wrapper.ensure_connection()

        self.breaker.record_failure.assert_called_once_with(ALIAS, was_probe=False)
        self.breaker.record_success.assert_not_called()

    def test_query_error_is_not_counted_as_connection_failure(self) -> None:
        self.breaker.before_connect.return_value = BreakerDecision(allowed=True, is_probe=False)
        self.super_ensure.side_effect = ProgrammingError("relation does not exist")

        with self.assertRaises(ProgrammingError):
            self.wrapper.ensure_connection()

        self.breaker.record_failure.assert_not_called()
        self.breaker.record_success.assert_not_called()

    def test_existing_connection_skips_breaker(self) -> None:
        self.wrapper.connection = object()

        self.wrapper.ensure_connection()

        self.breaker.before_connect.assert_not_called()
        self.super_ensure.assert_not_called()
