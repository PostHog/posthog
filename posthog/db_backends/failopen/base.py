from __future__ import annotations

from django.db import InterfaceError, OperationalError
from django.db.backends.postgresql.base import DatabaseWrapper as PostgresDatabaseWrapper

from posthog.db_circuit_breaker import get_circuit_breaker


class CircuitOpenError(OperationalError):
    """Raised instead of attempting a connection when the breaker is open.

    Subclasses ``OperationalError`` so callers and the ORM treat it like any
    other database connection failure, but it is raised in microseconds rather
    than after the per-database ``connect_timeout``.
    """


class DatabaseWrapper(PostgresDatabaseWrapper):
    """Postgres backend with a fail-fast circuit breaker on the connection path.

    When the breaker for this alias is open, ``ensure_connection`` raises
    immediately instead of waiting on a dead host — freeing the worker to serve
    other requests and stopping a single product-database outage from exhausting
    the shared worker pool. Connection failures feed the breaker so it opens
    after a few failures and probes for recovery on a cooldown.
    """

    def ensure_connection(self) -> None:
        if self.connection is not None:
            return

        breaker = get_circuit_breaker()
        decision = breaker.before_connect(self.alias)
        if not decision.allowed:
            raise CircuitOpenError(f"circuit breaker open for database '{self.alias}'")

        try:
            super().ensure_connection()
        except Exception as exc:
            if isinstance(exc, OperationalError | InterfaceError):
                breaker.record_failure(self.alias, was_probe=decision.is_probe)
            raise
        else:
            breaker.record_success(self.alias, was_probe=decision.is_probe)
