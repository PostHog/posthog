"""Paced, vacuumed batch deletion for one work unit at a time."""

import time
from collections.abc import Callable
from typing import Any, Protocol

from django.conf import settings
from django.db import connection, transaction
from django.db.utils import DatabaseError

import psycopg2
import structlog

from posthog.clickhouse.custom_metrics import MetricsClient
from posthog.dataclasses import frozen

from . import sql
from .config import EventPropertyCleanupConfig
from .units import WorkUnit

logger = structlog.get_logger(__name__)

# serialization_failure, deadlock_detected, lock_not_available (lock_timeout), query_canceled (statement_timeout)
RETRYABLE_SQLSTATES = frozenset({"40001", "40P01", "55P03", "57014"})
MAX_RETRY_ATTEMPTS = 5
RETRY_BACKOFF_SECONDS = 1.0


@frozen
class HealthProbe:
    dead_tuple_ratio: float
    blocked_propdefs_backends: int


@frozen
class UnitResult:
    mode: str
    team_id: int
    label: str
    est_rows: int
    rows_deleted: int
    batches: int
    pauses: int
    vacuums: int
    seconds: float
    # Rows this unit deleted after its last VACUUM (all of them when it never vacuumed), so the
    # collect step can decide whether a final VACUUM is due.
    rows_since_vacuum: int
    # Set when the unit stopped before it was exhausted (max_rows, max_runtime).
    stopped_reason: str | None


class DeleteBackend(Protocol):
    """The three database interactions the engine needs. Tests provide a fake."""

    def delete_batch(
        self, statement: str, params: dict[str, Any], lock_timeout: str, statement_timeout: str
    ) -> int: ...

    def probe_health(self) -> HealthProbe: ...

    def vacuum(self, cost_delay_ms: int, cost_limit: int) -> list[str]: ...


class DjangoPostgresBackend:
    """Runs against the Django default connection (the cloud primary in Dagster)."""

    def delete_batch(self, statement: str, params: dict[str, Any], lock_timeout: str, statement_timeout: str) -> int:
        with transaction.atomic(), connection.cursor() as cursor:
            cursor.execute("SET LOCAL lock_timeout = %s", (lock_timeout,))
            cursor.execute("SET LOCAL statement_timeout = %s", (statement_timeout,))
            cursor.execute(statement, params)
            return int(cursor.rowcount)

    def probe_health(self) -> HealthProbe:
        with connection.cursor() as cursor:
            cursor.execute(sql.HEALTH_TABLE_STATS)
            row = cursor.fetchone()
            live, dead = (row[0], row[1]) if row else (0, 0)
            cursor.execute(sql.HEALTH_BLOCKED_PROPDEFS)
            blocked = int(cursor.fetchone()[0])
        ratio = float(dead) / float(live) if live else 0.0
        return HealthProbe(dead_tuple_ratio=ratio, blocked_propdefs_backends=blocked)

    def vacuum(self, cost_delay_ms: int, cost_limit: int) -> list[str]:
        # VACUUM cannot run inside a transaction, so it needs its own autocommit connection.
        db = settings.DATABASES["default"]
        conn = psycopg2.connect(
            host=db["HOST"],
            port=int(db["PORT"] or 5432),
            dbname=db["NAME"],
            user=db["USER"],
            password=db["PASSWORD"],
        )
        try:
            conn.autocommit = True
            with conn.cursor() as cursor:
                cursor.execute("SET vacuum_cost_delay = %s", (f"{cost_delay_ms}ms",))
                cursor.execute("SET vacuum_cost_limit = %s", (cost_limit,))
                cursor.execute(sql.VACUUM)
            return [str(n).strip() for n in conn.notices]
        finally:
            conn.close()


def sqlstate_of(exc: BaseException) -> str | None:
    cause = exc.__cause__ if isinstance(exc, DatabaseError) and exc.__cause__ else exc
    return getattr(cause, "pgcode", None) or getattr(cause, "sqlstate", None)


def delete_statement(unit: WorkUnit, batch_size: int, retention_days: int | None) -> tuple[str, dict[str, Any]]:
    if unit.mode == "pollution":
        return sql.POLLUTION_DELETE, {
            "team_id": unit.team_id,
            "project_id": unit.project_id,
            "property": unit.key,
            "batch": batch_size,
        }
    if unit.mode == "retention":
        if retention_days is None:
            raise ValueError("retention unit without retention_days")
        return sql.RETENTION_DELETE, {
            "project_id": unit.project_id,
            "names": list(unit.key),
            "days": retention_days,
            "batch": batch_size,
        }
    if unit.mode == "dormant":
        return sql.DORMANT_DELETE, {"team_id": unit.team_id, "batch": batch_size}
    raise ValueError(f"unknown mode {unit.mode}")


class DeleteEngine:
    """Deletes one unit in batches, pausing on database pressure and vacuuming on a row budget."""

    def __init__(
        self,
        config: EventPropertyCleanupConfig,
        backend: DeleteBackend,
        *,
        metrics: MetricsClient | None = None,
        metric_labels: dict[str, str] | None = None,
        sleep: Callable[[float], None] = time.sleep,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.config = config
        self.backend = backend
        self.metrics = metrics
        self.metric_labels = metric_labels or {}
        self.sleep = sleep
        self.clock = clock
        self.started_at = clock()
        self.rows_deleted_total = 0
        self.rows_since_vacuum = 0
        self.vacuums = 0
        self._last_probe_at: float | None = None
        self._last_probe: HealthProbe | None = None

    def run_unit(self, unit: WorkUnit) -> UnitResult:
        started = self.clock()
        statement, params = delete_statement(unit, self.config.batch_size, self.config.retention_days)
        rows_deleted = batches = pauses = vacuums = rows_since_vacuum = 0
        stopped_reason: str | None = None
        retries = 0
        force_pause = False

        while True:
            stopped_reason = self._limit_reached()
            if stopped_reason:
                break
            pauses += self._pause_while_unhealthy(force_pause)
            force_pause = False
            try:
                deleted = self.backend.delete_batch(
                    statement, params, self.config.lock_timeout, self.config.statement_timeout
                )
            except DatabaseError as exc:
                code = sqlstate_of(exc)
                if code in RETRYABLE_SQLSTATES and retries < MAX_RETRY_ATTEMPTS:
                    retries += 1
                    force_pause = True
                    self._count("eventproperty_cleanup_retries", {"sqlstate": code or "unknown"})
                    self.sleep(RETRY_BACKOFF_SECONDS)
                    continue
                raise
            retries = 0
            batches += 1
            rows_deleted += deleted
            self.rows_deleted_total += deleted
            self.rows_since_vacuum += deleted
            rows_since_vacuum += deleted
            self._count("eventproperty_cleanup_rows_deleted", value=float(deleted))
            if self.config.vacuum and self.rows_since_vacuum >= self.config.rows_between_vacuum:
                self.vacuum()
                vacuums += 1
                rows_since_vacuum = 0
            if deleted < self.config.batch_size:
                break
            if self.config.sleep_seconds:
                self.sleep(self.config.sleep_seconds)

        return UnitResult(
            mode=unit.mode,
            team_id=unit.team_id,
            label=unit.label,
            est_rows=unit.est_rows,
            rows_deleted=rows_deleted,
            batches=batches,
            pauses=pauses,
            vacuums=vacuums,
            seconds=self.clock() - started,
            rows_since_vacuum=rows_since_vacuum,
            stopped_reason=stopped_reason,
        )

    def vacuum(self) -> list[str]:
        notices = self.backend.vacuum(self.config.vacuum_cost_delay_ms, self.config.vacuum_cost_limit)
        self.rows_since_vacuum = 0
        self.vacuums += 1
        self._count("eventproperty_cleanup_vacuums")
        logger.info("eventproperty_cleanup.vacuum", notices=notices[-12:])
        return notices

    def _limit_reached(self) -> str | None:
        if self.config.max_rows is not None and self.rows_deleted_total >= self.config.max_rows:
            return "max_rows"
        if self.config.max_runtime_minutes is not None:
            if self.clock() - self.started_at >= self.config.max_runtime_minutes * 60:
                return "max_runtime"
        return None

    def _pause_while_unhealthy(self, force: bool) -> int:
        pauses = 0
        while True:
            probe = self._probe(refresh=force or pauses > 0)
            unhealthy = (
                force
                or probe.dead_tuple_ratio > self.config.pause_dead_tuple_ratio
                or probe.blocked_propdefs_backends >= self.config.pause_propdefs_blocked_backends
            )
            if not unhealthy:
                return pauses
            reason = "retry" if force else "health"
            force = False
            pauses += 1
            self._count("eventproperty_cleanup_pauses", {"reason": reason})
            logger.info("eventproperty_cleanup.pause", reason=reason, probe=probe)
            self.sleep(self.config.pause_seconds)

    def _probe(self, refresh: bool) -> HealthProbe:
        now = self.clock()
        stale = (
            self._last_probe is None
            or self._last_probe_at is None
            or now - self._last_probe_at >= self.config.health_probe_interval_seconds
        )
        if refresh or stale:
            self._last_probe = self.backend.probe_health()
            self._last_probe_at = now
        assert self._last_probe is not None
        return self._last_probe

    def _count(self, name: str, labels: dict[str, str] | None = None, value: float = 1.0) -> None:
        if self.metrics is None:
            return
        try:
            self.metrics.increment(name, labels={**self.metric_labels, **(labels or {})}, value=value).result()
        except Exception:
            logger.warning("eventproperty_cleanup.metric_failed", metric=name)
