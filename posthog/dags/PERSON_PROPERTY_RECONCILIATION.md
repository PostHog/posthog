# Person Property Reconciliation Job

This document provides a comprehensive overview of the person property reconciliation job, including architecture diagrams, parameter reference, and example configurations.

For detailed query explanations, see [person_property_reconciliation_query_explanation.md](person_property_reconciliation_query_explanation.md).

## Overview

The reconciliation job fixes person properties that were missed due to a bug where `PERSON_BATCH_WRITING_DB_WRITE_MODE=ASSERT_VERSION` caused `updatePersonAssertVersion()` to not properly merge properties.

The job:

1. Reads events from ClickHouse to find property updates (`$set`, `$set_once`, `$unset`) within a bug window
2. Compares with current person properties in ClickHouse
3. Applies any missed updates to Postgres
4. Publishes updated persons to Kafka for ClickHouse ingestion

## Architecture

### Non-Windowed Mode (Default)

Best for: Smaller teams or short bug windows where a single ClickHouse query can handle the data.

```text
┌─────────────────────────────────────────────────────────────────────────────┐
│                           Non-Windowed Flow                                  │
└─────────────────────────────────────────────────────────────────────────────┘

    ┌──────────────────────────────────────────────────────────────────┐
    │  ClickHouse: Single Query                                         │
    │  ┌────────────────────────────────────────────────────────────┐  │
    │  │ get_person_property_updates_from_clickhouse()              │  │
    │  │                                                             │  │
    │  │ • Scans events from bug_window_start to now()              │  │
    │  │ • Joins with person_distinct_id_overrides (merge handling) │  │
    │  │ • Joins with person table for current state                │  │
    │  │ • Computes diffs IN SQL (efficient)                        │  │
    │  │ • Returns only persons with actual differences             │  │
    │  └────────────────────────────────────────────────────────────┘  │
    └──────────────────────────────────────────────────────────────────┘
                                    │
                                    ▼
                    ┌───────────────────────────────┐
                    │ filter_event_person_properties │
                    │ (resolve set/unset conflicts)  │
                    └───────────────────────────────┘
                                    │
                                    ▼
                    ┌───────────────────────────────┐
                    │ process_persons_in_batches     │
                    │ • Update Postgres              │
                    │ • Publish to Kafka             │
                    │ • Commit in batches            │
                    └───────────────────────────────┘
```

### Windowed Batched Mode

Best for: Large teams with millions of persons where a single query would OOM.

```text
┌─────────────────────────────────────────────────────────────────────────────┐
│                        Windowed Batched Flow                                 │
└─────────────────────────────────────────────────────────────────────────────┘

    ┌──────────────────────────────────────────────────────────────────┐
    │  Step 1: Identify Affected Persons (BOUNDED)                      │
    │  ┌────────────────────────────────────────────────────────────┐  │
    │  │ get_affected_person_ids_from_clickhouse()                  │  │
    │  │                                                             │  │
    │  │ • Scans events from bug_window_start to bug_window_end     │  │
    │  │ • Returns ONLY distinct person_ids (not full data)         │  │
    │  │ • Bounded query = predictable result size                  │  │
    │  └────────────────────────────────────────────────────────────┘  │
    └──────────────────────────────────────────────────────────────────┘
                                    │
                                    ▼
    ┌──────────────────────────────────────────────────────────────────┐
    │  Step 2: Process Persons in Batches (~10K each)                   │
    │                                                                   │
    │  FOR EACH person_batch (chunk of ~10K person_ids):               │
    │                                                                   │
    │  ┌────────────────────────────────────────────────────────────┐  │
    │  │  Step 2a: Windowed Event Aggregation                       │  │
    │  │                                                             │  │
    │  │  FOR EACH time_window (1 hour chunks from start to now): │  │
    │  │    • Query events filtered to this batch's person_ids      │  │
    │  │    • Merge into batch accumulator (timestamp-based)        │  │
    │  └────────────────────────────────────────────────────────────┘  │
    │                          │                                        │
    │                          ▼                                        │
    │  ┌────────────────────────────────────────────────────────────┐  │
    │  │  Step 2b: Compare with Person State                        │  │
    │  │                                                             │  │
    │  │  • Query current person properties from ClickHouse         │  │
    │  │  • Filter to actual diffs (set: value differs, etc.)       │  │
    │  └────────────────────────────────────────────────────────────┘  │
    │                          │                                        │
    │                          ▼                                        │
    │  ┌────────────────────────────────────────────────────────────┐  │
    │  │  Step 2c: Process & Commit Batch                           │  │
    │  │                                                             │  │
    │  │  • Filter set/unset conflicts                              │  │
    │  │  • Update Postgres                                         │  │
    │  │  • Publish to Kafka                                        │  │
    │  │  • Commit transaction                                      │  │
    │  │  • Clear memory for next batch                             │  │
    │  └────────────────────────────────────────────────────────────┘  │
    │                                                                   │
    │  END FOR EACH person_batch                                        │
    └──────────────────────────────────────────────────────────────────┘
```

### Why Windowed Batched Mode?

The key insight is that Step 1 uses `bug_window_end` to bound the set of affected persons, while Step 2 still reads events up to `now()` to capture all property updates for those persons.

This prevents the problem where the original windowed implementation accumulated ALL persons with events from `bug_window_start` to `now()` (potentially millions), causing OOM.

## Parameter Reference

### Job Configuration (`PersonPropertyReconciliationConfig`)

| Parameter                            | Type                | Default  | Description                                                              |
| ------------------------------------ | ------------------- | -------- | ------------------------------------------------------------------------ |
| `bug_window_start`                   | `str`               | Required | Start of bug window (ClickHouse format: "YYYY-MM-DD HH:MM:SS", UTC)      |
| `bug_window_end`                     | `str \| None`       | `None`   | End of bug window. Required if `team_ids` not supplied                   |
| `team_ids`                           | `list[int] \| None` | `None`   | Explicit list of team IDs to process                                     |
| `min_team_id`                        | `int \| None`       | `None`   | Minimum team_id (inclusive) for range scanning                           |
| `max_team_id`                        | `int \| None`       | `None`   | Maximum team_id (inclusive) for range scanning                           |
| `exclude_team_ids`                   | `list[int] \| None` | `None`   | Team IDs to exclude from processing                                      |
| `dry_run`                            | `bool`              | `False`  | Log changes without applying to Postgres                                 |
| `backup_enabled`                     | `bool`              | `True`   | Store before/after state in backup table                                 |
| `batch_size`                         | `int`               | `100`    | Commit Postgres transaction every N persons (0 = single commit)          |
| `teams_per_chunk`                    | `int`               | `100`    | Teams per k8s task (reduces pod overhead)                                |
| `team_ch_props_fetch_window_seconds` | `int`               | `0`      | **Mode selector**: 0 = non-windowed, >0 = windowed with N-second windows |
| `person_batch_size`                  | `int`               | `10000`  | Persons per batch in windowed mode (keeps IN clauses under limit)        |

### Sensor Configuration (`ReconciliationSchedulerConfig`)

The sensor automates launching multiple reconciliation jobs across teams.

| Parameter                            | Type                | Default                 | Description                               |
| ------------------------------------ | ------------------- | ----------------------- | ----------------------------------------- |
| **Team Selection**                   |                     |                         |                                           |
| `team_ids`                           | `list[int] \| None` | `None`                  | Explicit list of team IDs (Option 1)      |
| `range_start`                        | `int \| None`       | `None`                  | First team_id for range scan (Option 2)   |
| `range_end`                          | `int \| None`       | `None`                  | Last team_id for range scan (Option 2)    |
| **Concurrency**                      |                     |                         |                                           |
| `chunk_size`                         | `int`               | `1000`                  | Teams per job run                         |
| `max_concurrent_jobs`                | `int`               | `5`                     | Max reconciliation jobs at once (cap: 50) |
| `max_concurrent_tasks`               | `int`               | `10`                    | Max k8s pods per job (cap: 100)           |
| **Bug Window**                       |                     |                         |                                           |
| `bug_window_start`                   | `str`               | Required                | Start of bug window                       |
| `bug_window_end`                     | `str`               | Required                | End of bug window                         |
| **Processing**                       |                     |                         |                                           |
| `dry_run`                            | `bool`              | `False`                 | Log changes without applying              |
| `backup_enabled`                     | `bool`              | `True`                  | Store before/after state                  |
| `batch_size`                         | `int`               | `100`                   | Postgres commit batch size                |
| `teams_per_chunk`                    | `int`               | `100`                   | Teams per k8s task                        |
| `team_ch_props_fetch_window_seconds` | `int`               | `0`                     | Mode selector (0 = non-windowed)          |
| `person_batch_size`                  | `int`               | `10000`                 | Persons per batch in windowed mode        |
| **Resources**                        |                     |                         |                                           |
| `persons_db_env_var`                 | `str`               | `PERSONS_DB_WRITER_URL` | Env var for Postgres connection           |

## Example Sensor Cursor Configurations

Set the sensor cursor in Dagster UI to one of these JSON configurations.

### Non-Windowed Mode (Small Teams)

Best for teams with < 100K affected persons or short bug windows.

```json
{
  "team_ids": [123, 456, 789],
  "bug_window_start": "2026-01-06 20:01:00",
  "bug_window_end": "2026-01-07 14:52:00",
  "team_ch_props_fetch_window_seconds": 0,
  "dry_run": true,
  "backup_enabled": true,
  "batch_size": 100
}
```

### Windowed Batched Mode (Large Teams)

Best for teams with 100K+ affected persons. Uses 1-hour windows and 10K person batches.

```json
{
  "team_ids": [2],
  "bug_window_start": "2026-01-06 20:01:00",
  "bug_window_end": "2026-01-07 14:52:00",
  "team_ch_props_fetch_window_seconds": 3600,
  "person_batch_size": 10000,
  "dry_run": true,
  "backup_enabled": true,
  "batch_size": 100
}
```

### Range-Based Scanning (All Teams)

Process all teams in a team_id range, in chunks.

```json
{
  "range_start": 1,
  "range_end": 100000,
  "chunk_size": 1000,
  "bug_window_start": "2026-01-06 20:01:00",
  "bug_window_end": "2026-01-07 14:52:00",
  "team_ch_props_fetch_window_seconds": 0,
  "max_concurrent_jobs": 5,
  "max_concurrent_tasks": 10,
  "dry_run": false
}
```

### Production Run with Windowed Mode

Full production configuration for a large team.

```json
{
  "team_ids": [2],
  "bug_window_start": "2026-01-06 20:01:00",
  "bug_window_end": "2026-01-07 14:52:00",
  "team_ch_props_fetch_window_seconds": 3600,
  "person_batch_size": 10000,
  "dry_run": false,
  "backup_enabled": true,
  "batch_size": 100,
  "teams_per_chunk": 1,
  "max_concurrent_jobs": 1,
  "max_concurrent_tasks": 1
}
```

## Choosing the Right Mode

| Scenario                     | Recommended Mode | Config                                     |
| ---------------------------- | ---------------- | ------------------------------------------ |
| Small team (< 100K persons)  | Non-windowed     | `team_ch_props_fetch_window_seconds: 0`    |
| Short bug window (< 1 day)   | Non-windowed     | `team_ch_props_fetch_window_seconds: 0`    |
| Large team (100K+ persons)   | Windowed batched | `team_ch_props_fetch_window_seconds: 3600` |
| Long bug window (days/weeks) | Windowed batched | `team_ch_props_fetch_window_seconds: 3600` |
| Unknown size, being cautious | Windowed batched | Start with `dry_run: true`                 |

## Recommended Workflow

For a full reconciliation across all teams, use this two-pass approach:

### Pass 1: Non-Windowed Mode for Most Teams

Run the sensor with non-windowed mode to process the majority of teams quickly:

```json
{
  "range_start": 1,
  "range_end": 100000,
  "chunk_size": 1000,
  "bug_window_start": "2026-01-06 20:01:00",
  "bug_window_end": "2026-01-07 14:52:00",
  "team_ch_props_fetch_window_seconds": 0,
  "max_concurrent_jobs": 5,
  "max_concurrent_tasks": 10,
  "dry_run": false,
  "backup_enabled": true
}
```

This will complete successfully for most teams but may fail (OOM or timeout) for very large teams.

### Extract Failed Teams

Use the extraction script to identify which teams failed:

```bash
export DAGSTER_CLOUD_TOKEN="<your-user-token>"

# Extract failed teams from recent runs
python posthog/dags/scripts/extract_reconciliation_results.py \
    --org posthog \
    --deployment prod-us \
    --since "2026-01-27" \
    --until "2026-01-30" \
    --verbose \
    --output-csv failed_teams.csv

# The script outputs:
# - Summary of succeeded/failed teams
# - List of failed team IDs
# - CSV with error details for each failed team
```

See the script's `--help` for additional options (filter by status, specific run ID, etc.).

### Pass 2: Windowed Mode for Failed Teams

Re-run the sensor targeting only the failed teams using windowed batched mode:

```json
{
  "team_ids": [2, 15847, 23456],
  "bug_window_start": "2026-01-06 20:01:00",
  "bug_window_end": "2026-01-07 14:52:00",
  "team_ch_props_fetch_window_seconds": 3600,
  "person_batch_size": 10000,
  "max_concurrent_jobs": 1,
  "max_concurrent_tasks": 1,
  "dry_run": false,
  "backup_enabled": true,
  "teams_per_chunk": 1
}
```

Key differences for Pass 2:

- `team_ids`: Explicit list of failed teams from the extraction script
- `team_ch_props_fetch_window_seconds: 3600`: Enable windowed mode (1-hour windows)
- `person_batch_size: 10000`: Process persons in batches to avoid OOM
- `max_concurrent_jobs: 1` and `max_concurrent_tasks: 1`: Serialize for large teams
- `teams_per_chunk: 1`: One team per task for better isolation

If a team still fails, try reducing `person_batch_size` (e.g., 5000) or check the error logs for specific issues.

## Monitoring and Troubleshooting

### Logs to Watch

In windowed batched mode, look for these log patterns:

```text
# Step 1: Affected persons query
Querying affected persons: team_id={id}, bug_window=[{start}, {end}]
Found {N} affected persons for team_id={id}

# Step 2: Per-batch progress
Starting batched windowed processing: team_id={id}, {N} batches of ~10000 persons, ~{M} windows of 3600s each
Processing batch {n}/{total} for team_id={id}, {N} persons
Batch {n}: processed window {w}/{total_windows}, accumulated {N} persons
Batch {n}: comparing {N} persons against current state
Batch {n}: yielding {N} persons with diffs

# Completion
Completed team_id={id} (windowed batched): processed={N}, updated={M}, skipped={K}, person_batches={B}
```

### Error Logs

When failures occur, errors are logged via `logger.exception()` which includes the full stack trace. Look for these message patterns:

```text
# Failed to query affected persons
Failed to query affected persons for team_id={id}, bug_window=[{start}, {end}]
[full stack trace follows]

# Failed during a specific window query
Batch {n}: failed to query window {w}/{total} [{window_start}, {window_end}) for team_id={id}
[full stack trace follows]
Batch {n}: failed during windowed event collection for team_id={id} after {w} windows, accumulated {N} persons
[full stack trace follows]

# Failed during person state comparison
Batch {n}: failed to compare {N} persons against current state for team_id={id}
[full stack trace follows]
```

**Partial Progress**: If a failure occurs mid-processing, already-committed batches are persisted to Postgres and Kafka. The job will be marked as failed, but partial progress is saved.

### Common Issues

1. **OOM in windowed mode**: Reduce `person_batch_size` (e.g., 5000 instead of 10000)
2. **Query size exceeded**: The code handles this by batching person_ids, but if you see this error, reduce `person_batch_size`
3. **Slow progress**: Increase `team_ch_props_fetch_window_seconds` (e.g., 7200 for 2-hour windows) to reduce query count

### Metrics

The job emits these metrics to ClickHouse:

- `person_property_reconciliation_persons_processed_total`
- `person_property_reconciliation_persons_updated_total`
- `person_property_reconciliation_persons_skipped_total`
- `person_property_reconciliation_teams_succeeded_total`
- `person_property_reconciliation_teams_failed_total`
- `person_property_reconciliation_duration_seconds_total`
- `person_property_reconciliation_error` (on failures)

## Backup and Recovery

When `backup_enabled: true`, the job stores before/after state in `posthog_person_reconciliation_backup`:

- `job_id`: Dagster run ID
- `properties` / `properties_after`: Before/after JSON
- `version` / `version_after`: Before/after version numbers
- `pending_operations`: Array of operations that were applied

To restore a person to their pre-reconciliation state, use the companion job `person_property_reconciliation_restore.py`.
