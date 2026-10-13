"""Unit tests for warehouse_sources_queue_partition_management activities."""

from __future__ import annotations

import threading
from contextlib import contextmanager
from datetime import UTC, date, datetime, timedelta
from types import TracebackType
from typing import Any, Literal
from uuid import uuid4

import pytest
import time_machine
from unittest.mock import MagicMock, call, patch

from django.db import connection

import psycopg
from asgiref.sync import sync_to_async
from psycopg.conninfo import make_conninfo

from posthog.temporal.warehouse_sources_queue_partition_management import activities as activities_module
from posthog.temporal.warehouse_sources_queue_partition_management.activities import (
    RETENTION_STRANDED_ERROR,
    _terminalize_stranded_runs,
    manage_warehouse_sources_queue_partitions,
)

# Activity-level integration


class _FakePgConn:
    """Minimal psycopg.Connection stand-in: context manager + .execute returning a cursor.

    ``partitions`` (parent table -> partition names) feeds the pg_inherits
    listing. Executed CREATEs add to it and executed DROPs remove from it, so
    the listing after the run reflects what the activity did. DROPs are also
    recorded in ``dropped``. ``default_rows`` (default partition -> row
    ``created_at`` values) works the same way for DELETEs.
    """

    def __init__(
        self,
        partitions: dict[str, list[str]] | None = None,
        *,
        default_rows: dict[str, list[datetime]] | None = None,
        denied_creates: frozenset[str] = frozenset(),
        denied_drops: frozenset[str] = frozenset(),
        denied_deletes: frozenset[str] = frozenset(),
    ) -> None:
        self.partitions = partitions if partitions is not None else {}
        self.default_rows = default_rows if default_rows is not None else {}
        self.denied_creates = denied_creates
        self.denied_drops = denied_drops
        self.denied_deletes = denied_deletes
        self.dropped: list[str] = []
        self.deleted: list[tuple[str, datetime]] = []
        self.execute_threads: set[int] = set()

    def __enter__(self) -> _FakePgConn:
        return self

    def __exit__(self, *args: Any) -> Literal[False]:
        return False

    def execute(self, sql: Any, params: Any = None) -> MagicMock:
        self.execute_threads.add(threading.get_ident())
        cursor = MagicMock()
        cursor.fetchall.return_value = []
        cursor.rowcount = 0
        if "pg_inherits" in sql and params:
            cursor.fetchall.return_value = [(name,) for name in self.partitions.get(params[0], [])]
        elif sql.startswith("CREATE TABLE IF NOT EXISTS "):
            tokens = sql.split()
            partition_name, table = tokens[5], tokens[8]
            if partition_name in self.denied_creates:
                raise psycopg.errors.InsufficientPrivilege(f"must be owner of table {table}")
            if partition_name not in self.partitions.setdefault(table, []):
                self.partitions[table].append(partition_name)
        elif sql.startswith("DROP TABLE IF EXISTS "):
            partition_name = sql.removeprefix("DROP TABLE IF EXISTS ")
            if partition_name in self.denied_drops:
                raise psycopg.errors.InsufficientPrivilege(f"must be owner of table {partition_name}")
            self.dropped.append(partition_name)
            for names in self.partitions.values():
                if partition_name in names:
                    names.remove(partition_name)
        elif sql.strip().startswith("DELETE FROM "):
            partition_name, created_before = sql.split()[2], params["created_before"]
            if partition_name in self.denied_deletes:
                raise psycopg.errors.InsufficientPrivilege(f"permission denied for table {partition_name}")
            self.deleted.append((partition_name, created_before))
            rows = self.default_rows.get(partition_name, [])
            self.default_rows[partition_name] = [r for r in rows if r >= created_before]
            cursor.rowcount = len(rows) - len(self.default_rows[partition_name])
        elif sql.startswith("SELECT EXISTS "):
            partition_name = sql.split()[5]
            cursor.fetchone.return_value = (any(r < params[0] for r in self.default_rows.get(partition_name, [])),)
        return cursor


@contextmanager
def _patched_pg(partitions: dict[str, list[str]] | None = None):
    conn = _FakePgConn(partitions)
    with patch.object(activities_module.psycopg.Connection, "connect", return_value=conn):
        yield conn


ALERT_TODAY = date(2026, 9, 22)


def _day(offset: int) -> str:
    return (ALERT_TODAY + timedelta(days=offset)).strftime("%Y%m%d")


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("partitions", "default_rows", "denied_creates", "denied_retention", "expected_alert"),
    [
        ({}, {}, {f"sourcebatch_{_day(1)}"}, set(), "`sourcebatch`: 2026-09-23"),
        ({}, {}, {f"sourcebatch_{_day(0)}"}, set(), None),
        ({}, {}, {f"sourcebatch_{_day(6)}"}, set(), None),
        ({"sourcebatch": [f"sourcebatch_{_day(-9)}"]}, {}, set(), {f"sourcebatch_{_day(-9)}"}, "oldest 2026-09-13"),
        ({"sourcebatch": [f"sourcebatch_{_day(-8)}"]}, {}, set(), {f"sourcebatch_{_day(-8)}"}, None),
        (
            {"sourcebatch": ["sourcebatch_default"]},
            {"sourcebatch_default": [datetime(2026, 9, 13, 12, tzinfo=UTC)]},
            set(),
            {"sourcebatch_default"},
            "`sourcebatch_default`: rows created before 2026-09-14",
        ),
        (
            {"sourcebatch": ["sourcebatch_default"]},
            {"sourcebatch_default": [datetime(2026, 9, 14, 12, tzinfo=UTC)]},
            set(),
            {"sourcebatch_default"},
            None,
        ),
    ],
    ids=[
        "tomorrow_missing",
        "only_today_missing",
        "newest_partition_first_failure",
        "drop_overdue_a_day",
        "first_drop_failure",
        "default_rows_overdue_a_day",
        "first_default_expiry_failure",
    ],
)
async def test_activity_posts_to_slack_only_when_someone_must_act(
    activity_environment,
    partitions: dict[str, list[str]],
    default_rows: dict[str, list[datetime]],
    denied_creates: set[str],
    denied_retention: set[str],
    expected_alert: str | None,
) -> None:
    conn = _FakePgConn(
        {table: list(names) for table, names in partitions.items()},
        default_rows={name: list(rows) for name, rows in default_rows.items()},
        denied_creates=frozenset(denied_creates),
        denied_drops=frozenset(denied_retention),
        denied_deletes=frozenset(denied_retention),
    )

    with (
        time_machine.travel("2026-09-22T08:00:00Z", tick=False),
        patch.object(activities_module.psycopg.Connection, "connect", return_value=conn),
        patch.object(activities_module.settings, "WAREHOUSE_SOURCES_QUEUE_PARTITION_DATABASE_URL", ""),
        patch.object(
            activities_module.settings, "WAREHOUSE_SOURCES_QUEUE_PARTITION_SLACK_WEBHOOK_URL", "https://hooks/x"
        ),
        patch.object(activities_module.requests, "post") as post,
        patch.object(activities_module, "_terminalize_stranded_runs"),
    ):
        result = await activity_environment.run(manage_warehouse_sources_queue_partitions)

    assert result["success"] is False
    if expected_alert is None:
        post.assert_not_called()
    else:
        post.assert_called_once()
        assert expected_alert in str(post.call_args.kwargs["json"])


# Terminalizing stranded runs before partition drops


class _StrandedQueryConn:
    """Stand-in for the queue-DB connection inside _terminalize_stranded_runs."""

    def __init__(self, rows: list[tuple[Any, ...]]) -> None:
        self.rows = rows

    def execute(self, _sql: Any, _params: Any = None) -> MagicMock:
        cursor = MagicMock()
        cursor.fetchall.return_value = self.rows
        return cursor


@contextmanager
def _patched_terminalize_collaborators():
    with (
        # These tests run without the django_db mark, but close_old_connections probes any
        # connection a neighboring test left initialized, tripping pytest-django's DB blocker.
        patch("django.db.close_old_connections"),
        patch("products.warehouse_sources.backend.facade.pipelines.BatchQueue") as batch_queue,
        patch("products.warehouse_sources.backend.facade.pipelines.mark_job_failed_if_not_terminal") as mark_failed,
        patch("products.warehouse_sources.backend.facade.pipelines.release_v3_pipeline_lock") as release_lock,
    ):
        batch_queue.fail_batches_for_job_sync.return_value = 2
        yield batch_queue, mark_failed, release_lock


def test_terminalize_fails_each_stranded_run_and_releases_its_lock() -> None:
    conn = _StrandedQueryConn(
        [
            ("run-1", 1, "schema-a", "job-1", "wf-run-1", 3),
            ("run-2", 2, "schema-b", "job-2", None, 1),
        ]
    )

    with _patched_terminalize_collaborators() as (batch_queue, mark_failed, release_lock):
        _terminalize_stranded_runs(conn, "sourcebatch_20000101")  # type: ignore[arg-type]

    assert batch_queue.fail_batches_for_job_sync.call_args_list == [
        call(conn, job_id="job-1", reason=RETENTION_STRANDED_ERROR),
        call(conn, job_id="job-2", reason=RETENTION_STRANDED_ERROR),
    ]
    assert mark_failed.call_args_list == [
        call(job_id="job-1", team_id=1, error=RETENTION_STRANDED_ERROR),
        call(job_id="job-2", team_id=2, error=RETENTION_STRANDED_ERROR),
    ]
    # Only run-1 recorded a workflow_run_id; releasing without the holder's token must not happen.
    release_lock.assert_called_once_with(1, "schema-a", "wf-run-1")


def test_terminalize_keeps_batches_non_terminal_when_job_fail_write_errors() -> None:
    # The queue-batch fail must come last: it flips the very state the sweep uses
    # to rediscover a stranded run, so committing it before a failed app-DB write
    # would make tomorrow's retry see an all-terminal partition and drop the
    # evidence with the job still RUNNING.
    conn = _StrandedQueryConn([("run-1", 1, "schema-a", "job-1", "wf-run-1", 3)])

    with _patched_terminalize_collaborators() as (batch_queue, mark_failed, _release_lock):
        mark_failed.side_effect = RuntimeError("app db unavailable")
        with pytest.raises(RuntimeError, match="app db unavailable"):
            _terminalize_stranded_runs(conn, "sourcebatch_20000101")  # type: ignore[arg-type]

    batch_queue.fail_batches_for_job_sync.assert_not_called()


def test_terminalize_makes_no_writes_for_all_terminal_partition() -> None:
    with _patched_terminalize_collaborators() as (batch_queue, mark_failed, release_lock):
        _terminalize_stranded_runs(_StrandedQueryConn([]), "sourcebatch_20000101")  # type: ignore[arg-type]

    batch_queue.fail_batches_for_job_sync.assert_not_called()
    mark_failed.assert_not_called()
    release_lock.assert_not_called()


OLD_BATCH_PART = "sourcebatch_20000101"
OLD_BATCH_PART_2 = "sourcebatch_20000102"
OLD_STATUS_PART = "sourcebatchstatus_20000101"


@pytest.mark.asyncio
async def test_activity_terminalizes_only_sourcebatch_partitions_then_drops(activity_environment) -> None:
    partitions = {"sourcebatch": [OLD_BATCH_PART], "sourcebatchstatus": [OLD_STATUS_PART]}

    with (
        _patched_pg(partitions) as conn,
        patch.object(activities_module, "_terminalize_stranded_runs") as terminalize,
    ):
        result = await activity_environment.run(manage_warehouse_sources_queue_partitions)

    # Status partitions carry no run state, so only the sourcebatch partition terminalizes.
    terminalize.assert_called_once_with(conn, OLD_BATCH_PART)
    assert OLD_BATCH_PART in result["dropped"]
    assert OLD_STATUS_PART in result["dropped"]
    assert result["success"] is True


@pytest.mark.asyncio
async def test_activity_runs_queue_database_statements_on_a_pool_thread(activity_environment) -> None:
    shared_thread_sensitive_ident = await sync_to_async(threading.get_ident)()

    with (
        _patched_pg({"sourcebatch": [OLD_BATCH_PART]}) as conn,
        patch.object(activities_module, "_terminalize_stranded_runs"),
    ):
        await activity_environment.run(manage_warehouse_sources_queue_partitions)

    assert conn.dropped == [OLD_BATCH_PART]
    assert conn.execute_threads.isdisjoint({threading.get_ident(), shared_thread_sensitive_ident})


@pytest.mark.asyncio
async def test_activity_keeps_partition_when_terminalization_fails(activity_environment) -> None:
    partitions = {
        "sourcebatch": [OLD_BATCH_PART, OLD_BATCH_PART_2],
        "sourcebatchstatus": [OLD_STATUS_PART],
    }

    def _boom(_conn: Any, partition_name: str) -> None:
        if partition_name == OLD_BATCH_PART:
            raise RuntimeError("app-db unavailable")

    with (
        _patched_pg(partitions) as conn,
        patch.object(activities_module, "_terminalize_stranded_runs", side_effect=_boom),
    ):
        result = await activity_environment.run(manage_warehouse_sources_queue_partitions)

    # The failed partition is preserved as evidence (no DROP even attempted); everything else proceeds.
    assert OLD_BATCH_PART not in conn.dropped
    assert OLD_BATCH_PART_2 in result["dropped"]
    assert OLD_STATUS_PART in result["dropped"]
    assert result["success"] is False
    assert any(OLD_BATCH_PART in e for e in result["errors"])


PARTITION_ROLE_URL = "postgres://migrator@db.example.com/queue"
WORKER_ROLE_URL = "postgres://worker@db.example.com/queue"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("partition_url", "expected_urls", "expect_dropped"),
    [
        (PARTITION_ROLE_URL, [PARTITION_ROLE_URL, WORKER_ROLE_URL], True),
        ("", [WORKER_ROLE_URL], False),
    ],
)
async def test_activity_uses_partition_role_and_drops_worker_owned_partitions_as_worker(
    activity_environment, partition_url: str, expected_urls: list[str], expect_dropped: bool
) -> None:
    ddl_conn = _FakePgConn({"sourcebatchstatus": [OLD_STATUS_PART]}, denied_drops=frozenset({OLD_STATUS_PART}))
    owner_conn = _FakePgConn(ddl_conn.partitions)

    with (
        patch.object(activities_module.settings, "WAREHOUSE_SOURCES_QUEUE_PARTITION_DATABASE_URL", partition_url),
        patch.object(activities_module.settings, "WAREHOUSE_SOURCES_DATABASE_URL", WORKER_ROLE_URL),
        patch.object(activities_module.psycopg.Connection, "connect", side_effect=[ddl_conn, owner_conn]) as connect,
    ):
        result = await activity_environment.run(manage_warehouse_sources_queue_partitions)

    assert [c.args[0] for c in connect.call_args_list] == expected_urls
    assert (OLD_STATUS_PART in result["dropped"]) is expect_dropped
    assert owner_conn.dropped == ([OLD_STATUS_PART] if expect_dropped else [])
    assert result["success"] is expect_dropped


@pytest.mark.asyncio
async def test_activity_expires_old_default_partition_rows_instead_of_dropping(activity_environment) -> None:
    partitions = {"sourcebatch": ["sourcebatch_default"], "sourcebatchstatus": ["sourcebatchstatus_default"]}
    cutoff = datetime(2026, 9, 15, tzinfo=UTC)

    with (
        time_machine.travel("2026-09-22T12:00:00Z", tick=False),
        _patched_pg(partitions) as conn,
        patch.object(activities_module, "_terminalize_stranded_runs") as terminalize,
    ):
        result = await activity_environment.run(manage_warehouse_sources_queue_partitions)

    terminalize.assert_called_once_with(conn, "sourcebatch_default", created_before=cutoff)
    assert conn.deleted == [("sourcebatch_default", cutoff), ("sourcebatchstatus_default", cutoff)]
    assert conn.dropped == []
    assert result["success"] is True


def _test_database_conninfo() -> str:
    settings_dict = connection.settings_dict
    params = {
        "host": settings_dict["HOST"],
        "port": str(settings_dict["PORT"] or ""),
        "user": settings_dict["USER"],
        "password": settings_dict["PASSWORD"],
        "dbname": settings_dict["NAME"],
    }
    return make_conninfo(**{key: value for key, value in params.items() if value})


@pytest.mark.django_db
def test_expire_default_partition_rows_deletes_only_rows_older_than_cutoff_in_batches() -> None:
    table = f"expiry_test_{uuid4().hex[:12]}"
    cutoff = date(2026, 9, 15)
    errors: list[str] = []

    with psycopg.Connection.connect(_test_database_conninfo(), autocommit=True) as conn:
        try:
            conn.execute(f"CREATE TABLE {table} (id int, created_at timestamptz) PARTITION BY RANGE (created_at)")
            conn.execute(f"CREATE TABLE {table}_default PARTITION OF {table} DEFAULT")
            conn.execute(
                f"""
                INSERT INTO {table}
                SELECT g, timestamptz '2026-09-14 23:59:59+00' - g * interval '1 hour' FROM generate_series(1, 5) g
                UNION ALL
                SELECT 100 + g, timestamptz '2026-09-15 00:00:00+00' + g * interval '1 hour' FROM generate_series(0, 1) g
                """
            )

            with patch.object(activities_module, "DEFAULT_PARTITION_DELETE_BATCH_SIZE", 2):
                activities_module._expire_default_partition_rows(conn, table, f"{table}_default", cutoff, errors)

            remaining = [row[0] for row in conn.execute(f"SELECT id FROM {table} ORDER BY id").fetchall()]
        finally:
            conn.execute(f"DROP TABLE IF EXISTS {table}")

    assert errors == []
    assert remaining == [100, 101]


def _connect_refused(*args: Any, **kwargs: Any) -> None:
    del args, kwargs
    raise psycopg.OperationalError("connection refused")


def _frames_holding(tb: TracebackType | None, needle: str) -> list[str]:
    hits: list[str] = []
    while tb is not None:
        if needle in repr(tb.tb_frame.f_locals):
            hits.append(tb.tb_frame.f_code.co_qualname)
        tb = tb.tb_next
    return hits


_SECRET = "invented-secret"


@pytest.mark.asyncio
async def test_connect_failure_keeps_database_url_out_of_traceback_locals() -> None:
    with (
        patch.object(
            activities_module.settings,
            "WAREHOUSE_SOURCES_DATABASE_URL",
            f"postgres://alice:{_SECRET}@db.example.com/app",
        ),
        patch.object(activities_module.psycopg.Connection, "connect", _connect_refused),
        pytest.raises(psycopg.OperationalError) as exc_info,
    ):
        await manage_warehouse_sources_queue_partitions()

    hits = _frames_holding(exc_info.value.__traceback__, _SECRET)
    assert hits == []


@pytest.mark.django_db
@pytest.mark.parametrize(
    "existing_options, expect_alter",
    [
        ("", True),
        ("autovacuum_vacuum_scale_factor = 0.02, autovacuum_analyze_scale_factor = 0.02", True),
        (", ".join(activities_module._PARTITION_AUTOVACUUM_OPTIONS), False),
    ],
)
def test_tune_partition_autovacuum_sets_options_once(existing_options: str, expect_alter: bool) -> None:
    table = f"autovacuum_test_{uuid4().hex[:12]}"
    partition = f"{table}_20261002"
    errors: list[str] = []

    with psycopg.Connection.connect(_test_database_conninfo(), autocommit=True) as conn:
        try:
            conn.execute(f"CREATE TABLE {table} (id int, created_at timestamptz) PARTITION BY RANGE (created_at)")
            conn.execute(
                f"CREATE TABLE {partition} PARTITION OF {table} FOR VALUES FROM ('2026-10-02') TO ('2026-10-03')"
            )
            if existing_options:
                conn.execute(f"ALTER TABLE {partition} SET ({existing_options})")

            statements: list[str] = []
            real_execute = conn.execute

            def recording_execute(query: Any, *args: Any, **kwargs: Any) -> Any:
                statements.append(str(query))
                return real_execute(query, *args, **kwargs)

            with patch.object(conn, "execute", side_effect=recording_execute):
                activities_module._tune_partition_autovacuum(conn, partition, errors)

            row = conn.execute("SELECT reloptions FROM pg_class WHERE oid = %s::regclass", [partition]).fetchone()
            assert row is not None
            options = row[0]
        finally:
            conn.execute(f"DROP TABLE IF EXISTS {table}")

    assert errors == []
    assert set(options) >= set(activities_module._PARTITION_AUTOVACUUM_OPTIONS)
    assert any(statement.startswith("ALTER TABLE") for statement in statements) is expect_alter
