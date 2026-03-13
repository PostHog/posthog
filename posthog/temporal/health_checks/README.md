# Health check framework (Temporal)

A framework for running scheduled health checks across PostHog teams. Subclass `HealthCheck`, implement a `detect` method, and the framework handles team batching, parallel execution, issue persistence, auto-resolution, and rollout control — all orchestrated by Temporal.

Issues are written to the `posthog_healthissue` table and automatically resolved when a team passes a subsequent check run.

## Quick start

### 1. Subclass `HealthCheck`

Create a module in the appropriate product directory
(e.g. `products/web_analytics/backend/temporal/health_checks/my_check.py`).

The `detect` method receives a batch of team IDs and returns issues found:

```python
from posthog.models.health_issue import HealthIssue
from posthog.temporal.health_checks.detectors import CLICKHOUSE_BATCH_EXECUTION_POLICY
from posthog.temporal.health_checks.framework import HealthCheck
from posthog.temporal.health_checks.models import HealthCheckResult
from posthog.dags.common.owners import JobOwners
from posthog.temporal.health_checks.query import execute_clickhouse_health_team_query

STALE_DATA_SQL = """
SELECT team_id
FROM events
WHERE team_id IN %(team_ids)s
  AND timestamp >= now() - INTERVAL %(lookback_days)s DAY
GROUP BY team_id
"""


class StaleDataCheck(HealthCheck):
    name = "stale_data"
    kind = "stale_data"
    owner = JobOwners.TEAM_WEB_ANALYTICS
    policy = CLICKHOUSE_BATCH_EXECUTION_POLICY
    schedule = "0 8 * * *"  # daily at 08:00 UTC

    def detect(self, team_ids: list[int]) -> dict[int, list[HealthCheckResult]]:
        rows = execute_clickhouse_health_team_query(
            STALE_DATA_SQL,
            team_ids=team_ids,
            lookback_days=7,
        )

        teams_with_recent_events = {team_id for team_id, *_ in rows}

        issues: dict[int, list[HealthCheckResult]] = {}
        for team_id in set(team_ids) - teams_with_recent_events:
            issues[team_id] = [
                HealthCheckResult(
                    severity=HealthIssue.Severity.WARNING,
                    payload={"reason": "No events in 7 days"},
                    hash_keys=[],
                )
            ]

        return issues
```

Teams not present in the returned dict are considered healthy. Their active issues (for this `kind`) are auto-resolved.

The class auto-registers itself when its module is imported — no extra registration call is needed.

### 2. Register the module

Add the module path to `HEALTH_CHECK_MODULES` in `registry.py`:

```python
HEALTH_CHECK_MODULES = [
    ...,
    "products.web_analytics.backend.temporal.health_checks.stale_data",
]
```

### 3. Done

If your class sets a `schedule`, a Temporal schedule is automatically created at deploy time via `init_schedules`. No additional wiring is needed.
Omit `schedule` if you only want the check to be triggered manually from the admin UI.

## `HealthCheck` class reference

```python
class HealthCheck:
    name: str
    kind: str
    owner: JobOwners
    policy: HealthExecutionPolicy = DEFAULT_EXECUTION_POLICY
    schedule: str | None = None
    rollout_percentage: float = 1.0
    not_processed_threshold: float = 0.1
    dry_run: bool = False

    def detect(self, team_ids: list[int]) -> dict[int, list[HealthCheckResult]]:
        raise NotImplementedError
```

| Attribute                 | Type                    | Default                    | Description                                                                                                                       |
| ------------------------- | ----------------------- | -------------------------- | --------------------------------------------------------------------------------------------------------------------------------- |
| `name`                    | `str`                   | required                   | Unique name used in Temporal workflow and schedule naming                                                                         |
| `kind`                    | `str`                   | required                   | Issue kind written to the `posthog_healthissue` table. Must be globally unique                                                    |
| `owner`                   | `JobOwners`             | required                   | Team that owns this check (used for alert routing)                                                                                |
| `policy`                  | `HealthExecutionPolicy` | `DEFAULT_EXECUTION_POLICY` | Controls batch size and concurrency (see [Execution policies](#execution-policies))                                               |
| `schedule`                | `str \| None`           | `None`                     | Cron expression (UTC). Omit for manual-only checks                                                                                |
| `rollout_percentage`      | `float`                 | `1.0`                      | Fraction of teams to include (0–1, e.g. 0.01 = 1%). Deterministic by team ID                                                      |
| `not_processed_threshold` | `float`                 | `0.1`                      | Fail the workflow if this fraction of teams are skipped or errored                                                                |
| `dry_run`                 | `bool`                  | `False`                    | Run detection but skip DB writes (upsert/resolve). Sets the default for scheduled runs; can be overridden per-run in the admin UI |

## `HealthCheckResult`

Every detected issue is a `HealthCheckResult`:

```python
HealthCheckResult(
    severity=HealthIssue.Severity.WARNING,  # "critical", "warning", or "info"
    payload={"reason": "No events", "last_seen": "2025-01-01"},
    hash_keys=["reason"],  # optional
)
```

| Field       | Type                   | Description                          |
| ----------- | ---------------------- | ------------------------------------ |
| `severity`  | `HealthIssue.Severity` | One of `CRITICAL`, `WARNING`, `INFO` |
| `payload`   | `dict[str, Any]`       | Arbitrary data stored with the issue |
| `hash_keys` | `list[str] \| None`    | Controls issue identity (see below)  |

### Issue identity and `hash_keys`

An active issue is uniquely identified by `(team_id, kind, unique_hash)`. The `unique_hash` is derived from `kind` + `payload`, controlled by `hash_keys`. `kind` is always included as a prefix in the hash content, so the hash is always scoped to the issue kind.

| `hash_keys` value        | Hash content                   | Use case                                                  |
| ------------------------ | ------------------------------ | --------------------------------------------------------- |
| `None` (default)         | `kind` + full payload          | Each unique payload produces a distinct issue             |
| `[]`                     | `kind` only (payload = `{}`)   | One active issue per team per kind                        |
| `["field_a", "field_b"]` | `kind` + selected payload keys | Identity based on specific fields, ignoring volatile ones |

## Issue lifecycle

On each check run, for every team in the batch:

1. **Upsert** — Issues returned by the detector are written (or updated) as `status=active`.
2. **Resolve** — Active issues for checked teams that were _not_ returned by the detector are marked `status=resolved`.

## Execution policies

| Preset                              | `batch_size` | `max_concurrent` | Use case                |
| ----------------------------------- | ------------ | ---------------- | ----------------------- |
| `DEFAULT_EXECUTION_POLICY`          | 1000         | 5                | Lightweight checks      |
| `CLICKHOUSE_BATCH_EXECUTION_POLICY` | 250          | 1                | ClickHouse query checks |

Teams are split into batches of `batch_size` IDs. Up to `max_concurrent` batches run concurrently, controlled by an `asyncio.Semaphore` in the Temporal workflow. Each batch activity has a retry policy (3 attempts, 30 s initial interval, exponential backoff up to 5 min).

Set the `policy` class attribute on your `HealthCheck` subclass to choose one.

## Configuration guide

### Batch size and concurrency

Defaults depend on the execution policy you choose. You can create a custom `HealthExecutionPolicy` if the presets don't fit:

```python
from posthog.temporal.health_checks.detectors import HealthExecutionPolicy

class MyCheck(HealthCheck):
    policy = HealthExecutionPolicy(batch_size=500, max_concurrent=2)
    ...
```

### Rollout percentage

`rollout_percentage` deterministically selects a subset of teams using a SHA-256 hash of each team ID. The selection is stable across runs — the same teams are always included at the same percentage.

Use this to canary a new health check:

```python
class MyCheck(HealthCheck):
    rollout_percentage = 0.01  # start with 1% of teams
    ...
```

At `rollout_percentage=1.0` (default), all teams are processed.

### Failure threshold

If more than `not_processed_threshold` (default 10%) of teams are skipped or errored, the workflow fails with `HealthCheckThresholdExceeded`. This catches detector bugs early — if your detect function is crashing for a large fraction of teams, the workflow alerts rather than silently resolving issues.

### Worked example

With 300,000 total teams:

| Setting                   | Value  | Effect                         |
| ------------------------- | ------ | ------------------------------ |
| `rollout_percentage`      | `0.01` | 3,000 teams selected (1%)      |
| `batch_size`              | `250`  | 12 batches created             |
| `max_concurrent`          | `2`    | Up to 2 batches run at a time  |
| `not_processed_threshold` | `0.1`  | Fails if >300 teams skip/error |

## ClickHouse query helper

`execute_clickhouse_health_team_query()` is a safe wrapper for running ClickHouse queries in health checks. It enforces a `%(team_ids)s` placeholder, applies conservative default settings, and handles parameter merging.

```python
from posthog.temporal.health_checks.query import execute_clickhouse_health_team_query

rows = execute_clickhouse_health_team_query(
    "SELECT team_id, count() FROM events WHERE team_id IN %(team_ids)s GROUP BY team_id",
    team_ids=team_ids,
    lookback_days=7,       # optional, available as %(lookback_days)s
    params={"event": "$pageview"},  # additional query params
    settings={"max_execution_time": 60},  # override ClickHouse settings
)
```

| Parameter       | Type                        | Default | Description                                                          |
| --------------- | --------------------------- | ------- | -------------------------------------------------------------------- |
| `sql`           | `str`                       | —       | SQL with a `%(team_ids)s` placeholder (validated, raises if missing) |
| `team_ids`      | `list[int]`                 | —       | Team IDs to query. Returns `[]` immediately if empty                 |
| `lookback_days` | `int \| None`               | `None`  | If set, available as `%(lookback_days)s` in SQL. Must be > 0         |
| `params`        | `Mapping[str, Any] \| None` | `None`  | Extra query params. Cannot override `team_ids` or `lookback_days`    |
| `settings`      | `Mapping[str, Any] \| None` | `None`  | ClickHouse settings overrides                                        |

Default ClickHouse settings: `max_execution_time=30`, `max_threads=2`.

## ClickHouse kill switch

Health checks are automatically skipped when the ClickHouse kill switch is active (LIGHT or FULL).
The `get_team_id_batches` activity returns an empty list, and the workflow completes with `total_teams: 0`.

## Admin UI

Health checks can be triggered manually from the Django admin at `/admin/health_checks/`. Staff access is required. The trigger form allows overriding:

- **dry_run** — run detection without writing to the database
- **batch_size** — teams per batch (1–10,000)
- **max_concurrent** — concurrent batch activities (1–20)
- **rollout_percentage** — fraction of teams to process (0.01–1.0)
- **team_ids** — comma-separated list to target specific teams

The admin also shows recent workflow runs with links to the Temporal UI.
