import django.db

import psycopg.errors
from parameterized import parameterized

from posthog.db_read_only import (
    drop_read_only_transaction_exceptions,
    is_read_only_transaction_error,
    is_read_only_transaction_event,
)


def _wrapped_read_only_error() -> django.db.InternalError:
    # Mirror how Django surfaces a driver read-only error: its own InternalError with the
    # psycopg ReadOnlySqlTransaction chained on __cause__.
    cause = psycopg.errors.ReadOnlySqlTransaction("cannot execute UPDATE in a read-only transaction")
    wrapped = django.db.InternalError("cannot execute UPDATE in a read-only transaction")
    wrapped.__cause__ = cause
    return wrapped


class TestIsReadOnlyTransactionError:
    @parameterized.expand(
        [
            ("raw_psycopg", psycopg.errors.ReadOnlySqlTransaction("cannot execute UPDATE in a read-only transaction")),
            ("django_wrapped", _wrapped_read_only_error()),
        ]
    )
    def test_matches_read_only(self, _name: str, error: BaseException) -> None:
        assert is_read_only_transaction_error(error) is True

    @parameterized.expand(
        [
            ("operational", django.db.OperationalError("connection already closed")),
            ("value_error", ValueError("unrelated")),
            ("none", None),
        ]
    )
    def test_ignores_others(self, _name: str, error: BaseException | None) -> None:
        assert is_read_only_transaction_error(error) is False


class TestReadOnlyTransactionEvent:
    @parameterized.expand(
        [
            # Raw psycopg error: a single ReadOnlySqlTransaction entry.
            (
                "raw_psycopg",
                [{"type": "ReadOnlySqlTransaction", "value": "cannot execute UPDATE in a read-only transaction"}],
            ),
            # Django-wrapped error: the SDK chains the psycopg cause, so the wire event carries the
            # InternalError wrapper and the ReadOnlySqlTransaction as separate entries.
            (
                "django_wrapped",
                [
                    {"type": "InternalError", "value": "cannot execute UPDATE in a read-only transaction"},
                    {"type": "ReadOnlySqlTransaction", "value": "cannot execute UPDATE in a read-only transaction"},
                ],
            ),
        ]
    )
    def test_drops_read_only_exception_event(self, _name: str, exception_list: list[dict]) -> None:
        event = {"event": "$exception", "properties": {"$exception_list": exception_list}}
        assert is_read_only_transaction_event(event) is True
        assert drop_read_only_transaction_exceptions(event) is None

    @parameterized.expand(
        [
            (
                "other_exception",
                {"event": "$exception", "properties": {"$exception_list": [{"type": "ValueError", "value": "boom"}]}},
            ),
            # An unrelated exception whose value merely mentions a read-only transaction is kept:
            # detection is by type, not by message text.
            (
                "unrelated_value_mentions_read_only",
                {
                    "event": "$exception",
                    "properties": {
                        "$exception_list": [
                            {"type": "ValueError", "value": "source database is in a read-only transaction"}
                        ]
                    },
                },
            ),
            ("not_an_exception", {"event": "$pageview", "properties": {}}),
        ]
    )
    def test_keeps_other_events(self, _name: str, event: dict) -> None:
        assert is_read_only_transaction_event(event) is False
        assert drop_read_only_transaction_exceptions(event) is event
