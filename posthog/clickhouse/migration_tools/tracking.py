"""Advisory locking for concurrent apply prevention.

The tracking table is ReplicatedMergeTree ON CLUSTER so that every node
in the cluster sees the same lock/history rows. This prevents two
concurrent ``ch_migrate apply`` calls on different hosts from both
acquiring the advisory lock.
"""

import time
import logging
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Literal

TRACKING_TABLE_NAME = "clickhouse_schema_migrations"

TRACKING_TABLE_DDL = """
CREATE TABLE IF NOT EXISTS {database}.clickhouse_schema_migrations ON CLUSTER {cluster} (
    migration_number UInt32,
    migration_name String,
    step_index Int32,
    host String,
    node_role String,
    direction Enum8('up' = 1, 'down' = 2),
    checksum String,
    applied_at DateTime64(3),
    success Bool
) ENGINE = ReplicatedMergeTree('/clickhouse/tables/{{shard}}/{database}/clickhouse_schema_migrations', '{{replica}}')
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
    direction: Literal["up", "down"]
    checksum: str
    success: bool


def _ensure_tracking_table(client: Any, database: str, cluster: str = "posthog_migrations") -> None:
    """Create the tracking table on every node via ON CLUSTER (idempotent)."""
    client.execute(TRACKING_TABLE_DDL.format(database=database, cluster=cluster))


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


def acquire_apply_lock(
    client: Any,
    database: str,
    hostname: str,
    *,
    force: bool = False,
    cluster: str = "posthog_migrations",
) -> tuple[bool, str]:
    """Cluster-wide advisory lock via ReplicatedMergeTree INSERT.

    The tracking table is replicated across all nodes, so a lock row
    inserted on any host is visible to every other host after replication
    converges. We INSERT a lock row, wait briefly for replication, then
    verify no other host also acquired — if so, we back off.
    """
    _ensure_tracking_table(client, database, cluster)
    table_ref = f"{database}.{TRACKING_TABLE_NAME}"

    if not force:
        # Check for an existing active lock before attempting to insert.
        # A lock is "active" when a host's 'up' row is newer than that host's
        # own latest 'down' row (per-host scope). The JOIN is host-scoped so
        # that a loser releasing its own lock does not make the winner's lock
        # invisible via an unscoped max(applied_at) on the 'down' table.
        check_sql = f"""
            SELECT t.host, t.applied_at
            FROM {table_ref} AS t
            LEFT JOIN (
                SELECT host, max(applied_at) AS last_released
                FROM {table_ref}
                WHERE migration_number = {LOCK_MIGRATION_NUMBER}
                  AND step_index = {LOCK_STEP_INDEX}
                  AND direction = 'down'
                GROUP BY host
            ) AS d ON t.host = d.host
            WHERE t.migration_number = {LOCK_MIGRATION_NUMBER}
              AND t.step_index = {LOCK_STEP_INDEX}
              AND t.direction = 'up'
              AND t.success = 1
              AND t.applied_at > now() - INTERVAL {LOCK_TIMEOUT_MINUTES} MINUTE
              AND t.host != %(hostname)s
              AND t.applied_at > coalesce(d.last_released, toDateTime64('1970-01-01', 3))
            ORDER BY t.applied_at DESC
            LIMIT 1
        """
        existing = client.execute(check_sql, {"hostname": hostname})
        if existing:
            return (
                False,
                f"Another ch_migrate apply is running on {existing[0][0]} (started {existing[0][1]}). Use --force to override.",
            )

    # Insert the acquire record (always, whether forced or not)
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

    # Force replication convergence before the double-lock check. A fixed
    # sleep (0.5s, 5s, ...) is not a correctness barrier — under replication
    # lag each host can still see only its own insert. SYSTEM SYNC REPLICA
    # STRICT blocks until the local replica has drained its ZooKeeper
    # replication queue, so when we then SELECT we observe all peer inserts
    # that beat ours to the leader. Hosts that INSERT simultaneously will
    # disagree on the tie-break (applied_at, host) but both observe the same
    # sorted set and agree on the winner.
    try:
        client.execute(f"SYSTEM SYNC REPLICA {table_ref} STRICT")
    except Exception as e:
        # ClickHouse raises "Table ... is not replicated" (or similar) when
        # SYSTEM SYNC REPLICA runs against a plain MergeTree table (dev stack).
        # Silently fall through only for that case; re-raise everything else
        # (ZooKeeper unreachable, timeout, network partition) so the caller
        # aborts the acquire instead of proceeding without a replication barrier.
        if "is not replicated" not in str(e) and "NOT_IMPLEMENTED" not in str(e):
            raise
        # Non-replicated engine (dev only) — best-effort sleep. Safe because the
        # dev stack is single-host and cannot have competing apply processes.
        time.sleep(1)

    # Deterministic tie-break: earliest-applied wins, then lexicographic
    # hostname. Both callers sort the same rows identically regardless of
    # which one landed in the driver result first, so they agree on the
    # winner. Prior `ORDER BY applied_at DESC` let the winner flip when two
    # inserts landed in the same millisecond.
    # The 'down' subquery is host-scoped (LEFT JOIN GROUP BY host) so that a
    # race loser releasing its own lock cannot make the winner's 'up' row
    # invisible via an unscoped max(applied_at) across all hosts.
    verify_sql = f"""
        SELECT t.host, t.applied_at
        FROM {table_ref} AS t
        LEFT JOIN (
            SELECT host, max(applied_at) AS last_released
            FROM {table_ref}
            WHERE migration_number = {LOCK_MIGRATION_NUMBER}
              AND step_index = {LOCK_STEP_INDEX}
              AND direction = 'down'
            GROUP BY host
        ) AS d ON t.host = d.host
        WHERE t.migration_number = {LOCK_MIGRATION_NUMBER}
          AND t.step_index = {LOCK_STEP_INDEX}
          AND t.direction = 'up'
          AND t.success = 1
          AND t.applied_at > now() - INTERVAL {LOCK_TIMEOUT_MINUTES} MINUTE
          AND t.applied_at > coalesce(d.last_released, toDateTime64('1970-01-01', 3))
        ORDER BY t.applied_at ASC, t.host ASC
    """
    active = client.execute(verify_sql)
    if not active:
        # Unexpected: our own INSERT should be visible after SYNC REPLICA.
        # Most likely cause is extreme clock skew pushing the row outside the
        # LOCK_TIMEOUT_MINUTES window. Log and proceed cautiously — the caller
        # holds the lock as far as it can tell; a subsequent acquire on another
        # host will see no competition and also proceed (correctness degraded).
        logging.getLogger(__name__).warning(
            "ch_migrate: verify returned no active lock rows after INSERT — possible clock skew on %s",
            hostname,
        )
        return (True, "")
    if len(active) > 1 and active[0][0] != hostname:
        if force:
            # --force skips the pre-check but still runs SYNC+verify so we can
            # detect competing apply runs. Log the override; don't back off.
            logging.getLogger(__name__).warning("ch_migrate --force: overriding lock held by %s", active[0][0])
            return (True, "")
        # Race: another host won. Release and back off.
        release_apply_lock(client, database, hostname)
        return (
            False,
            f"Race detected — lock held by {active[0][0]}. Use --force to override.",
        )

    return (True, "")


# Schema version sentinel: records which git commit was last applied.
VERSION_STEP_INDEX = -2


def record_schema_version(client: Any, database: str, commit_hash: str, hostname: str) -> None:
    """Record the git commit hash of the schema YAML that was just applied.

    Precondition: the tracking table must already exist. In the normal
    acquire → apply → record_schema_version → release flow this is
    guaranteed because acquire_apply_lock calls _ensure_tracking_table.
    If called in isolation (e.g. a future CLI subcommand), call
    _ensure_tracking_table first.
    """
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
    """Return (commit_hash, host, applied_at) of the last applied schema version, or None.

    Precondition: the tracking table must already exist (see record_schema_version).
    """
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
    """Release the advisory lock by inserting a direction='down' row.

    The acquire logic checks for 'up' rows whose applied_at exceeds the
    latest 'down' row — this release row makes the lock invisible.
    """
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
            success=True,
        ),
        database=database,
    )
