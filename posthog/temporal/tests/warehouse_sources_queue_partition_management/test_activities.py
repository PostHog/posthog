"""Unit tests for warehouse_sources_queue_partition_management activities."""

from __future__ import annotations

from contextlib import contextmanager
from datetime import date
from typing import Any, Literal

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

import psycopg

from posthog.temporal.warehouse_sources_queue_partition_management import activities as activities_module
from posthog.temporal.warehouse_sources_queue_partition_management.activities import (
    _cleanup_old_s3_extractions,
    manage_warehouse_sources_queue_partitions,
)

TODAY = date(2026, 5, 22)
BUCKET = "data-warehouse"
BASE = f"{BUCKET}/data_pipelines_extract"


def _build_s3_mock(
    entries: list[str],
    *,
    ls_raises: Exception | None = None,
    delete_raises: dict[str, Exception] | None = None,
) -> MagicMock:
    s3 = MagicMock()
    if ls_raises is not None:
        s3.ls.side_effect = ls_raises
    else:
        s3.ls.return_value = entries

    if delete_raises:

        def _delete(path: str, recursive: bool) -> None:
            if path in delete_raises:
                raise delete_raises[path]

        s3.delete.side_effect = _delete
    return s3


@contextmanager
def _patched_s3(
    entries: list[str],
    *,
    ls_raises: Exception | None = None,
    delete_raises: dict[str, Exception] | None = None,
    bucket: str = BUCKET,
):
    s3 = _build_s3_mock(entries, ls_raises=ls_raises, delete_raises=delete_raises)
    with (
        patch("products.data_warehouse.backend.s3.get_s3_client", return_value=s3),
        patch.object(activities_module.settings, "DATAWAREHOUSE_BUCKET", bucket),
    ):
        yield s3


# Cutoff arithmetic


@pytest.mark.parametrize(
    ("partition_date", "should_delete", "note"),
    [
        (date(2026, 5, 15), False, "exactly at cutoff -> keep (guards against `<=` flip)"),
        (date(2026, 5, 14), True, "one day before cutoff -> delete"),
        (date(2026, 5, 16), False, "one day after cutoff -> keep"),
        (date(2026, 5, 22), False, "today -> keep"),
        (date(2026, 6, 1), False, "future-dated -> keep (defense against clock skew)"),
        (date(2020, 1, 1), True, "far old -> delete"),
    ],
)
def test_cutoff_boundaries(partition_date: date, should_delete: bool, note: str) -> None:
    name = f"dt={partition_date.isoformat()}"
    entries = [f"{BASE}/{name}"]
    errors: list[str] = []

    with _patched_s3(entries) as s3:
        deleted = _cleanup_old_s3_extractions(TODAY, errors)

    assert errors == []
    if should_delete:
        assert deleted == [name]
        s3.delete.assert_called_once_with(entries[0], recursive=True)
    else:
        assert deleted == []
        s3.delete.assert_not_called()


# Name parsing / filtering safety


def test_skips_entries_without_dt_prefix() -> None:
    entries = [
        f"{BASE}/README.md",
        f"{BASE}/_temp",
        f"{BASE}/year=2024",
        f"{BASE}/dt=2020-01-01",
    ]
    errors: list[str] = []

    with _patched_s3(entries) as s3:
        deleted = _cleanup_old_s3_extractions(TODAY, errors)

    assert deleted == ["dt=2020-01-01"]
    assert errors == []
    s3.delete.assert_called_once_with(f"{BASE}/dt=2020-01-01", recursive=True)


@pytest.mark.parametrize(
    "bad_entry",
    [
        "dt=invalid",
        "dt=2026-13-40",
        "dt=",
        "dt=2026/05/15",
        "dt=2020-01-01-extra",
    ],
)
def test_skips_dt_entries_with_unparseable_date(bad_entry: str) -> None:
    entries = [f"{BASE}/{bad_entry}"]
    errors: list[str] = []

    with _patched_s3(entries) as s3:
        deleted = _cleanup_old_s3_extractions(TODAY, errors)

    assert deleted == []
    assert errors == []
    s3.delete.assert_not_called()


def test_handles_entries_with_and_without_trailing_slash() -> None:
    entries = [
        f"{BASE}/dt=2020-01-01/",
        f"{BASE}/dt=2020-02-02",
    ]
    errors: list[str] = []

    with _patched_s3(entries) as s3:
        deleted = _cleanup_old_s3_extractions(TODAY, errors)

    assert set(deleted) == {"dt=2020-01-01", "dt=2020-02-02"}
    assert errors == []
    assert s3.delete.call_count == 2
    s3.delete.assert_any_call(f"{BASE}/dt=2020-01-01/", recursive=True)
    s3.delete.assert_any_call(f"{BASE}/dt=2020-02-02", recursive=True)


def test_uses_basename_for_date_parsing_not_full_path() -> None:
    entries = ["s3://other-bucket/data_pipelines_extract/dt=2020-01-01/"]
    errors: list[str] = []

    with _patched_s3(entries) as s3:
        deleted = _cleanup_old_s3_extractions(TODAY, errors)

    assert deleted == ["dt=2020-01-01"]
    assert errors == []
    s3.delete.assert_called_once_with(entries[0], recursive=True)


# S3 listing edges


def test_returns_empty_when_prefix_does_not_exist() -> None:
    errors: list[str] = []

    with _patched_s3([], ls_raises=FileNotFoundError()) as s3:
        deleted = _cleanup_old_s3_extractions(TODAY, errors)

    assert deleted == []
    assert errors == []
    s3.delete.assert_not_called()


def test_returns_empty_when_prefix_has_no_entries() -> None:
    errors: list[str] = []

    with _patched_s3([]) as s3:
        deleted = _cleanup_old_s3_extractions(TODAY, errors)

    assert deleted == []
    assert errors == []
    s3.delete.assert_not_called()


def test_returns_empty_when_no_entries_old_enough() -> None:
    entries = [
        f"{BASE}/dt=2026-05-20",
        f"{BASE}/dt=2026-05-21",
        f"{BASE}/dt=2026-05-22",
    ]
    errors: list[str] = []

    with _patched_s3(entries) as s3:
        deleted = _cleanup_old_s3_extractions(TODAY, errors)

    assert deleted == []
    assert errors == []
    s3.delete.assert_not_called()


# Per-entry failure isolation


def test_continues_after_individual_delete_failure() -> None:
    entries = [
        f"{BASE}/dt=2020-01-01",
        f"{BASE}/dt=2020-01-02",
        f"{BASE}/dt=2020-01-03",
    ]
    errors: list[str] = []

    with _patched_s3(entries, delete_raises={f"{BASE}/dt=2020-01-02": OSError("boom")}) as s3:
        deleted = _cleanup_old_s3_extractions(TODAY, errors)

    assert set(deleted) == {"dt=2020-01-01", "dt=2020-01-03"}
    assert errors == ["Failed to delete S3 partition dt=2020-01-02: boom"]
    assert s3.delete.call_count == 3


def test_appends_error_for_each_failed_delete() -> None:
    entries = [
        f"{BASE}/dt=2020-01-01",
        f"{BASE}/dt=2020-01-02",
    ]
    errors: list[str] = []
    delete_raises: dict[str, Exception] = {
        f"{BASE}/dt=2020-01-01": OSError("first"),
        f"{BASE}/dt=2020-01-02": OSError("second"),
    }

    with _patched_s3(entries, delete_raises=delete_raises):
        deleted = _cleanup_old_s3_extractions(TODAY, errors)

    assert deleted == []
    assert errors == [
        "Failed to delete S3 partition dt=2020-01-01: first",
        "Failed to delete S3 partition dt=2020-01-02: second",
    ]


def test_failure_does_not_mark_unrelated_skipped_entries() -> None:
    entries = [
        f"{BASE}/dt=2020-01-01",
        f"{BASE}/dt=2026-05-22",
        f"{BASE}/not-a-partition",
        f"{BASE}/dt=invalid",
    ]
    errors: list[str] = []

    with _patched_s3(entries, delete_raises={f"{BASE}/dt=2020-01-01": OSError("x")}) as s3:
        deleted = _cleanup_old_s3_extractions(TODAY, errors)

    assert deleted == []
    assert errors == ["Failed to delete S3 partition dt=2020-01-01: x"]
    s3.delete.assert_called_once_with(f"{BASE}/dt=2020-01-01", recursive=True)


# Call shape


def test_calls_delete_with_recursive_true() -> None:
    entries = [f"{BASE}/dt=2020-01-01"]
    errors: list[str] = []

    with _patched_s3(entries) as s3:
        _cleanup_old_s3_extractions(TODAY, errors)

    # without recursive=True we'd leak every parquet file under the prefix
    _, kwargs = s3.delete.call_args
    assert kwargs == {"recursive": True}


def test_uses_full_entry_path_when_deleting() -> None:
    full_path = "s3://some-bucket/data_pipelines_extract/dt=2020-01-01"
    entries = [full_path]
    errors: list[str] = []

    with _patched_s3(entries) as s3:
        _cleanup_old_s3_extractions(TODAY, errors)

    s3.delete.assert_called_once_with(full_path, recursive=True)


def test_uses_configured_bucket_prefix() -> None:
    errors: list[str] = []

    with _patched_s3([], bucket="my-special-bucket") as s3:
        _cleanup_old_s3_extractions(TODAY, errors)

    s3.ls.assert_called_once_with("my-special-bucket/data_pipelines_extract")


# Activity-level integration


class _FakePgConn:
    """Minimal psycopg.Connection stand-in: context manager + .execute returning a cursor."""

    def __enter__(self) -> _FakePgConn:
        return self

    def __exit__(self, *args: Any) -> Literal[False]:
        return False

    def execute(self, _sql: Any, _params: Any = None) -> MagicMock:
        cursor = MagicMock()
        cursor.fetchall.return_value = []
        return cursor


@contextmanager
def _patched_pg():
    # _verify_partitions is stubbed because the fake connection returns no rows, which would
    # otherwise flood `errors` with bogus "partition missing" messages — orthogonal to the
    # S3-cleanup wiring these integration tests cover.
    with (
        patch.object(activities_module.psycopg.Connection, "connect", return_value=_FakePgConn()) as connect,
        patch.object(activities_module, "_verify_partitions"),
    ):
        yield connect


@pytest.mark.asyncio
async def test_activity_result_includes_s3_deleted(activity_environment) -> None:
    # Use a date guaranteed to be older than 7 days from real `date.today()` so we don't have
    # to patch the date module — the cutoff math itself is exhaustively tested above.
    entries = [f"{BASE}/dt=2000-01-01"]

    with _patched_pg(), _patched_s3(entries):
        result = await activity_environment.run(manage_warehouse_sources_queue_partitions)

    assert result["s3_deleted"] == ["dt=2000-01-01"]
    assert result["errors"] == []
    assert result["success"] is True


@pytest.mark.asyncio
async def test_activity_s3_failure_marks_success_false_and_triggers_slack(activity_environment) -> None:
    entries = [f"{BASE}/dt=2000-01-01"]
    delete_raises: dict[str, Exception] = {f"{BASE}/dt=2000-01-01": OSError("kaboom")}

    with (
        _patched_pg(),
        _patched_s3(entries, delete_raises=delete_raises),
        patch.object(
            activities_module.settings, "WAREHOUSE_SOURCES_QUEUE_PARTITION_SLACK_WEBHOOK_URL", "https://hooks/x"
        ),
        patch.object(activities_module.requests, "post") as post,
    ):
        post.return_value.raise_for_status = MagicMock()
        result = await activity_environment.run(manage_warehouse_sources_queue_partitions)

    assert result["success"] is False
    assert result["errors"] == ["Failed to delete S3 partition dt=2000-01-01: kaboom"]
    assert result["s3_deleted"] == []
    post.assert_called_once()


@pytest.mark.asyncio
async def test_activity_logs_s3_deleted_count(activity_environment) -> None:
    entries = [
        f"{BASE}/dt=2000-01-01",
        f"{BASE}/dt=2000-01-02",
    ]

    with (
        _patched_pg(),
        _patched_s3(entries),
        patch.object(activities_module.logger, "info") as log_info,
    ):
        await activity_environment.run(manage_warehouse_sources_queue_partitions)

    completion_calls = [
        call for call in log_info.call_args_list if call.args and call.args[0] == "Partition management completed"
    ]
    assert len(completion_calls) == 1
    assert completion_calls[0].kwargs["s3_deleted_count"] == 2


# DDL lock retry


class _LockFlakyConn:
    def __init__(self, failures: int, error: type[Exception]) -> None:
        self.failures = failures
        self.error = error
        self.calls = 0

    def execute(self, _sql: Any, _params: Any = None) -> MagicMock:
        self.calls += 1
        if self.calls <= self.failures:
            raise self.error()
        return MagicMock()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("failures", "error", "expected_calls", "raises"),
    [
        # transient lock timeouts retry until the DDL goes through
        (2, psycopg.errors.LockNotAvailable, 3, None),
        # persistent lock timeouts give up after the attempt cap instead of retrying forever
        (
            99,
            psycopg.errors.LockNotAvailable,
            activities_module.DDL_LOCK_MAX_ATTEMPTS,
            psycopg.errors.LockNotAvailable,
        ),
        # non-lock errors surface immediately — retrying would mask real failures
        (99, psycopg.errors.UndefinedTable, 1, psycopg.errors.UndefinedTable),
    ],
)
async def test_ddl_lock_retry(
    failures: int, error: type[Exception], expected_calls: int, raises: type[Exception] | None
) -> None:
    conn = _LockFlakyConn(failures, error)
    with patch("asyncio.sleep", new=AsyncMock()):
        if raises is None:
            await activities_module._execute_ddl_with_lock_retry(conn, "DROP TABLE IF EXISTS sourcebatch_20260101")  # type: ignore[arg-type]
        else:
            with pytest.raises(raises):
                await activities_module._execute_ddl_with_lock_retry(
                    conn,  # type: ignore[arg-type]
                    "DROP TABLE IF EXISTS sourcebatch_20260101",
                )
    assert conn.calls == expected_calls
