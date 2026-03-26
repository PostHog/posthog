# Health check framework

A framework for running scheduled health checks across PostHog teams. Define a detect function, call `create_health_check`, and the framework handles team batching, parallel execution, issue persistence, auto-resolution, rollout control, and Dagster observability.

Issues are written to the `posthog_healthissue` table and automatically resolved when a team passes a subsequent check run.

## Quick start

### 1. Write a detect function

A detect function receives a batch of team IDs and returns issues found:

```python
import dagster
from posthog.dags.common.health.types import HealthCheckResult
from posthog.models.health_issue import HealthIssue

def detect_stale_data(
    team_ids: list[int], context: dagster.OpExecutionContext
) -> dict[int, list[HealthCheckResult]]:
    # Your detection logic here — query ClickHouse, check state, etc.
    issues: dict[int, list[HealthCheckResult]] = {}

    stale_team_ids = find_teams_with_stale_data(team_ids)

    for team_id in stale_team_ids:
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

### 2. Create the health check

```python
from posthog.dags.common import JobOwners
from posthog.dags.common.health.detectors import batch_detector
from posthog.dags.common.health.framework import create_health_check

stale_data_check = create_health_check(
    name="stale_data",
    kind="stale_data",
    detector=batch_detector(detect_stale_data),
    owner=JobOwners.TEAM_WEB_ANALYTICS,
    schedule="0 * * * *",  # hourly
)
```

### 3. Register in a Dagster location

Add the job and schedule to a location file (e.g. `posthog/dags/locations/health.py`):

```python
import dagster
from . import resources

defs = dagster.Definitions(
    jobs=[stale_data_check.job],
    schedules=[s for s in [stale_data_check.schedule] if s],
    resources=resources,
)
```

If you skip the `schedule` parameter, the job can still be triggered manually from the Dagster UI.

## Detectors

A detector wraps your detect function and determines how the framework calls it and what execution defaults to use.

### `batch_detector`

Your function receives the full batch of team IDs at once. Best for checks that can evaluate many teams in a single operation (e.g. one SQL query).

```python
from posthog.dags.common.health.detectors import batch_detector

detector = batch_detector(detect_fn)
```

Spread a preset dict to control batching and concurrency:

```python
from posthog.dags.common.health.detectors import (
    CLICKHOUSE_BATCH_EXECUTION_POLICY,
    DEFAULT_EXECUTION_POLICY,
    batch_detector,
)

detector = batch_detector(detect_fn)  # uses DEFAULT_EXECUTION_POLICY values
detector = batch_detector(detect_fn, **CLICKHOUSE_BATCH_EXECUTION_POLICY)

# Override a single field from a preset
detector = batch_detector(detect_fn, **{**CLICKHOUSE_BATCH_EXECUTION_POLICY, "max_concurrent": 3})
```

**Signature:** `(team_ids: list[int], context: OpExecutionContext) -> dict[int, list[HealthCheckResult]]`

| Preset                              | batch_size | max_concurrent |
| ----------------------------------- | ---------- | -------------- |
| `DEFAULT_EXECUTION_POLICY`          | 1000       | 5              |
| `CLICKHOUSE_BATCH_EXECUTION_POLICY` | 250        | 1              |

## HealthCheckResult

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

## `create_health_check` reference

```python
create_health_check(
    name: str,
    kind: str,
    detector: HealthDetector,
    owner: JobOwners,
    *,
    team_ids: list[int] | None = None,
    schedule: str | None = None,
    batch_size: int | None = None,
    max_concurrent: int | None = None,
    rollout_percentage: float | None = None,
    not_processed_threshold: float = 0.1,
    dry_run: bool = False,
) -> HealthCheckDefinition
```

| Parameter                 | Type                | Default  | Description                                                                                                                                |
| ------------------------- | ------------------- | -------- | ------------------------------------------------------------------------------------------------------------------------------------------ |
| `name`                    | `str`               | required | Unique name used in Dagster op/job naming                                                                                                  |
| `kind`                    | `str`               | required | Issue kind written to the `posthog_healthissue` table. Must be globally unique                                                             |
| `detector`                | `HealthDetector`    | required | Detector wrapping your detect function                                                                                                     |
| `owner`                   | `JobOwners`         | required | Team that owns this check (used for Slack alert routing)                                                                                   |
| `team_ids`                | `list[int] \| None` | `None`   | Restrict to specific teams. `None` processes all teams                                                                                     |
| `schedule`                | `str \| None`       | `None`   | Cron expression (UTC). Omit for manual-only jobs                                                                                           |
| `batch_size`              | `int \| None`       | `None`   | Override detector default batch size                                                                                                       |
| `max_concurrent`          | `int \| None`       | `None`   | Override detector default concurrency                                                                                                      |
| `rollout_percentage`      | `float \| None`     | `None`   | Fraction of teams to include (0–1, e.g. 0.01 = 1%). Deterministic by team ID                                                               |
| `not_processed_threshold` | `float`             | `0.1`    | Fail the job if this fraction of teams are skipped or errored                                                                              |
| `dry_run`                 | `bool`              | `False`  | Run detection but skip DB writes (upsert/resolve). Sets the default for scheduled runs; can be overridden per-run in the Dagster launchpad |

**Returns** a `HealthCheckDefinition` with `.job` and `.schedule` attributes for Dagster registration.

## Configuration guide

### Batch size and concurrency

Teams are split into batches of `batch_size` IDs. Up to `max_concurrent` batches run in parallel as Dagster dynamic ops. Each batch has a retry policy (2 retries, exponential backoff with jitter).

Defaults depend on the detector's execution policy:

| Preset                              | batch_size | max_concurrent |
| ----------------------------------- | ---------- | -------------- |
| `DEFAULT_EXECUTION_POLICY`          | 1000       | 5              |
| `CLICKHOUSE_BATCH_EXECUTION_POLICY` | 250        | 1              |

Override at the `create_health_check` call site if needed.

### Rollout percentage

`rollout_percentage` deterministically selects a subset of teams using a SHA-256 hash of each team ID. The selection is stable across runs — the same teams are always included at the same percentage.

Use this to canary a new health check:

```python
# Start with 1% of teams
stale_data_check = create_health_check(
    ...
    rollout_percentage=0.01,
)

# Later, increase to 100%
```

At `rollout_percentage=1.0` (default when omitted), all teams are processed.

### Failure threshold

If more than `not_processed_threshold` (default 10%) of teams are skipped or errored, the entire job fails with `HealthCheckThresholdExceeded`. This catches detector bugs early — if your detect function is crashing for a large fraction of teams, the job alerts rather than silently resolving issues.

### Worked example

With 300,000 total teams:

| Setting                   | Value  | Effect                             |
| ------------------------- | ------ | ---------------------------------- |
| `rollout_percentage`      | `0.01` | 3,000 teams selected (1%)          |
| `batch_size`              | `250`  | 12 batches created                 |
| `max_concurrent`          | `2`    | Up to 2 batches run at a time      |
| `not_processed_threshold` | `0.1`  | Job fails if >300 teams skip/error |

## Component files

| File                           | Role                                                                                                                                      |
| ------------------------------ | ----------------------------------------------------------------------------------------------------------------------------------------- |
| `framework.py`                 | Builds Dagster jobs and schedules via `create_health_check`. Applies retry policy and concurrency. Emits per-batch and aggregate metadata |
| `detectors.py`                 | Detector constructors and execution policy resolution                                                                                     |
| `processing.py`                | Orchestrates detect → validate → upsert → resolve for each batch                                                                          |
| `db.py`                        | Converts `HealthCheckResult` into `HealthIssue` model writes                                                                              |
| `query.py`                     | ClickHouse query helper with safe defaults and placeholder validation                                                                     |
| `validation.py`                | Validates batch detector output (drops unknown team IDs, non-result items)                                                                |
| `types.py`                     | `HealthCheckResult`, `BatchResult`, type aliases                                                                                          |
| `../ops.py`                    | Team selection, deterministic rollout filtering, batch chunking                                                                           |
| `../../models/health_issue.py` | Django model with `bulk_upsert` and `bulk_resolve`                                                                                        |
