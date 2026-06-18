# Warehouse Sync Status — Backend Implementation Plan (Tier 2: capture + query)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Back the warehouse Overview tab's freshness UI with a real, backend-neutral data source that reads the Dagster event backfill **via PostHog capture events** (no new table, no migration), and can be swapped to viaduck CDC by flipping one setting — with no API or frontend change.

**Architecture:** The `events_ducklake_backfill` Dagster asset emits one PostHog event per partition run (`success`/`failed`) via `ph_scoped_capture`. Those events land in PostHog's internal Cloud project. A backend-neutral `WarehouseSyncStatus` contract is produced by a `WarehouseSyncStatusProvider` chosen by a factory from a setting. The `DagsterBackfillStatusProvider` reads the internal project's `events` table in ClickHouse (the same cluster the product API already uses — no duckgres queries) and aggregates the latest event per partition into the DTO. A `ViaduckSyncStatusProvider` is staged behind the same interface. A new org-scoped `warehouse_sync_status` API action serializes the DTO; the frontend Overview tab swaps its mock for the generated client.

**Tech Stack:** Django + DRF + drf-spectacular, Dagster (Django + `posthoganalytics` available in-process), ClickHouse (`sync_execute`), kea + Orval-generated TypeScript.

## Global Constraints

- The UI must never reveal which backend (Dagster/viaduck) is active — `backend` exists in the contract but is not rendered. (Already enforced in `OverviewTab.tsx`.)
- **No new Django model and no migration** — backfill state lives entirely in captured events (this system is being replaced by viaduck, so nothing durable is invested in it).
- **No queries against duckgres / the customer warehouse** — the freshness read hits ClickHouse only.
- The event backfill is **platform-global per day** (partition key is a date, all teams together). Telemetry events go to a single internal project; the provider reads a configured internal `team_id`.
- **Worker capture rule:** never use bare `posthoganalytics.capture()` from the Dagster process — use `ph_scoped_capture` from `posthog.ph_client` (it flushes on context exit, even on exceptions). Verbatim from `CLAUDE.md` and `posthog/ph_client.py:32-53`.
- Neutral state enum is exactly: `seeding | caught_up | lagging | error | not_started`. Backend enum is exactly: `dagster | viaduck`.
- API response field names are **snake_case**; generated TS types are snake_case and consumed directly.
- ClickHouse reads must be **parameterized** (`%(name)s`), never f-string-interpolated, per `.agents/security.md`.
- New code is mypy-`--strict`-clean: annotate every signature, no `Any`, module-level imports only.
- Daily partitions start `2019-01-01`, `end_offset=0` (so "caught up" means fresh through **yesterday**). Verbatim from `posthog/dags/events_backfill_to_ducklake.py:85-89`.
- **Mandatory skills:** `/improving-drf-endpoints` before the serializer/viewset (Tasks 2 & 6); `/adopting-generated-api-types` before the frontend wiring (Task 7).

---

## File Structure

- `posthog/ducklake/backfill_telemetry.py` (new) — canonical event name + property keys + `emit_backfill_partition_event(...)` writer (importable by the Dagster asset).
- `posthog/dags/events_backfill_to_ducklake.py` — asset captures `success`/`failed` events; export captures written-row counts.
- `products/data_warehouse/backend/sync_status/contracts.py` (new) — DTO dataclasses + `WarehouseSyncStatusSerializer`.
- `products/data_warehouse/backend/sync_status/base.py` (new) — `WarehouseSyncStatusProvider` Protocol.
- `products/data_warehouse/backend/sync_status/dagster_provider.py` (new) — `DagsterBackfillStatusProvider` (ClickHouse read).
- `products/data_warehouse/backend/sync_status/viaduck_provider.py` (new) — `ViaduckSyncStatusProvider` + pure mapping.
- `products/data_warehouse/backend/sync_status/factory.py` (new) — `get_warehouse_sync_status_provider(...)`.
- `posthog/settings/data_stores.py` — `WAREHOUSE_SYNC_BACKEND` + `WAREHOUSE_BACKFILL_TELEMETRY_TEAM_ID` settings.
- `products/data_warehouse/backend/api/data_warehouse.py` — add `warehouse_sync_status` action.
- `frontend/src/scenes/data-warehouse/scene/warehouseSyncStatusLogic.ts` (new) — kea loader.
- `frontend/src/scenes/data-warehouse/scene/OverviewTab.tsx` — consume generated type; delete mock.
- `frontend/src/scenes/data-warehouse/scene/mockWarehouseSyncStatus.ts` — deleted in Task 7.
- Tests under `products/data_warehouse/backend/sync_status/test/` and `posthog/ducklake/test/`.

**Execution order:** `1, 2, 4, 5, 3, 6, 7` (the factory in Task 3 imports the concrete providers from Tasks 4 & 5).

---

## Task 1: Emit capture events from the backfill asset (write path)

**Files:**

- Create: `posthog/ducklake/backfill_telemetry.py`
- Modify: `posthog/dags/events_backfill_to_ducklake.py` (export fn ~358-432; asset body ~566-707)
- Test: `posthog/ducklake/test/test_backfill_telemetry.py`

**Interfaces:**

- Produces: constants `BACKFILL_PARTITION_EVENT = "warehouse_event_backfill_partition"`, `BACKFILL_DISTINCT_ID = "warehouse-event-backfill"`; and
  `emit_backfill_partition_event(*, partition_date: date, status: str, run_id: str, rows_exported: int | None = None, files_exported: int | None = None, files_registered: int | None = None, error_message: str | None = None) -> None` (status ∈ `"success" | "failed"`).

This task touches a production asset. Capture must be best-effort — a telemetry failure must never fail the backfill.

- [ ] **Step 1: Write the failing test for the writer**

```python
# posthog/ducklake/test/test_backfill_telemetry.py
from datetime import date
from unittest.mock import MagicMock, patch

from posthog.test.base import BaseTest
from posthog.ducklake.backfill_telemetry import (
    BACKFILL_PARTITION_EVENT,
    emit_backfill_partition_event,
)


class TestBackfillTelemetry(BaseTest):
    def test_emits_event_with_properties(self) -> None:
        capture = MagicMock()
        cm = MagicMock()
        cm.__enter__ = MagicMock(return_value=capture)
        cm.__exit__ = MagicMock(return_value=False)
        with patch("posthog.ducklake.backfill_telemetry.ph_scoped_capture", return_value=cm):
            emit_backfill_partition_event(
                partition_date=date(2020, 5, 1), status="success", run_id="r1", rows_exported=99
            )
        capture.assert_called_once()
        kwargs = capture.call_args.kwargs
        assert kwargs["event"] == BACKFILL_PARTITION_EVENT
        assert kwargs["properties"]["partition_date"] == "2020-05-01"
        assert kwargs["properties"]["status"] == "success"
        assert kwargs["properties"]["rows_exported"] == 99
```

- [ ] **Step 2: Run test to verify it fails**

Run: `hogli test posthog/ducklake/test/test_backfill_telemetry.py -v`
Expected: FAIL with `ModuleNotFoundError`.

- [ ] **Step 3: Implement the writer**

```python
# posthog/ducklake/backfill_telemetry.py
from datetime import date

from posthog.ph_client import ph_scoped_capture

BACKFILL_PARTITION_EVENT = "warehouse_event_backfill_partition"
BACKFILL_DISTINCT_ID = "warehouse-event-backfill"


def emit_backfill_partition_event(
    *,
    partition_date: date,
    status: str,
    run_id: str,
    rows_exported: int | None = None,
    files_exported: int | None = None,
    files_registered: int | None = None,
    error_message: str | None = None,
) -> None:
    """Capture one terminal event per backfill partition run. Best-effort: on Cloud the event
    lands in the internal project; off Cloud `ph_scoped_capture` is a no-op."""
    properties: dict[str, object] = {
        "partition_date": partition_date.isoformat(),
        "status": status,
        "run_id": run_id,
        "rows_exported": rows_exported,
        "files_exported": files_exported,
        "files_registered": files_registered,
        "error_message": error_message,
    }
    with ph_scoped_capture() as capture:
        capture(distinct_id=BACKFILL_DISTINCT_ID, event=BACKFILL_PARTITION_EVENT, properties=properties)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `hogli test posthog/ducklake/test/test_backfill_telemetry.py -v`
Expected: PASS.

- [ ] **Step 5: Capture written rows from the export (best-effort)**

In `export_events_to_s3` (`posthog/dags/events_backfill_to_ducklake.py:358`), change the success branch (~424-432) to also report written rows, and the return type to `tuple[list[str], int]`:

```python
    try:
        _execute_export_with_retry(client, export_sql, settings, chunk_info)
        written_rows = 0
        try:
            progress = client.last_query.progress if client.last_query else None
            written_rows = int(progress.written_rows) if progress else 0
        except Exception:
            written_rows = 0
        context.log.info(f"Successfully exported chunk {chunk_info} ({written_rows} rows)")
        logger.info("export_chunk_success", chunk=team_id_chunk, total_chunks=total_chunks, written_rows=written_rows)
        return [s3_path], written_rows
    except Exception:
        context.log.exception(f"Failed to export chunk {chunk_info} after {MAX_RETRY_ATTEMPTS} attempts")
        logger.exception("export_chunk_failed", chunk=team_id_chunk, total_chunks=total_chunks)
        raise
```

Also change that function's dry-run/no-op `return []` lines to `return [], 0`, and its return annotation to `tuple[list[str], int]`.

- [ ] **Step 6: Aggregate rows and emit terminal events in the asset**

At the top of `posthog/dags/events_backfill_to_ducklake.py` add the module-level import:

```python
from posthog.ducklake.backfill_telemetry import emit_backfill_partition_event
```

In the asset, make `export_single_chunk` (and its inner `do_export`) return `tuple[list[str], int]`, and replace the aggregation:

```python
    all_s3_paths: list[str] = []
    total_rows_exported = 0
```

Parallel branch:

```python
                try:
                    paths, rows = future.result()
                    all_s3_paths.extend(paths)
                    total_rows_exported += rows
                    context.log.info(f"Completed chunk {chunk_i + 1}/{team_id_chunks}")
```

Serial branch:

```python
        for chunk_i in range(team_id_chunks):
            context.log.info(f"Processing chunk {chunk_i + 1}/{team_id_chunks}")
            paths, rows = export_single_chunk(chunk_i)
            all_s3_paths.extend(paths)
            total_rows_exported += rows
            context.log.info(f"Completed chunk {chunk_i + 1}/{team_id_chunks}")
```

Wrap the export+register body so a failure emits a `failed` event then re-raises, and success emits a `success` event. Compute `partition_day = partition_date.date()` near `run_id = ...` (line ~587). Around the export/register section:

```python
    try:
        # ... existing export loop + register_files_with_ducklake(...) + add_output_metadata(...) ...
        if not config.dry_run:
            try:
                emit_backfill_partition_event(
                    partition_date=partition_day,
                    status="success",
                    run_id=context.run.run_id,
                    rows_exported=total_rows_exported,
                    files_exported=len(all_s3_paths),
                    files_registered=registered_count,
                )
            except Exception:
                context.log.exception("Failed to emit backfill success event (non-fatal)")
    except Exception as exc:
        if not config.dry_run:
            try:
                emit_backfill_partition_event(
                    partition_date=partition_day, status="failed", run_id=context.run.run_id, error_message=str(exc)[:1000]
                )
            except Exception:
                context.log.exception("Failed to emit backfill failure event (non-fatal)")
        raise
```

Also add `"rows_exported": total_rows_exported,` to the existing `context.add_output_metadata({...})` dict.

- [ ] **Step 7: Smoke-check imports**

Run: `DEBUG=1 python -c "import posthog.dags.events_backfill_to_ducklake; import posthog.ducklake.backfill_telemetry; print('ok')"`
Expected: prints `ok`.

- [ ] **Step 8: Commit**

```bash
git add posthog/ducklake/backfill_telemetry.py posthog/ducklake/test/test_backfill_telemetry.py posthog/dags/events_backfill_to_ducklake.py
git commit -m "feat(data-warehouse): capture event backfill partition telemetry"
```

---

## Task 2: Neutral contract — DTO + serializer

**Files:**

- Create: `products/data_warehouse/backend/sync_status/contracts.py`
- Test: `products/data_warehouse/backend/sync_status/test/test_contracts.py`

**Interfaces:**

- Produces: dataclasses `InitialBackfill(complete: bool, progress_pct: int | None)`, `SyncError(message: str, since: datetime)`, `WarehouseSyncStatusDTO(backend: str, state: str, fresh_through: datetime | None, lag_seconds: int | None, last_activity_at: datetime | None, initial_backfill: InitialBackfill, total_rows_synced: int | None, error: SyncError | None, updated_at: datetime)`; and `WarehouseSyncStatusSerializer`.

Invoke `/improving-drf-endpoints` first.

- [ ] **Step 1: Write the failing test**

```python
# products/data_warehouse/backend/sync_status/test/test_contracts.py
from datetime import datetime, timezone

from posthog.test.base import BaseTest
from products.data_warehouse.backend.sync_status.contracts import (
    InitialBackfill,
    WarehouseSyncStatusDTO,
    WarehouseSyncStatusSerializer,
)


class TestWarehouseSyncStatusSerializer(BaseTest):
    def test_serializes_nested_shape(self) -> None:
        dto = WarehouseSyncStatusDTO(
            backend="dagster",
            state="caught_up",
            fresh_through=datetime(2026, 6, 17, 23, 59, tzinfo=timezone.utc),
            lag_seconds=3600,
            last_activity_at=datetime(2026, 6, 18, 1, 0, tzinfo=timezone.utc),
            initial_backfill=InitialBackfill(complete=True, progress_pct=100),
            total_rows_synced=8_900_000_000,
            error=None,
            updated_at=datetime(2026, 6, 18, 2, 0, tzinfo=timezone.utc),
        )
        data = WarehouseSyncStatusSerializer(dto).data
        assert data["backend"] == "dagster"
        assert data["state"] == "caught_up"
        assert data["initial_backfill"] == {"complete": True, "progress_pct": 100}
        assert data["error"] is None
        assert data["total_rows_synced"] == 8_900_000_000
```

- [ ] **Step 2: Run test to verify it fails**

Run: `hogli test products/data_warehouse/backend/sync_status/test/test_contracts.py -v`
Expected: FAIL with `ModuleNotFoundError`.

- [ ] **Step 3: Implement the contract**

```python
# products/data_warehouse/backend/sync_status/contracts.py
from dataclasses import dataclass
from datetime import datetime

from rest_framework import serializers

WAREHOUSE_SYNC_STATES = ["seeding", "caught_up", "lagging", "error", "not_started"]
WAREHOUSE_SYNC_BACKENDS = ["dagster", "viaduck"]


@dataclass
class InitialBackfill:
    complete: bool
    progress_pct: int | None


@dataclass
class SyncError:
    message: str
    since: datetime


@dataclass
class WarehouseSyncStatusDTO:
    backend: str
    state: str
    fresh_through: datetime | None
    lag_seconds: int | None
    last_activity_at: datetime | None
    initial_backfill: InitialBackfill
    total_rows_synced: int | None
    error: SyncError | None
    updated_at: datetime


class _InitialBackfillSerializer(serializers.Serializer):
    complete = serializers.BooleanField(help_text="Whether the one-time historical load has finished.")
    progress_pct = serializers.IntegerField(allow_null=True, help_text="Historical load progress, 0-100, or null if unknown.")


class _SyncErrorSerializer(serializers.Serializer):
    message = serializers.CharField(help_text="Human-readable error message.")
    since = serializers.DateTimeField(help_text="When the current error first occurred.")


class WarehouseSyncStatusSerializer(serializers.Serializer):
    backend = serializers.ChoiceField(choices=WAREHOUSE_SYNC_BACKENDS, help_text="Pipeline moving the data (internal).")
    state = serializers.ChoiceField(choices=WAREHOUSE_SYNC_STATES, help_text="Overall freshness state.")
    fresh_through = serializers.DateTimeField(allow_null=True, help_text="Timestamp the warehouse is fresh through.")
    lag_seconds = serializers.IntegerField(allow_null=True, help_text="Seconds behind now/source, or null if unknown.")
    last_activity_at = serializers.DateTimeField(allow_null=True, help_text="Last time the pipeline made progress.")
    initial_backfill = _InitialBackfillSerializer(help_text="One-time historical load status.")
    total_rows_synced = serializers.IntegerField(allow_null=True, help_text="Cumulative events moved into the warehouse.")
    error = _SyncErrorSerializer(allow_null=True, help_text="Current error, or null when healthy.")
    updated_at = serializers.DateTimeField(help_text="When this status was computed.")
```

If `ModuleNotFoundError: products.data_warehouse.backend.sync_status` persists at import, add `products/data_warehouse/backend/sync_status/__init__.py` re-exporting `InitialBackfill, SyncError, WarehouseSyncStatusDTO, WarehouseSyncStatusSerializer` (with `# noqa: F401`).

- [ ] **Step 4: Run test to verify it passes**

Run: `hogli test products/data_warehouse/backend/sync_status/test/test_contracts.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add products/data_warehouse/backend/sync_status
git commit -m "feat(data-warehouse): add warehouse sync status contract"
```

---

## Task 4: `DagsterBackfillStatusProvider` (reads telemetry events)

> Implemented before Task 3 because the factory imports it.

**Files:**

- Create: `products/data_warehouse/backend/sync_status/dagster_provider.py`
- Modify: `posthog/settings/data_stores.py` (add `WAREHOUSE_BACKFILL_TELEMETRY_TEAM_ID`)
- Test: `products/data_warehouse/backend/sync_status/test/test_dagster_provider.py`

**Interfaces:**

- Consumes: `BACKFILL_PARTITION_EVENT` (Task 1), `WarehouseSyncStatusDTO`/`InitialBackfill`/`SyncError` (Task 2), setting `WAREHOUSE_BACKFILL_TELEMETRY_TEAM_ID: int | None`.
- Produces: `DagsterBackfillStatusProvider` with `backend = "dagster"`, `get_status(organization_id: str) -> WarehouseSyncStatusDTO`. `organization_id` accepted but ignored (backfill is global).

Reads the internal telemetry project's `events` in ClickHouse, taking the latest event per `partition_date` (argMax by `timestamp`). Aggregates: `fresh_through` = end-of-day of max `partition_date` whose latest status is `success`; counts of success/failed partitions; `total_rows_synced` = Σ latest `rows_exported` for success partitions; `last_activity_at` = max event timestamp; `error` = latest failed partition's message. State: `error` if any failed; `not_started` if no telemetry team or no events; `seeding` if not complete; `lagging` if lag > 2 days; else `caught_up`.

- [ ] **Step 1: Add the setting**

In `posthog/settings/data_stores.py`:

```python
# Internal project that receives warehouse event-backfill telemetry (region-specific on Cloud).
# Defaults to the Cloud dogfooding project on US. None/0 disables the read (off Cloud / dev).
WAREHOUSE_BACKFILL_TELEMETRY_TEAM_ID = get_from_env("WAREHOUSE_BACKFILL_TELEMETRY_TEAM_ID", 2, type_cast=int)
```

(Confirm `get_from_env` is imported in that file; it is. If not, use `int(os.getenv("WAREHOUSE_BACKFILL_TELEMETRY_TEAM_ID", "2"))`.)

- [ ] **Step 2: Write the failing tests**

```python
# products/data_warehouse/backend/sync_status/test/test_dagster_provider.py
from datetime import timedelta

from django.test import override_settings
from django.utils import timezone

from posthog.test.base import ClickhouseTestMixin, _create_event, flush_persons_and_events
from posthog.test.base import APIBaseTest
from posthog.ducklake.backfill_telemetry import BACKFILL_DISTINCT_ID, BACKFILL_PARTITION_EVENT
from products.data_warehouse.backend.sync_status.dagster_provider import DagsterBackfillStatusProvider


class TestDagsterProvider(ClickhouseTestMixin, APIBaseTest):
    def _emit(self, partition_date: str, status: str, **props: object) -> None:
        _create_event(
            team=self.team,
            event=BACKFILL_PARTITION_EVENT,
            distinct_id=BACKFILL_DISTINCT_ID,
            properties={"partition_date": partition_date, "status": status, **props},
        )

    @override_settings(WAREHOUSE_BACKFILL_TELEMETRY_TEAM_ID=None)
    def test_not_started_without_telemetry_team(self) -> None:
        dto = DagsterBackfillStatusProvider().get_status("org-1")
        assert dto.state == "not_started"

    def test_error_state_when_a_partition_failed(self) -> None:
        yesterday = (timezone.now().date() - timedelta(days=1)).isoformat()
        self._emit(yesterday, "success", rows_exported=5)
        self._emit("2020-01-01", "failed", error_message="boom")
        flush_persons_and_events()
        with override_settings(WAREHOUSE_BACKFILL_TELEMETRY_TEAM_ID=self.team.id):
            dto = DagsterBackfillStatusProvider().get_status("org-1")
        assert dto.state == "error"
        assert dto.error is not None
        assert dto.error.message == "boom"
        assert dto.total_rows_synced == 5

    def test_latest_event_per_partition_wins(self) -> None:
        d = "2020-01-01"
        self._emit(d, "failed", error_message="first")
        self._emit(d, "success", rows_exported=10)  # later event for same partition
        flush_persons_and_events()
        with override_settings(WAREHOUSE_BACKFILL_TELEMETRY_TEAM_ID=self.team.id):
            dto = DagsterBackfillStatusProvider().get_status("org-1")
        assert dto.error is None  # the success supersedes the earlier failure
        assert dto.total_rows_synced == 10
```

> Note: `_create_event` assigns `timestamp` in creation order; the second `_emit` for the same partition is later, so `argMax(..., timestamp)` picks `success`. If the harness needs explicit ordering, pass `timestamp=` to `_create_event` (earlier for the first, later for the second).

- [ ] **Step 3: Run tests to verify they fail**

Run: `hogli test products/data_warehouse/backend/sync_status/test/test_dagster_provider.py -v`
Expected: FAIL (module does not exist).

- [ ] **Step 4: Implement the provider**

```python
# products/data_warehouse/backend/sync_status/dagster_provider.py
from datetime import date, datetime, time, timezone as dt_timezone

from django.conf import settings
from django.utils import timezone

from posthog.clickhouse.client import sync_execute
from posthog.ducklake.backfill_telemetry import BACKFILL_PARTITION_EVENT
from products.data_warehouse.backend.sync_status.contracts import (
    InitialBackfill,
    SyncError,
    WarehouseSyncStatusDTO,
)

PARTITION_START = date(2019, 1, 1)
CAUGHT_UP_LAG_SECONDS = 2 * 24 * 60 * 60

# Latest event per partition_date for the telemetry team.
_QUERY = """
SELECT
    JSONExtractString(properties, 'partition_date') AS partition_date,
    argMax(JSONExtractString(properties, 'status'), timestamp) AS status,
    argMax(JSONExtractInt(properties, 'rows_exported'), timestamp) AS rows_exported,
    argMax(JSONExtractString(properties, 'error_message'), timestamp) AS error_message,
    max(timestamp) AS last_event_at
FROM events
WHERE team_id = %(team_id)s AND event = %(event)s
GROUP BY partition_date
"""


def _empty(now: datetime, state: str) -> WarehouseSyncStatusDTO:
    return WarehouseSyncStatusDTO(
        backend="dagster",
        state=state,
        fresh_through=None,
        lag_seconds=None,
        last_activity_at=None,
        initial_backfill=InitialBackfill(complete=False, progress_pct=None),
        total_rows_synced=None,
        error=None,
        updated_at=now,
    )


class DagsterBackfillStatusProvider:
    backend = "dagster"

    def get_status(self, organization_id: str) -> WarehouseSyncStatusDTO:
        now = timezone.now()
        team_id = getattr(settings, "WAREHOUSE_BACKFILL_TELEMETRY_TEAM_ID", None)
        if not team_id:
            return _empty(now, "not_started")

        rows = sync_execute(_QUERY, {"team_id": int(team_id), "event": BACKFILL_PARTITION_EVENT})
        if not rows:
            return _empty(now, "not_started")

        done = 0
        failed = 0
        total_rows = 0
        fresh_date: date | None = None
        last_event_at: datetime | None = None
        latest_failure: tuple[datetime, str] | None = None

        for partition_date_str, status, row_count, error_message, event_at in rows:
            if last_event_at is None or event_at > last_event_at:
                last_event_at = event_at
            if status == "success":
                done += 1
                total_rows += int(row_count or 0)
                pd = date.fromisoformat(partition_date_str)
                if fresh_date is None or pd > fresh_date:
                    fresh_date = pd
            elif status == "failed":
                failed += 1
                if latest_failure is None or event_at > latest_failure[0]:
                    latest_failure = (event_at, error_message or "Backfill partition failed")

        today = now.date()
        total_days = max((today - PARTITION_START).days, 1)
        complete = done >= total_days
        progress_pct = min(round(100 * done / total_days), 100)

        fresh_through = (
            datetime.combine(fresh_date, time.max, tzinfo=dt_timezone.utc) if fresh_date is not None else None
        )
        lag_seconds = int((now - fresh_through).total_seconds()) if fresh_through is not None else None

        error = SyncError(message=latest_failure[1], since=latest_failure[0]) if latest_failure else None

        if failed:
            state = "error"
        elif done == 0:
            state = "not_started"
        elif not complete:
            state = "seeding"
        elif lag_seconds is not None and lag_seconds > CAUGHT_UP_LAG_SECONDS:
            state = "lagging"
        else:
            state = "caught_up"

        return WarehouseSyncStatusDTO(
            backend=self.backend,
            state=state,
            fresh_through=fresh_through,
            lag_seconds=lag_seconds,
            last_activity_at=last_event_at,
            initial_backfill=InitialBackfill(complete=complete, progress_pct=progress_pct),
            total_rows_synced=total_rows or None,
            error=error,
            updated_at=now,
        )
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `hogli test products/data_warehouse/backend/sync_status/test/test_dagster_provider.py -v`
Expected: PASS (all three).

- [ ] **Step 6: Commit**

```bash
git add products/data_warehouse/backend/sync_status/dagster_provider.py products/data_warehouse/backend/sync_status/test/test_dagster_provider.py posthog/settings/data_stores.py
git commit -m "feat(data-warehouse): add dagster backfill status provider (telemetry read)"
```

---

## Task 5: `ViaduckSyncStatusProvider` (staged)

**Files:**

- Create: `products/data_warehouse/backend/sync_status/viaduck_provider.py`
- Test: `products/data_warehouse/backend/sync_status/test/test_viaduck_provider.py`

**Interfaces:**

- Consumes: `WarehouseSyncStatusDTO`/`InitialBackfill`/`SyncError` (Task 2).
- Produces: `ViaduckSyncStatusProvider` with `backend = "viaduck"`, `get_status(organization_id: str) -> WarehouseSyncStatusDTO`, and pure helper `viaduck_state_to_sync_state(health: str, cursor_snapshot: int, lag_seconds: float | None) -> str`.

Ships the mapping logic (tested) and a `get_status` that returns `not_started` until `_fetch_destination` is wired to viaduck (`viaduck.viaduck_state` filtered by `routing_value(org)`, or viaduck's `/status`). Reference fields: `status ∈ {healthy, buffering, flushing, lagging, error}`, `last_snapshot_id`, `lag_seconds`, `rows_replicated`, `last_replicated_at`, `last_error` — see `/Users/eric/PostHog/viaduck/viaduck/server.py` (`DestStatus`) and `state.py`.

- [ ] **Step 1: Write the failing tests**

```python
# products/data_warehouse/backend/sync_status/test/test_viaduck_provider.py
from posthog.test.base import BaseTest
from products.data_warehouse.backend.sync_status.viaduck_provider import (
    ViaduckSyncStatusProvider,
    viaduck_state_to_sync_state,
)


class TestViaduckMapping(BaseTest):
    def test_health_maps_to_neutral_state(self) -> None:
        assert viaduck_state_to_sync_state("healthy", 42, 0.0) == "caught_up"
        assert viaduck_state_to_sync_state("buffering", 42, 0.0) == "caught_up"
        assert viaduck_state_to_sync_state("flushing", 42, 0.0) == "caught_up"
        assert viaduck_state_to_sync_state("lagging", 42, 30.0) == "lagging"
        assert viaduck_state_to_sync_state("error", 42, 0.0) == "error"

    def test_cursor_zero_is_seeding(self) -> None:
        assert viaduck_state_to_sync_state("buffering", 0, 0.0) == "seeding"

    def test_get_status_not_started_without_source(self) -> None:
        dto = ViaduckSyncStatusProvider().get_status("org-1")
        assert dto.backend == "viaduck"
        assert dto.state == "not_started"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `hogli test products/data_warehouse/backend/sync_status/test/test_viaduck_provider.py -v`
Expected: FAIL (module does not exist).

- [ ] **Step 3: Implement the provider**

```python
# products/data_warehouse/backend/sync_status/viaduck_provider.py
from dataclasses import dataclass
from datetime import datetime

from django.utils import timezone

from products.data_warehouse.backend.sync_status.contracts import (
    InitialBackfill,
    SyncError,
    WarehouseSyncStatusDTO,
)


@dataclass
class ViaduckDestinationState:
    health: str  # healthy | buffering | flushing | lagging | error
    cursor_snapshot: int  # last_snapshot_id; 0 means seeding not yet complete
    lag_seconds: float | None
    rows_replicated: int | None
    last_replicated_at: datetime | None
    fresh_through: datetime | None
    last_error: str | None
    last_error_at: datetime | None


def viaduck_state_to_sync_state(health: str, cursor_snapshot: int, lag_seconds: float | None) -> str:
    if health == "error":
        return "error"
    if cursor_snapshot == 0:
        return "seeding"
    if health == "lagging":
        return "lagging"
    return "caught_up"  # healthy | buffering | flushing


class ViaduckSyncStatusProvider:
    backend = "viaduck"

    def _fetch_destination(self, organization_id: str) -> ViaduckDestinationState | None:
        # SWAP POINT: read viaduck.viaduck_state filtered by routing_value(organization_id),
        # or hit viaduck's /status endpoint. Returns None until that source is wired up.
        return None

    def get_status(self, organization_id: str) -> WarehouseSyncStatusDTO:
        now = timezone.now()
        dest = self._fetch_destination(organization_id)
        if dest is None:
            return WarehouseSyncStatusDTO(
                backend=self.backend,
                state="not_started",
                fresh_through=None,
                lag_seconds=None,
                last_activity_at=None,
                initial_backfill=InitialBackfill(complete=False, progress_pct=None),
                total_rows_synced=None,
                error=None,
                updated_at=now,
            )

        state = viaduck_state_to_sync_state(dest.health, dest.cursor_snapshot, dest.lag_seconds)
        error = (
            SyncError(message=dest.last_error, since=dest.last_error_at or now)
            if dest.health == "error" and dest.last_error
            else None
        )
        return WarehouseSyncStatusDTO(
            backend=self.backend,
            state=state,
            fresh_through=dest.fresh_through,
            lag_seconds=int(dest.lag_seconds) if dest.lag_seconds is not None else None,
            last_activity_at=dest.last_replicated_at,
            initial_backfill=InitialBackfill(complete=dest.cursor_snapshot > 0, progress_pct=None),
            total_rows_synced=dest.rows_replicated,
            error=error,
            updated_at=now,
        )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `hogli test products/data_warehouse/backend/sync_status/test/test_viaduck_provider.py -v`
Expected: PASS (all three).

- [ ] **Step 5: Commit**

```bash
git add products/data_warehouse/backend/sync_status/viaduck_provider.py products/data_warehouse/backend/sync_status/test/test_viaduck_provider.py
git commit -m "feat(data-warehouse): stage viaduck sync status provider"
```

---

## Task 3: Provider protocol + factory + backend setting

> Run after Tasks 4 & 5 (it imports both providers).

**Files:**

- Create: `products/data_warehouse/backend/sync_status/base.py`
- Create: `products/data_warehouse/backend/sync_status/factory.py`
- Modify: `posthog/settings/data_stores.py`
- Test: `products/data_warehouse/backend/sync_status/test/test_factory.py`

**Interfaces:**

- Produces: `WarehouseSyncStatusProvider` Protocol with `get_status(self, organization_id: str) -> WarehouseSyncStatusDTO`; `get_warehouse_sync_status_provider(organization_id: str) -> WarehouseSyncStatusProvider`; setting `WAREHOUSE_SYNC_BACKEND: str` (default `"dagster"`).

- [ ] **Step 1: Add the setting**

In `posthog/settings/data_stores.py`:

```python
# Which pipeline backs the warehouse sync-status API: "dagster" (current) or "viaduck" (future CDC).
WAREHOUSE_SYNC_BACKEND = get_from_env("WAREHOUSE_SYNC_BACKEND", "dagster")
```

- [ ] **Step 2: Write the Protocol**

```python
# products/data_warehouse/backend/sync_status/base.py
from typing import Protocol

from products.data_warehouse.backend.sync_status.contracts import WarehouseSyncStatusDTO


class WarehouseSyncStatusProvider(Protocol):
    backend: str

    def get_status(self, organization_id: str) -> WarehouseSyncStatusDTO: ...
```

- [ ] **Step 3: Write the failing factory test**

```python
# products/data_warehouse/backend/sync_status/test/test_factory.py
from django.test import override_settings

from posthog.test.base import BaseTest
from products.data_warehouse.backend.sync_status.dagster_provider import DagsterBackfillStatusProvider
from products.data_warehouse.backend.sync_status.factory import get_warehouse_sync_status_provider
from products.data_warehouse.backend.sync_status.viaduck_provider import ViaduckSyncStatusProvider


class TestFactory(BaseTest):
    @override_settings(WAREHOUSE_SYNC_BACKEND="dagster")
    def test_defaults_to_dagster(self) -> None:
        assert isinstance(get_warehouse_sync_status_provider("org-1"), DagsterBackfillStatusProvider)

    @override_settings(WAREHOUSE_SYNC_BACKEND="viaduck")
    def test_selects_viaduck(self) -> None:
        assert isinstance(get_warehouse_sync_status_provider("org-1"), ViaduckSyncStatusProvider)
```

- [ ] **Step 4: Run test to verify it fails**

Run: `hogli test products/data_warehouse/backend/sync_status/test/test_factory.py -v`
Expected: FAIL (factory does not exist).

- [ ] **Step 5: Implement the factory**

```python
# products/data_warehouse/backend/sync_status/factory.py
from django.conf import settings

from products.data_warehouse.backend.sync_status.base import WarehouseSyncStatusProvider
from products.data_warehouse.backend.sync_status.dagster_provider import DagsterBackfillStatusProvider
from products.data_warehouse.backend.sync_status.viaduck_provider import ViaduckSyncStatusProvider


def get_warehouse_sync_status_provider(organization_id: str) -> WarehouseSyncStatusProvider:
    backend = getattr(settings, "WAREHOUSE_SYNC_BACKEND", "dagster")
    if backend == "viaduck":
        return ViaduckSyncStatusProvider()
    return DagsterBackfillStatusProvider()
```

- [ ] **Step 6: Run test to verify it passes**

Run: `hogli test products/data_warehouse/backend/sync_status/test/test_factory.py -v`
Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add products/data_warehouse/backend/sync_status/base.py products/data_warehouse/backend/sync_status/factory.py products/data_warehouse/backend/sync_status/test/test_factory.py posthog/settings/data_stores.py
git commit -m "feat(data-warehouse): add warehouse sync provider seam"
```

---

## Task 6: API action `warehouse_sync_status` + generated types

**Files:**

- Modify: `products/data_warehouse/backend/api/data_warehouse.py` (add action after the existing managed-warehouse actions, ~line 950)
- Test: `products/data_warehouse/backend/api/test/test_warehouse_sync_status.py`
- Regenerate: `products/data_warehouse/frontend/generated/*`

**Interfaces:**

- Consumes: `get_warehouse_sync_status_provider` (Task 3), `WarehouseSyncStatusSerializer` (Task 2).
- Produces: `GET /api/environments/{team_id}/data_warehouse/warehouse_sync_status/` → `WarehouseSyncStatusSerializer` shape. Generated TS: `dataWarehouseWarehouseSyncStatusRetrieve(projectId)` returning `WarehouseSyncStatusApi`.

Invoke `/improving-drf-endpoints` first.

- [ ] **Step 1: Write the failing API test**

```python
# products/data_warehouse/backend/api/test/test_warehouse_sync_status.py
from datetime import timedelta

from django.test import override_settings
from django.utils import timezone

from posthog.test.base import APIBaseTest, ClickhouseTestMixin, _create_event, flush_persons_and_events
from posthog.ducklake.backfill_telemetry import BACKFILL_DISTINCT_ID, BACKFILL_PARTITION_EVENT


class TestWarehouseSyncStatusAPI(ClickhouseTestMixin, APIBaseTest):
    def test_returns_neutral_contract(self) -> None:
        yesterday = (timezone.now().date() - timedelta(days=1)).isoformat()
        _create_event(
            team=self.team,
            event=BACKFILL_PARTITION_EVENT,
            distinct_id=BACKFILL_DISTINCT_ID,
            properties={"partition_date": yesterday, "status": "success", "rows_exported": 5},
        )
        flush_persons_and_events()

        with override_settings(WAREHOUSE_BACKFILL_TELEMETRY_TEAM_ID=self.team.id):
            res = self.client.get(f"/api/environments/{self.team.id}/data_warehouse/warehouse_sync_status/")

        assert res.status_code == 200, res.json()
        body = res.json()
        assert set(body.keys()) >= {
            "backend", "state", "fresh_through", "lag_seconds", "last_activity_at",
            "initial_backfill", "total_rows_synced", "error", "updated_at",
        }
        assert body["initial_backfill"].keys() == {"complete", "progress_pct"}
        assert body["total_rows_synced"] == 5
```

- [ ] **Step 2: Run test to verify it fails**

Run: `hogli test products/data_warehouse/backend/api/test/test_warehouse_sync_status.py -v`
Expected: FAIL with 404 (action not registered).

- [ ] **Step 3: Add the action**

Add imports near the top of `products/data_warehouse/backend/api/data_warehouse.py`:

```python
from products.data_warehouse.backend.sync_status.contracts import WarehouseSyncStatusSerializer
from products.data_warehouse.backend.sync_status.factory import get_warehouse_sync_status_provider
```

Add inside `DataWarehouseViewSet` (mirror the `warehouse_status` action's style):

```python
    @extend_schema(responses={200: WarehouseSyncStatusSerializer})
    @action(methods=["GET"], detail=False, url_path="warehouse_sync_status")
    def warehouse_sync_status(self, request: Request, **kwargs: Any) -> Response:
        """Backend-neutral freshness of the managed warehouse's event data."""
        provider = get_warehouse_sync_status_provider(str(self.team.organization_id))
        dto = provider.get_status(str(self.team.organization_id))
        return Response(WarehouseSyncStatusSerializer(dto).data)
```

(Confirm `extend_schema`, `action`, `Response`, `Request`, `Any` are already imported in this file; the existing actions use them.)

- [ ] **Step 4: Run test to verify it passes**

Run: `hogli test products/data_warehouse/backend/api/test/test_warehouse_sync_status.py -v`
Expected: PASS.

- [ ] **Step 5: Regenerate OpenAPI + TS types**

Run: `hogli build:openapi`
Expected: `products/data_warehouse/frontend/generated/api.ts` and `api.schemas.ts` gain `dataWarehouseWarehouseSyncStatusRetrieve` and `WarehouseSyncStatusApi` (snake_case, nested `initial_backfill`/`error`). Don't hand-edit generated files.

- [ ] **Step 6: Commit**

```bash
git add products/data_warehouse/backend/api/data_warehouse.py products/data_warehouse/backend/api/test/test_warehouse_sync_status.py products/data_warehouse/frontend/generated
git commit -m "feat(data-warehouse): add warehouse_sync_status API action"
```

---

## Task 7: Frontend — swap mock for the real endpoint

**Files:**

- Create: `frontend/src/scenes/data-warehouse/scene/warehouseSyncStatusLogic.ts`
- Modify: `frontend/src/scenes/data-warehouse/scene/OverviewTab.tsx`
- Delete: `frontend/src/scenes/data-warehouse/scene/mockWarehouseSyncStatus.ts`

**Interfaces:**

- Consumes: generated `dataWarehouseWarehouseSyncStatusRetrieve` + `WarehouseSyncStatusApi` (Task 6).
- Produces: `warehouseSyncStatusLogic` exposing `{ syncStatus: WarehouseSyncStatusApi | null, syncStatusLoading: boolean }`.

Invoke `/adopting-generated-api-types` first. The generated type is **snake_case** — `OverviewTab` field accesses change accordingly (`freshThrough`→`fresh_through`, `lagSeconds`→`lag_seconds`, `lastActivityAt`→`last_activity_at`, `initialBackfill`→`initial_backfill`, `progressPct`→`progress_pct`, `totalRowsSynced`→`total_rows_synced`; `error.message`/`error.since` unchanged).

- [ ] **Step 1: Write the loader logic**

```typescript
// frontend/src/scenes/data-warehouse/scene/warehouseSyncStatusLogic.ts
import { afterMount, kea, path } from 'kea'
import { loaders } from 'kea-loaders'

import { currentProjectId } from 'lib/utils/project'
import { dataWarehouseWarehouseSyncStatusRetrieve } from 'products/data_warehouse/frontend/generated/api'
import type { WarehouseSyncStatusApi } from 'products/data_warehouse/frontend/generated/api.schemas'

import type { warehouseSyncStatusLogicType } from './warehouseSyncStatusLogicType'

export const warehouseSyncStatusLogic = kea<warehouseSyncStatusLogicType>([
  path(['scenes', 'data-warehouse', 'scene', 'warehouseSyncStatusLogic']),
  loaders({
    syncStatus: [
      null as WarehouseSyncStatusApi | null,
      {
        loadSyncStatus: async (): Promise<WarehouseSyncStatusApi | null> => {
          try {
            return await dataWarehouseWarehouseSyncStatusRetrieve(currentProjectId())
          } catch (e: any) {
            if (e.status === 404) {
              return null
            }
            throw e
          }
        },
      },
    ],
  }),
  afterMount(({ actions }) => {
    actions.loadSyncStatus()
  }),
])
```

> Verify the exact `currentProjectId` import path and the generated function name against `warehouseProvisioningLogic.ts` (it imports the same generated module). Match it exactly.

- [ ] **Step 2: Point OverviewTab at the logic and generated type; delete the mock**

In `OverviewTab.tsx`: remove the `./mockWarehouseSyncStatus` import; import `WarehouseSyncStatusApi` from the generated schemas and `warehouseSyncStatusLogic`; inline the small `formatLag`/`formatRows` helpers (their file is being deleted). Replace `const status = useMemo(() => getMockWarehouseSyncStatus(), [])` with `const { syncStatus } = useValues(warehouseSyncStatusLogic)`. Guard the render on `syncStatus` (show a `Spinner` while null). Rename every `status.*` access to the snake_case fields in the Interfaces block, and change the `WarehouseSyncStatus` type to `WarehouseSyncStatusApi`. Delete `frontend/src/scenes/data-warehouse/scene/mockWarehouseSyncStatus.ts`.

- [ ] **Step 3: Typecheck + lint**

Run: `pnpm --filter=@posthog/frontend typescript:check 2>&1 | rg "OverviewTab|warehouseSyncStatusLogic"`
Expected: no output.
Run: `npx oxlint frontend/src/scenes/data-warehouse/scene/OverviewTab.tsx frontend/src/scenes/data-warehouse/scene/warehouseSyncStatusLogic.ts`
Expected: 0 warnings, 0 errors.

- [ ] **Step 4: Commit**

```bash
git add frontend/src/scenes/data-warehouse/scene/OverviewTab.tsx frontend/src/scenes/data-warehouse/scene/warehouseSyncStatusLogic.ts
git rm frontend/src/scenes/data-warehouse/scene/mockWarehouseSyncStatus.ts
git commit -m "feat(data-warehouse): wire overview tab to warehouse_sync_status endpoint"
```

---

## Self-Review

**Spec coverage:**

- No migration / capture-based write → Task 1 (`emit_backfill_partition_event` from the asset). ✓
- No duckgres queries (ClickHouse-only read) → Task 4 (`sync_execute` against the internal telemetry team). ✓
- Neutral contract both backends fill → Tasks 2, 4, 5. ✓
- Provider seam + flag swap → Task 3. ✓
- Viaduck staged so swap is config-only → Task 5 `_fetch_destination` swap point. ✓
- API endpoint (org-scoped, snake_case, drf-spectacular) → Task 6. ✓
- Frontend swap mock → generated fetch → Task 7. ✓

**Type consistency:** `WarehouseSyncStatusDTO` fields match the serializer; `InitialBackfill(complete, progress_pct)` and `SyncError(message, since)` consistent across Tasks 2/4/5; `emit_backfill_partition_event` signature identical in Tasks 1/(asset); `BACKFILL_PARTITION_EVENT`/`BACKFILL_DISTINCT_ID` shared between writer (Task 1) and reader (Task 4) and tests; `get_status(organization_id: str)` identical across Tasks 3/4/5; state enum consistent.

**Execution order:** `1, 2, 4, 5, 3, 6, 7`.

**Risks / open items (non-blocking):**

- `WAREHOUSE_BACKFILL_TELEMETRY_TEAM_ID` is region-specific (US dogfood project = 2; set EU's via env). Off Cloud it's effectively unused → provider returns `not_started`. Confirm the public ingest key (`posthog/ph_client.py`) routes backfill events to that same project; if not, set the team id to whichever internal project receives them.
- Ingestion lag (seconds) means a just-finished partition appears in the card a moment later — acceptable for a freshness view.
- `client.last_query.progress.written_rows` is best-effort; if unavailable, `total_rows_synced` is null and the UI shows "—".
- Wiring viaduck's real data source (`_fetch_destination`) and snapshot-id→timestamp resolution for `fresh_through` are deferred to the viaduck swap.
- Optional follow-ups: cache the ClickHouse read (short TTL) since it's hit on each Overview load; per-org feature-flag override of `WAREHOUSE_SYNC_BACKEND`; polling in `warehouseSyncStatusLogic`.
