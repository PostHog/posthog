"""Advisory locking for concurrent apply prevention."""

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

TRACKING_TABLE_NAME = "clickhouse_schema_migrations"

TRACKING_TABLE_DDL = """
CREATE TABLE IF NOT EXISTS {database}.clickhouse_schema_migrations (
    migration_number UInt32,
    migration_name String,
    step_index Int32,
    host String,
    node_role String,
    direction Enum8('up' = 1, 'down' = 2),
    checksum String,
    applied_at DateTime64(3),
    success Bool
) ENGINE = MergeTree()
ORDER BY (migration_number, step_index, host, direction, applied_at)
"""

# Advisory lock constants.
LOCK_MIGRATION_NUMBER = 0
LOCK_STEP_INDEX = -999
LOCK_TIMEOUT_MINUTES = 30


@dataclass
class StepRecord:
    migration_number: int
    migration_name: str
    step_index: int
    host: str
    node_role: str
    direction: str
    checksum: str
    success: bool


def _ensure_tracking_table(client: Any, database: str) -> None:
    """Create the tracking table if it doesn't exist (idempotent)."""
    client.execute(TRACKING_TABLE_DDL.format(database=database))


def _record_step(
    client: Any,
    record: StepRecord,
    database: str = "",
) -> None:
    table_ref = f"{database}.{TRACKING_TABLE_NAME}" if database else TRACKING_TABLE_NAME
    sql = f"""
        INSERT INTO {table_ref}
        (migration_number, migration_name, step_index, host, node_role, direction, checksum, applied_at, success)
        VALUES
    """
    now = datetime.now(tz=UTC)
    params = [
        (
            record.migration_number,
            record.migration_name,
            record.step_index,
            record.host,
            record.node_role,
            record.direction,
            record.checksum,
            now,
            record.success,
        )
    ]
    client.execute(sql, params)


def acquire_apply_lock(client: Any, database: str, hostname: str, *, force: bool = False) -> tuple[bool, str]:
    """Best-effort advisory lock via INSERT...SELECT WHERE NOT EXISTS. Returns (acquired, message).

    Auto-creates the tracking table if needed. Uses a single query to check
    for existing locks and insert, but MergeTree is eventually consistent —
    two concurrent pods could both acquire in the same merge cycle.
    Sufficient for single-deploy-at-a-time; use --force to break stale locks.
    """
    _ensure_tracking_table(client, database)
    table_ref = f"{database}.{TRACKING_TABLE_NAME}"

    if force:
        _record_step(
            client=client,
            record=StepRecord(
                migration_number=LOCK_MIGRATION_NUMBER,
                migration_name="__lock__",
                step_index=LOCK_STEP_INDEX,
                host=hostname,
                node_role="*",
                direction="up",
                checksum="lock",
                success=True,
            ),
            database=database,
        )
        return (True, "")

    # Atomic: INSERT only if no active lock from another host
    atomic_sql = f"""
        INSERT INTO {table_ref}
        (migration_number, migration_name, step_index, host, node_role, direction, checksum, applied_at, success)
        SELECT
            {LOCK_MIGRATION_NUMBER}, '__lock__', {LOCK_STEP_INDEX},
            %(hostname)s, '*', 'up', 'lock', now64(), 1
        WHERE NOT EXISTS (
            SELECT 1 FROM {table_ref}
            WHERE migration_number = {LOCK_MIGRATION_NUMBER}
              AND step_index = {LOCK_STEP_INDEX}
              AND success = 1
              AND applied_at > now() - INTERVAL {LOCK_TIMEOUT_MINUTES} MINUTE
              AND host != %(hostname)s
        )
    """
    client.execute(atomic_sql, {"hostname": hostname})

    # Verify we got the lock by checking if our row is the latest
    verify_sql = f"""
        SELECT host, applied_at
        FROM {table_ref}
        WHERE migration_number = {LOCK_MIGRATION_NUMBER}
          AND step_index = {LOCK_STEP_INDEX}
          AND success = 1
          AND applied_at > now() - INTERVAL {LOCK_TIMEOUT_MINUTES} MINUTE
        ORDER BY applied_at DESC
        LIMIT 1
    """
    rows = client.execute(verify_sql)
    if rows and rows[0][0] != hostname:
        lock_host = rows[0][0]
        lock_time = rows[0][1]
        return (
            False,
            f"Another ch_migrate apply is running on {lock_host} (started {lock_time}). Use --force to override.",
        )

    return (True, "")


# Schema version sentinel: records which git commit was last applied.
VERSION_STEP_INDEX = -2


def record_schema_version(client: Any, database: str, commit_hash: str, hostname: str) -> None:
    """Record the git commit hash of the schema YAML that was just applied."""
    _record_step(
        client=client,
        record=StepRecord(
            migration_number=LOCK_MIGRATION_NUMBER,
            migration_name=commit_hash,
            step_index=VERSION_STEP_INDEX,
            host=hostname,
            node_role="*",
            direction="up",
            checksum="version",
            success=True,
        ),
        database=database,
    )


def get_latest_schema_version(client: Any, database: str) -> tuple[str, str, str] | None:
    """Return (commit_hash, host, applied_at) of the last applied schema version, or None."""
    table_ref = f"{database}.{TRACKING_TABLE_NAME}"
    sql = f"""
        SELECT migration_name, host, applied_at
        FROM {table_ref}
        WHERE migration_number = {LOCK_MIGRATION_NUMBER}
          AND step_index = {VERSION_STEP_INDEX}
          AND success = 1
        ORDER BY applied_at DESC
        LIMIT 1
    """
    rows = client.execute(sql)
    if rows:
        return (rows[0][0], rows[0][1], str(rows[0][2]))
    return None


def release_apply_lock(client: Any, database: str, hostname: str) -> None:
    """Release the advisory lock by inserting a success=False row that shadows the lock."""
    _record_step(
        client=client,
        record=StepRecord(
            migration_number=LOCK_MIGRATION_NUMBER,
            migration_name="__lock__",
            step_index=LOCK_STEP_INDEX,
            host=hostname,
            node_role="*",
            direction="down",
            checksum="unlock",
            success=False,
        ),
        database=database,
    )
