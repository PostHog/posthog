# Duckling Backfill System

This document describes the Dagster jobs and sensors for backfilling ClickHouse data to customer-specific "ducklings" - isolated DuckLake instances with their own RDS catalog and S3 bucket.

## Architecture

```text
DuckgresServer + DuckgresServerTeam (Django models)
    │ team_id → org's DuckgresServer (connection + bucket); DuckgresServerTeam gates enablement
    ▼
ClickHouse (events/person tables)
    │ export via s3() - bucket policy allows ClickHouse EC2 role
    ▼
Duckling S3 Bucket (parquet files)
    │ register via ducklake_add_data_files
    ▼
Duckling RDS Catalog (PostgreSQL)
```

### IAM Access

- **ClickHouse EC2 role**: Allowed in duckling bucket policy for direct S3 writes
- **Dagster IRSA role**: Can assume duckling cross-account roles for DuckDB registration

## Jobs and Sensors

### Events Backfill

| Component                               | Description                                         |
| --------------------------------------- | --------------------------------------------------- |
| `duckling_events_backfill`              | Asset that exports events for a team/date partition |
| `duckling_events_backfill_job`          | Job wrapping the asset                              |
| `duckling_events_daily_backfill_sensor` | Hourly sensor for yesterday's data (top-up)         |
| `duckling_events_full_backfill_sensor`  | Sensor for historical backfill (monthly batches)    |

### Persons Backfill

| Component                                | Description                                          |
| ---------------------------------------- | ---------------------------------------------------- |
| `duckling_persons_backfill`              | Asset that exports persons for a team/date partition |
| `duckling_persons_backfill_job`          | Job wrapping the asset                               |
| `duckling_persons_daily_backfill_sensor` | Hourly sensor for yesterday's data (top-up)          |
| `duckling_persons_full_backfill_sensor`  | Sensor for historical backfill (full export)         |

## Partition Strategy

Partitions use a composite key format: `{team_id}_{YYYY-MM-DD}`

Example: `12345_2024-01-15` for team 12345's data on January 15, 2024.

## Sensor Behavior

### Discovery Sensors (Hourly)

- Run every hour
- Create partitions for **yesterday's** data only
- Retry failed partitions automatically
- Skip partitions already in progress

### Full Backfill Sensors (Daily)

- Run once per day (controlled by cursor)
- Query ClickHouse for earliest event/person date per team
- Create up to 100 partitions per evaluation
- Progress through historical data day by day

## Managing Backfills

### Triggering a Manual Full Backfill

To run the full backfill immediately (without waiting for tomorrow):

1. Go to Dagster UI → Sensors
2. Find the relevant sensor (e.g., `duckling_events_full_backfill_sensor` or `duckling_persons_full_backfill_sensor`)
3. Click "Reset cursor"
4. The sensor will run on its next tick (within 60 seconds)

### Running a Specific Partition

1. Go to Dagster UI → Jobs → `duckling_events_backfill_job`
2. Click "Launchpad"
3. Select the partition (e.g., `12345_2024-01-15`)
4. Optionally configure:
   - `dry_run: true` - Preview without writing data
   - `skip_ducklake_registration: true` - Export to S3 only
   - `delete_tables: true` - Reset duckling tables first

### Resetting a Duckling

To completely reset a duckling's data and re-backfill:

1. Run a partition with `delete_tables: true` - this drops and recreates the tables
2. Reset the full backfill sensor cursor to trigger historical backfill
3. The sensor will recreate all partitions from the earliest date

## Configuration Options

```python
class DucklingBackfillConfig:
    clickhouse_settings: dict | None = None  # Custom ClickHouse settings
    skip_ducklake_registration: bool = False  # Export to S3 only
    skip_schema_validation: bool = False      # Skip pre-flight schema check
    cleanup_existing_partition_data: bool = True  # Delete existing DuckLake data before re-processing
    create_tables_if_missing: bool = True     # Auto-create events/persons tables
    delete_tables: bool = False               # DANGER: Drop and recreate tables
    dry_run: bool = False                     # Preview mode, no writes
```

## Adding a New Duckling

1. Provision (or create) the org's `DuckgresServer` (typically via the Django admin
   "Provision managed warehouse" action, which also records the team's
   `DuckgresServerTeam`). The relevant fields are:
   - `organization`: the org that owns the warehouse
   - `bucket` / `bucket_region`: S3 bucket name and AWS region
   - `catalog_host` / `catalog_database` / `catalog_username` / `catalog_password`: the
     DuckLake catalog RDS connection

   Ensure the runtime IAM role can read from and write to the configured S3 bucket.

2. Enable the team's backfill by creating its `DuckgresServerTeam` row with
   `backfill_enabled=True` (the provision / enable-backfill admin actions do this). The
   discovery sensor will then pick up the team on its next run.

3. To trigger immediate historical backfill, reset the full backfill sensor cursor

## Troubleshooting

### Partition stuck in "Running"

Check the Dagster run logs. Common issues:

- ClickHouse timeout: Increase `max_execution_time` in clickhouse_settings
- S3 permission denied: Verify bucket policy allows ClickHouse EC2 role
- RDS connection failed: Check VPC peering and security groups

### Schema mismatch warnings

The job logs warnings if the duckling table schema differs from expected columns. DuckLake's `ducklake_add_data_files` handles schema evolution automatically, so this is usually informational.

### Orphaned files in S3

Failed or re-run partitions may leave orphaned Parquet files in S3. These files are harmless - each run writes its files under a unique `{run_id}_` prefix, registration globs only that run's files, and the `cleanup_existing_partition_data` option clears the partition's DuckLake rows via DELETE before re-registering. A re-run therefore registers exactly its own fan-out (no duplicates, none missed); a prior run's physical files are simply no longer in the catalog. Do NOT delete S3 files that may have been registered with DuckLake, as this causes catalog corruption.

### Table creation race condition

If multiple partitions for the same team run concurrently, they may race to create tables. The code handles this gracefully - one worker creates the table, others detect it exists and continue.

## File Locations

- **Job definition**: `posthog/dags/events_backfill_to_duckling.py`
- **Tests**: `posthog/dags/test_events_backfill_to_duckling.py`
- **Dagster registration**: `posthog/dags/locations/data_stack.py`
- **DuckgresServer / DuckgresServerTeam models**: `posthog/ducklake/models.py`

## S3 Path Structure

Each export fans a partition out across many right-sized Parquet files (one per
ClickHouse `PARTITION BY` bucket) instead of one giant per-day object, so reads get
parallelism and per-file scans stay cheap. The fan-out is **computed per export** from
a cheap `count()` estimate — `ceil(row_count / target_rows_per_file)`, clamped to
`[1, max_s3_file_fanout]` — so a tens-of-millions-of-rows team-day spreads across many
~GB-scale files while a tiny team-day stays a single file. Both knobs are tunable per
run via `DucklingBackfillConfig` (`target_rows_per_file`, `max_s3_file_fanout`). The
`{_partition_id}` is the bucket id (`0 … fanout-1`); registration globs
`{run_id}_*.parquet` to enumerate every file a run produced.

```text
s3://{bucket}/backfill/events/{team_id}/year={year}/month={month}/day={day}/{run_id}_{_partition_id}.parquet
s3://{bucket}/backfill/persons/{team_id}/year={year}/month={month}/{run_id}_{_partition_id}.parquet
```
