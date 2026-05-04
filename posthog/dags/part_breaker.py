"""
Automated ClickHouse Part Breaker

Finds oversized parts across sharded ClickHouse tables and breaks them into smaller
parts. Target workload is configurable via PART_BREAKER_WORKLOAD.

Tables to scan are configured via the PART_BREAKER_ELIGIBLE_TABLES env var
(comma-separated list of table names). If not set, the job logs a warning and exits.

The process per oversized part:
1. Create non-replicated staging tables if needed (SQL)
2. Pre-flight checks — disk space, no concurrent breaker, staging tables empty, replication healthy, no in-flight mutations (SQL)
3. Named FREEZE the partition containing the oversized part — creates hardlinks in shadow/<name>/ (SQL)
4. Copy the frozen part to source staging table's detached dir (SSH, hardlink or real copy via store/ paths)
5. ATTACH the part to source staging table (SQL)
6. INSERT SELECT from source staging → target staging (SQL, CH writes as smaller parts)
7. Verify target staging row count matches source staging (SQL)
8. ATTACH PARTITION FROM staging target → source table (SQL, CH handles block renumbering and replication)
9. Verify row delta matches staging target row count (SQL)
10. Wait for replication — polls all replicas' log_pointer via clusterAllReplicas(system.replicas) (SQL)
11. DROP PART — removes only the original oversized part (SQL)
12. Clean up — SYSTEM UNFREEZE BY NAME, truncate staging tables (SQL)

Safety properties:
- Source table is never missing data — new parts are attached BEFORE the oversized part is dropped
- Brief dedup window (step 10-11) is handled by ReplacingMergeTree — same data exists in old + new parts
- Parts are immutable — FREEZE creates a point-in-time snapshot, ongoing inserts don't affect the process
- Staging tables are non-replicated — no intermediate replication overhead
"""

import io
import re
import time
import uuid
import logging
from dataclasses import dataclass
from typing import Optional

from django.conf import settings

import dagster
import paramiko
from clickhouse_driver import Client

from posthog.clickhouse.client.connection import NodeRole, Workload
from posthog.clickhouse.cluster import ClickhouseCluster
from posthog.dags.common import JobOwners, skip_if_already_running
from posthog.dags.common.resources import PartBreakerClickhouseClusterResource

logger = logging.getLogger(__name__)


# -- Configuration --

STAGING_SOURCE_SUFFIX = "_part_breaker_src"
STAGING_TARGET_SUFFIX = "_part_breaker_tgt"

# Tables eligible for automated part breaking, configured via PART_BREAKER_ELIGIBLE_TABLES env var.
# Each must be a Replicated* engine (ReplicatedReplacingMergeTree, etc.).
# The staging tables will be created as non-replicated equivalents.
# Set as a comma-separated list in the environment, e.g.:
#   PART_BREAKER_ELIGIBLE_TABLES="table_a,table_b,table_c"
# If empty, the job will skip discovery and log a warning.

PART_BREAKER_RESOURCE_DEFS = {
    "cluster": PartBreakerClickhouseClusterResource(),
}


class PartBreakerConfig(dagster.Config):
    # Size threshold for "oversized" parts (GiB)
    max_part_size_gib: int = settings.PART_BREAKER_MAX_PART_SIZE_GIB

    # Minimum free disk space ratio required before starting
    min_free_space_multiplier: float = settings.PART_BREAKER_MIN_FREE_SPACE_MULTIPLIER

    # Maximum parts to process per run (across all tables)
    max_parts_per_run: int = settings.PART_BREAKER_MAX_PARTS_PER_RUN

    # Verification tolerance: count() difference allowed
    count_tolerance: float = settings.PART_BREAKER_COUNT_TOLERANCE

    # Which tables to scan (empty = all PART_BREAKER_ELIGIBLE_TABLES)
    tables: list[str] = []

    # Which shards to target (empty = all)
    target_shards: list[int] = []

    # Dry run mode: discover and report but don't break
    dry_run: bool = False


@dataclass
class PartStats:
    """Stats for a single part on a specific shard/table."""

    table: str
    shard_num: int
    partition_id: str
    part_name: str
    part_bytes: int
    part_rows: int

    @property
    def staging_source_table(self) -> str:
        return f"{self.table}{STAGING_SOURCE_SUFFIX}"

    @property
    def staging_target_table(self) -> str:
        return f"{self.table}{STAGING_TARGET_SUFFIX}"

    @property
    def part_gib(self) -> float:
        return self.part_bytes / (1024**3)


@dataclass
class BreakResult:
    """Result of breaking a single oversized part."""

    part: PartStats
    source_count: int = 0
    post_count: int = 0
    new_largest_part_gib: float = 0.0
    new_part_count: int = 0
    duration_seconds: float = 0.0
    dry_run: bool = False

    @property
    def count_diff_pct(self) -> float:
        if self.source_count == 0:
            return 0.0
        return abs(self.post_count - self.source_count) / self.source_count


# -- SSH helpers --


def _get_ssh_client(hostname: str) -> paramiko.SSHClient:
    """Create an SSH client connected to the given CH node.

    Uses the SSH key from CLICKHOUSE_SSH_PRIVATE_KEY env var (or falls back to
    PART_BREAKER_SSH_KEY_PATH for a file path). Connects as the user specified
    by PART_BREAKER_SSH_USER (default: ubuntu).
    """
    ssh = paramiko.SSHClient()
    ssh.set_missing_host_key_policy(paramiko.RejectPolicy())

    # Fetch the host key via paramiko transport.
    transport = paramiko.Transport((hostname, 22))
    transport.connect()
    host_key = transport.get_remote_server_key()
    transport.close()
    ssh.get_host_keys().add(hostname, host_key.get_name(), host_key)

    ssh_user = getattr(settings, "PART_BREAKER_SSH_USER", "ubuntu")

    # Key can be provided as a raw string (from K8s secret mount) or as a file path
    ssh_key = getattr(settings, "PART_BREAKER_SSH_KEY", None)
    ssh_key_path = getattr(settings, "PART_BREAKER_SSH_KEY_PATH", None)

    if ssh_key:
        # Raw key string — auto-detect key type (RSA, Ed25519, ECDSA)
        key_file = io.StringIO(ssh_key)
        pkey = None
        for key_class in (paramiko.Ed25519Key, paramiko.RSAKey, paramiko.ECDSAKey):
            try:
                key_file.seek(0)
                pkey = key_class.from_private_key(key_file)
                break
            except (paramiko.SSHException, ValueError):
                continue
        if pkey is None:
            raise dagster.Failure(
                description="Could not parse CLICKHOUSE_SSH_PRIVATE_KEY as any supported key type (Ed25519, RSA, ECDSA)"
            )
        ssh.connect(hostname, username=ssh_user, pkey=pkey, timeout=30)
    elif ssh_key_path:
        ssh.connect(hostname, username=ssh_user, key_filename=ssh_key_path, timeout=30)
    else:
        raise dagster.Failure(
            description="No SSH key configured. Set CLICKHOUSE_SSH_PRIVATE_KEY (raw key) or "
            "PART_BREAKER_SSH_KEY_PATH (file path) env var."
        )

    return ssh


def _ssh_exec(ssh: paramiko.SSHClient, cmd: str, sudo: bool = True, timeout: int = 3600) -> str:
    """Execute a command over SSH and return stdout. Raises on non-zero exit.

    Default timeout is 1 hour — cp/mv of large parts (hundreds of GiB) can take minutes.
    SSH connects as PART_BREAKER_SSH_USER (default: ubuntu), so filesystem operations
    on clickhouse-owned files require sudo (enabled by default).
    """
    if sudo:
        cmd = f"sudo {cmd}"
    _stdin, stdout, stderr = ssh.exec_command(cmd, timeout=timeout)
    exit_code = stdout.channel.recv_exit_status()
    out = stdout.read().decode().strip()
    err = stderr.read().decode().strip()
    if exit_code != 0:
        raise dagster.Failure(description=f"SSH command failed (exit {exit_code}): {cmd}\nstderr: {err}\nstdout: {out}")
    return out


# -- SQL helper functions --


def _get_database() -> str:
    """Return the ClickHouse database name from settings."""
    return settings.CLICKHOUSE_DATABASE


def _discover_oversized_parts_on_host(
    client: Client,
    table: str,
    max_part_size_bytes: int,
) -> list[tuple]:
    """Query system.parts on a single host for individual oversized parts.

    Returns raw rows: (partition_id, name, bytes_on_disk, rows).
    """
    database = _get_database()
    return client.execute(
        """
        SELECT
            partition_id,
            name,
            bytes_on_disk,
            rows
        FROM system.parts
        WHERE database = %(database)s
            AND table = %(table)s
            AND active
            AND bytes_on_disk > %(max_size)s
        ORDER BY bytes_on_disk ASC
        """,
        {
            "database": database,
            "table": table,
            "max_size": max_part_size_bytes,
        },
    )


def _discover_oversized_parts(
    cluster: ClickhouseCluster,
    tables: list[str],
    max_part_size_bytes: int,
    target_shards: list[int],
) -> list[PartStats]:
    """Query system.parts across all shards for individual oversized parts.

    Runs the discovery query on one host per shard (via map_one_host_per_shard),
    then aggregates results with shard numbers from the HostInfo.
    """

    def _query_all_tables(client: Client) -> list[tuple]:
        """Query all eligible tables on this host, returning (table, ...row) tuples."""
        all_rows = []
        for table in tables:
            rows = _discover_oversized_parts_on_host(client, table, max_part_size_bytes)
            for row in rows:
                all_rows.append((table, *row))
        return all_rows

    # Query one host per shard — each returns its local oversized parts
    shard_results = cluster.map_one_host_per_shard(_query_all_tables).result()

    results = []

    for host_info, rows in shard_results.items():
        shard_num = host_info.shard_num
        if shard_num is None:
            continue

        # Filter by target shards if specified
        if target_shards and shard_num not in target_shards:
            continue

        for row in rows:
            (table, partition_id, part_name, part_bytes, part_rows) = row

            results.append(
                PartStats(
                    table=table,
                    shard_num=shard_num,
                    partition_id=partition_id,
                    part_name=part_name,
                    part_bytes=part_bytes,
                    part_rows=part_rows,
                )
            )

    return results


def _check_disk_space(client: Client, required_bytes: int, multiplier: float) -> tuple[bool, int]:
    """Check if any disk on the node can fit the new parts from the INSERT SELECT.

    ClickHouse can write new parts to any disk in the storage policy, so we check
    whether at least one disk has enough free space — not just the disk(s) currently
    holding this partition's data.

    Returns (has_enough, max_free_bytes_on_any_disk).
    """
    # Check the largest free space on any local disk — CH will use whichever has room.
    # Exclude ObjectStorage (S3) disks which report unlimited (max uint64) free space.
    space_result = client.execute("SELECT max(free_space) FROM system.disks WHERE type = 'Local'")
    if not isinstance(space_result, list) or not space_result or space_result[0][0] is None:
        return False, 0

    max_free_bytes: int = space_result[0][0]
    return max_free_bytes >= required_bytes * multiplier, max_free_bytes


def _check_no_active_breaker(client: Client, staging_source: str, staging_target: str) -> bool:
    """Check that no other part breaker INSERT SELECT is running for these staging tables."""
    database = _get_database()
    rows = client.execute(
        """
        SELECT count()
        FROM system.processes
        WHERE query LIKE %(pattern1)s
           OR query LIKE %(pattern2)s
           OR query LIKE %(pattern3)s
           OR query LIKE %(pattern4)s
        """,
        {
            "pattern1": f"INSERT INTO {staging_target}%",
            "pattern2": f"INSERT INTO {database}.{staging_target}%",
            "pattern3": f"INSERT INTO {staging_source}%",
            "pattern4": f"INSERT INTO {database}.{staging_source}%",
        },
    )
    return rows[0][0] == 0


def _table_exists(client: Client, table: str) -> bool:
    """Check if a table exists."""
    database = _get_database()
    rows = client.execute(
        "SELECT count() FROM system.tables WHERE database = %(db)s AND name = %(table)s",
        {"db": database, "table": table},
    )
    return rows[0][0] > 0


def _check_staging_table_empty(client: Client, staging_table: str) -> bool:
    """Check that the staging table has no active parts."""
    database = _get_database()
    rows = client.execute(
        "SELECT count() FROM system.parts WHERE database = %(db)s AND table = %(table)s AND active",
        {"db": database, "table": staging_table},
    )
    return rows[0][0] == 0


def _check_replication_healthy(client: Client, source_table: str) -> bool:
    """Check that the replication queue is not backed up."""
    database = _get_database()
    rows = client.execute(
        "SELECT count() FROM system.replication_queue WHERE database = %(db)s AND table = %(table)s",
        {"db": database, "table": source_table},
    )
    return rows[0][0] < 100


def _parse_part_block_range(part_name: str) -> tuple[int, int]:
    """Parse (min_block, max_block) from a part name.

    Part names follow {partition_id}_{min_block}_{max_block}_{level}[_{mutation_version}].
    """
    pieces = part_name.split("_")
    return int(pieces[1]), int(pieces[2])


def _check_no_mutations_for_part(client: Client, source_table: str, partition_id: str, part_name: str) -> list[str]:
    """Return mutation_ids of in-progress mutations whose block range covers this part.

    A mutation's parts_to_do_names lists the exact part names still pending. If our
    part appears there, the mutation will rewrite it — unsafe to break.
    """
    database = _get_database()
    cluster = settings.CLICKHOUSE_CLUSTER
    rows = client.execute(
        "SELECT DISTINCT mutation_id "
        "FROM clusterAllReplicas(%(cluster)s, system.mutations) "
        "WHERE database = %(db)s AND table = %(table)s "
        "AND is_done = 0 "
        "AND has(parts_to_do_names, %(part)s)",
        {"cluster": cluster, "db": database, "table": source_table, "part": part_name},
    )
    return [row[0] for row in rows]


def _get_mutation_ids_for_part(client: Client, source_table: str, partition_id: str, part_name: str) -> set[str]:
    """Return mutation_ids (any status) targeting this specific part.

    A mutation includes our part iff both:
      - its block_numbers array has an entry for our partition_id, AND
      - that entry's block number is strictly greater than our part's min_block
        (ClickHouse: "Only parts that contain blocks with numbers less than this
        number will be mutated in the partition.")

    We also OR against parts_to_do_names for in-progress mutations, since their
    block_numbers logic still applies but parts_to_do_names is the authoritative
    live signal.
    """
    database = _get_database()
    cluster = settings.CLICKHOUSE_CLUSTER
    min_block, _ = _parse_part_block_range(part_name)
    rows = client.execute(
        "SELECT DISTINCT mutation_id "
        "FROM clusterAllReplicas(%(cluster)s, system.mutations) "
        "WHERE database = %(db)s AND table = %(table)s "
        "AND ("
        "  has(parts_to_do_names, %(part)s) "
        "  OR arrayExists("
        "    (pid, bnum) -> pid = %(partition_id)s AND bnum > %(min_block)s, "
        "    block_numbers.partition_id, block_numbers.number"
        "  )"
        ")",
        {
            "cluster": cluster,
            "db": database,
            "table": source_table,
            "part": part_name,
            "partition_id": partition_id,
            "min_block": min_block,
        },
    )
    return {row[0] for row in rows}


def _ensure_staging_table(client: Client, source_table: str, staging_table: str) -> None:
    """Drop any stale staging table and recreate from the current source schema.

    Always recreates so source-side ALTER TABLE additions don't cause
    "Tables have different structure" on ATTACH PARTITION FROM. Refuses to
    drop if the existing staging table is non-empty (likely leftover from a
    failed run that needs operator review).
    """
    database = _get_database()

    rows = client.execute(
        "SELECT total_bytes FROM system.tables WHERE database = %(db)s AND name = %(table)s",
        {"db": database, "table": staging_table},
    )
    if rows:
        existing_bytes = rows[0][0] or 0
        if existing_bytes > 0:
            raise dagster.Failure(
                description=f"Staging table {database}.{staging_table} is non-empty "
                f"({existing_bytes:,} bytes). Truncate manually after confirming nothing needs recovery."
            )
        client.execute(f"DROP TABLE {database}.{staging_table} SYNC")

    # Get the source engine definition to derive the non-replicated equivalent
    rows = client.execute(
        "SELECT engine_full FROM system.tables WHERE database = %(db)s AND name = %(table)s",
        {"db": database, "table": source_table},
    )
    if not rows:
        raise dagster.Failure(description=f"Source table {database}.{source_table} not found")

    engine_full = rows[0][0]

    # Extract non-replicated engine: strip Replicated prefix and ZK path/replica args
    # e.g. ReplicatedReplacingMergeTree('/path', '{replica}', _timestamp)
    #   → ReplacingMergeTree(_timestamp)
    def _strip_replication(m: re.Match) -> str:
        base_engine = m.group(1)  # e.g. "ReplacingMergeTree", "MergeTree"
        extra_args = m.group(2)  # e.g. "_timestamp" or None

        if base_engine == "MergeTree" or not extra_args:
            return f"{base_engine}()"
        return f"{base_engine}({extra_args})"

    engine_clause, count = re.subn(
        r"Replicated(\w+)\('[^']*',\s*'\{replica\}'(?:,\s*(.+?))?\)",
        _strip_replication,
        engine_full,
        count=1,
    )
    if count == 0:
        raise dagster.Failure(
            description=f"Source table {source_table} does not use a Replicated engine: {engine_full}"
        )

    # CREATE TABLE ... AS copies schema; ENGINE = overrides the engine only
    client.execute(f"CREATE TABLE {database}.{staging_table} AS {database}.{source_table} ENGINE = {engine_clause}")


def _get_disk_paths(client: Client) -> dict[str, str]:
    """Get all disk base paths keyed by disk name.

    Returns a dict of disk name → base path.
    """
    rows = client.execute("SELECT name, path FROM system.disks")
    if not rows:
        raise dagster.Failure(description="Could not determine ClickHouse disk paths from system.disks")
    return {row[0]: row[1].rstrip("/") + "/" for row in rows}


def _get_table_store_path(client: Client, table: str, disk_path: str) -> str:
    """Get the store-based data path for a table on a specific disk.

    ClickHouse stores table data under store/{prefix}/{uuid}/ rather than
    data/{database}/{table}/. The data/ path is just a symlink layer.
    FREEZE snapshots use the real store/ paths, so we must use them too.

    Queries system.tables for data_paths and matches against the given disk's
    base path to find the correct store path on that disk.

    Returns the store path for the table on the given disk.
    """
    database = _get_database()
    rows = client.execute(
        "SELECT data_paths FROM system.tables WHERE database = %(db)s AND name = %(table)s",
        {"db": database, "table": table},
    )
    if not rows or not rows[0][0]:
        raise dagster.Failure(description=f"Could not find data_paths for {database}.{table}")

    # data_paths is an Array(String) — one entry per disk in the storage policy.
    # Match the entry that starts with the target disk's base path.
    for path in rows[0][0]:
        if path.startswith(disk_path.rstrip("/") + "/") or path.startswith(disk_path):
            return path.rstrip("/") + "/"

    raise dagster.Failure(
        description=f"No data_path for {database}.{table} on disk at {disk_path}. Available paths: {rows[0][0]}"
    )


def _get_table_primary_disk(client: Client, table: str) -> str:
    """Get the primary disk for a table's storage policy.

    Queries system.storage_policies to find the first disk in the first volume
    of the table's storage policy. This is the disk where new parts are written
    and where staging tables (created with the same schema) will live.
    Returns the primary disk name from the table's storage policy.
    """
    database = _get_database()
    # Get the table's storage policy, then find the first disk in that policy
    rows = client.execute(
        "SELECT storage_policy FROM system.tables WHERE database = %(db)s AND name = %(table)s",
        {"db": database, "table": table},
    )
    if rows and rows[0][0]:
        policy_name = rows[0][0]
        disk_rows = client.execute(
            "SELECT disks FROM system.storage_policies "
            "WHERE policy_name = %(policy)s ORDER BY volume_priority ASC LIMIT 1",
            {"policy": policy_name},
        )
        if disk_rows and disk_rows[0][0]:
            # disks is an Array(String) — first element is the primary disk
            return disk_rows[0][0][0]

    # Fallback: use the first disk from system.disks (alphabetical)
    rows = client.execute("SELECT name FROM system.disks ORDER BY name LIMIT 1")
    if rows:
        return rows[0][0]
    return "default"


def _get_part_disk(client: Client, table: str, part_name: str) -> str:
    """Get the disk name where a specific part lives.

    Returns the disk name where the part is stored.
    """
    database = _get_database()
    rows = client.execute(
        "SELECT disk_name FROM system.parts "
        "WHERE database = %(db)s AND table = %(table)s AND name = %(part)s AND active",
        {"db": database, "table": table, "part": part_name},
    )
    if not rows:
        raise dagster.Failure(description=f"Part {part_name} not found in {database}.{table}")
    return rows[0][0]


def _run_insert_select(client: Client, source_table: str, target_table: str) -> str:
    """Run INSERT SELECT from source staging table into target staging table.

    No WHERE clause needed — the source staging table contains exactly one
    part (the oversized one). ClickHouse will write it as multiple smaller parts.

    Returns the query_id for monitoring.
    """
    database = _get_database()
    query_id = str(uuid.uuid4())

    client.execute(
        f"""
        INSERT INTO {database}.{target_table}
        SELECT * FROM {database}.{source_table}
        """,
        query_id=query_id,
    )
    return query_id


def _get_staging_stats(client: Client, staging_table: str, partition_id: str) -> tuple[int, int, float]:
    """Get count, part count, and largest part size from staging table.

    Returns (row_count, part_count, largest_part_gib).
    """
    database = _get_database()
    count_rows = client.execute(f"SELECT count() FROM {database}.{staging_table}")
    row_count = count_rows[0][0]

    parts_rows = client.execute(
        "SELECT count() AS part_count, max(bytes_on_disk) AS largest_bytes "
        "FROM system.parts "
        "WHERE database = %(db)s AND table = %(table)s AND active AND partition_id = %(partition_id)s",
        {"db": database, "table": staging_table, "partition_id": partition_id},
    )
    part_count = parts_rows[0][0]
    largest_bytes = parts_rows[0][1] if parts_rows[0][1] else 0
    largest_gib = largest_bytes / (1024**3)

    return row_count, part_count, largest_gib


def _wait_for_replication(
    client: Client, source_table: str, target_log_index: int, shard_num: int, max_wait: int = 0
) -> None:
    """Wait for ALL replicas to process past a specific replication log index.

    After ATTACHing new parts, we capture the current log_max_index and pass it here.
    This function waits until every active replica's log_pointer >= that index, meaning
    they have all fetched the new parts. Only then is it safe to DROP the old part.

    This handles active ingestion correctly — we don't need replicas to be fully
    caught up with everything, just past the point where our ATTACHes were recorded.

    Uses clusterAllReplicas() to query system.replicas across all nodes via a single
    connection — avoids querying internal ZooKeeper state directly.
    """
    if max_wait <= 0:
        max_wait = settings.PART_BREAKER_MAX_REPLICATION_WAIT_TIME

    database = _get_database()
    cluster = settings.CLICKHOUSE_CLUSTER

    behind_replicas: list[str] = []
    first_poll = True
    start = time.time()
    while time.time() - start < max_wait:
        # Query all replicas across the cluster, scoped to this shard via getMacro('shard').
        # clusterAllReplicas returns rows for ALL shards, but log_pointer values differ
        # per shard — we only care about replicas on the same shard.
        rows = client.execute(
            f"SELECT replica_name, log_pointer, is_session_expired "
            f"FROM clusterAllReplicas(%(cluster)s, system.replicas) "
            f"WHERE database = %(db)s AND table = %(table)s "
            f"AND getMacro('shard') = %(shard)s",
            {"cluster": cluster, "db": database, "table": source_table, "shard": str(shard_num)},
        )

        if not rows:
            raise dagster.Failure(
                description=f"No replicas found for {source_table} via clusterAllReplicas — "
                "cannot safely verify replication before dropping the old part"
            )

        # Filter to active replicas (session not expired)
        active = [(name, pointer) for name, pointer, expired in rows if not expired]
        inactive = [name for name, _, expired in rows if expired]

        if inactive:
            logger.info(f"Skipping {len(inactive)} inactive replica(s): {', '.join(inactive)}")

        if not active:
            raise dagster.Failure(
                description=f"No active replicas found for {source_table} — cannot verify replication"
            )

        if first_poll:
            logger.info(f"Waiting for {len(active)} active replica(s) to reach log index {target_log_index}...")
            first_poll = False

        all_synced = True
        behind_replicas = []
        for replica_name, log_pointer in active:
            if log_pointer < target_log_index:
                all_synced = False
                behind_replicas.append(
                    f"{replica_name} (at {log_pointer}, need {target_log_index}, "
                    f"{target_log_index - log_pointer} behind)"
                )

        if all_synced:
            logger.info(f"All {len(active)} replicas have reached log index {target_log_index}")
            return

        elapsed = int(time.time() - start)
        logger.info(f"Waiting for replicas to sync: {', '.join(behind_replicas)} ({elapsed}s elapsed)")
        time.sleep(30)

    raise dagster.Failure(
        description=f"Not all replicas reached log index {target_log_index} within {max_wait}s "
        f"for {source_table}. Behind: {', '.join(behind_replicas)}"
    )


def _truncate_staging(client: Client, staging_table: str) -> None:
    """Truncate the staging table."""
    database = _get_database()
    client.execute(
        f"TRUNCATE TABLE IF EXISTS {database}.{staging_table}",
        settings={"max_table_size_to_drop": "0"},
    )


# -- Dagster Ops --


@dagster.op(out=dagster.DynamicOut())
def discover_oversized_parts(
    context: dagster.OpExecutionContext,
    config: PartBreakerConfig,
    cluster: dagster.ResourceParam[ClickhouseCluster],
):
    """Find all individual oversized parts across the cluster."""
    max_size_bytes = config.max_part_size_gib * 1024**3
    tables = config.tables if config.tables else settings.PART_BREAKER_ELIGIBLE_TABLES

    if not tables:
        context.log.warning(
            "No eligible tables configured. Set PART_BREAKER_ELIGIBLE_TABLES env var "
            "as a comma-separated list of table names."
        )
        return

    # Query one host per shard to discover oversized parts across all tables
    parts = _discover_oversized_parts(
        cluster,
        tables,
        max_size_bytes,
        config.target_shards,
    )

    context.log.info(f"Found {len(parts)} oversized parts across the cluster")

    for p in parts:
        context.log.info(
            f"  {p.table} shard {p.shard_num}, partition {p.partition_id}: "
            f"part {p.part_name} ({p.part_gib:.1f} GiB, {p.part_rows:,} rows)"
        )

    # Pick 1 part per shard (smallest first — faster, lower risk),
    # then cap at max_parts_per_run total.
    parts.sort(key=lambda p: p.part_bytes)
    seen_shards: set[int] = set()
    selected: list[PartStats] = []
    for p in parts:
        if p.shard_num in seen_shards:
            continue
        seen_shards.add(p.shard_num)
        selected.append(p)
        if len(selected) >= config.max_parts_per_run:
            break
    parts = selected

    for p in parts:
        yield dagster.DynamicOutput(
            p,
            mapping_key=f"{p.table}_shard_{p.shard_num}_{p.part_name}",
        )


@dagster.op(out=dagster.Out(metadata={}))
def break_part(
    context: dagster.OpExecutionContext,
    config: PartBreakerConfig,
    cluster: dagster.ResourceParam[ClickhouseCluster],
    part: PartStats,
) -> Optional[BreakResult]:
    """Break a single oversized part on its shard's target node.

    Uses the freeze → copy → attach → INSERT SELECT → detach → move → attach → drop
    pattern to safely break the part without any window of missing data.
    """
    shard = part.shard_num
    partition_id = part.partition_id
    source_table = part.table
    staging_source = part.staging_source_table
    staging_target = part.staging_target_table
    database = _get_database()

    context.log.info(
        f"Processing {source_table} shard {shard}, part {part.part_name} "
        f"({part.part_gib:.1f} GiB, {part.part_rows:,} rows)"
    )

    if config.dry_run:

        def _dry_run(client: Client) -> None:
            """Run pre-flight checks and report what would happen without modifying anything."""
            context.log.info("DRY RUN — running pre-flight checks only, no modifications will be made")

            # Check disk space
            has_space, free_bytes = _check_disk_space(client, part.part_bytes, config.min_free_space_multiplier)
            free_gib = free_bytes / (1024**3)
            required_gib = part.part_gib * config.min_free_space_multiplier
            if has_space:
                context.log.info(f"  Disk space: OK ({free_gib:.1f} GiB free, need {required_gib:.1f} GiB)")
            else:
                context.log.warning(
                    f"  Disk space: INSUFFICIENT ({free_gib:.1f} GiB free, need {required_gib:.1f} GiB)"
                )

            # Check for active breaker
            no_active = _check_no_active_breaker(client, staging_source, staging_target)
            context.log.info(f"  No active breaker: {'OK' if no_active else 'BLOCKED — another INSERT SELECT running'}")

            # Check staging tables
            src_empty = (
                _check_staging_table_empty(client, staging_source) if _table_exists(client, staging_source) else True
            )
            tgt_empty = (
                _check_staging_table_empty(client, staging_target) if _table_exists(client, staging_target) else True
            )
            context.log.info(
                f"  Staging source ({staging_source}): "
                f"{'empty' if src_empty else 'NOT EMPTY — would truncate'}"
                f"{' (does not exist — would create)' if not _table_exists(client, staging_source) else ''}"
            )
            context.log.info(
                f"  Staging target ({staging_target}): "
                f"{'empty' if tgt_empty else 'NOT EMPTY — would truncate'}"
                f"{' (does not exist — would create)' if not _table_exists(client, staging_target) else ''}"
            )

            # Check replication health
            repl_ok = _check_replication_healthy(client, source_table)
            context.log.info(f"  Replication health: {'OK' if repl_ok else 'UNHEALTHY — queue > 100 entries'}")

            # Check in-flight mutations targeting this specific part
            blocking_mutations = _check_no_mutations_for_part(client, source_table, partition_id, part.part_name)
            context.log.info(
                f"  In-flight mutations for {part.part_name}: "
                f"{'OK (none)' if not blocking_mutations else f'BLOCKED ({len(blocking_mutations)} targeting this part: {blocking_mutations})'}"
            )

            # Get disk/path info
            disk_paths = _get_disk_paths(client)
            part_disk = _get_part_disk(client, source_table, part.part_name)
            primary_disk = _get_table_primary_disk(client, source_table)
            copy_method = (
                "hardlink (cp -rl)"
                if part_disk == primary_disk
                else f"real copy (cp -r, part on '{part_disk}', staging on '{primary_disk}')"
            )
            context.log.info(f"  Part disk: '{part_disk}' ({disk_paths[part_disk]})")
            context.log.info(f"  Primary disk: '{primary_disk}' ({disk_paths[primary_disk]})")
            context.log.info(f"  Copy method: {copy_method}")

            # Get host info
            host_rows = client.execute("SELECT hostName()")
            context.log.info(f"  Target host: {host_rows[0][0]}")

            # Replication status
            cluster_name = settings.CLICKHOUSE_CLUSTER
            replica_rows = client.execute(
                f"SELECT replica_name, log_pointer, log_max_index, is_session_expired "
                f"FROM clusterAllReplicas(%(cluster)s, system.replicas) "
                f"WHERE database = %(db)s AND table = %(table)s "
                f"AND getMacro('shard') = %(shard)s",
                {"cluster": cluster_name, "db": database, "table": source_table, "shard": str(shard)},
            )
            context.log.info(f"  Replicas for shard {shard}:")
            for rname, rpointer, rmax, rexpired in replica_rows:
                status = "EXPIRED" if rexpired else "active"
                behind = rmax - rpointer if rmax > rpointer else 0
                context.log.info(
                    f"    {rname}: log_pointer={rpointer}, log_max_index={rmax}, behind={behind}, status={status}"
                )

            # Summary
            context.log.info(
                f"  WOULD DO: FREEZE partition {partition_id} → {copy_method} → "
                f"INSERT SELECT {part.part_gib:.1f} GiB ({part.part_rows:,} rows) → "
                f"ATTACH PARTITION FROM staging → wait for replication → DROP {part.part_name}"
            )

        workload = Workload[settings.PART_BREAKER_WORKLOAD]
        try:
            cluster.map_any_host_in_shards_by_role(
                {shard: _dry_run},
                node_role=NodeRole.DATA,
                workload=workload,
            ).result()
        except Exception:
            context.log.exception(f"Dry run failed for {source_table} shard {shard}, part {part.part_name}")
        return BreakResult(part=part, dry_run=True)

    start_time = time.time()

    def _process(client: Client) -> BreakResult:
        # -- Step 1: Ensure both staging tables exist --
        context.log.info(f"Ensuring staging tables exist ({staging_source}, {staging_target})...")
        _ensure_staging_table(client, source_table, staging_source)
        _ensure_staging_table(client, source_table, staging_target)

        ssh: paramiko.SSHClient | None = None
        freeze_name: str | None = None
        # Track source-table side effects so the except block can surface incomplete state.
        attach_partition_from_succeeded = False
        original_part_dropped = False

        try:
            # -- Step 2: Pre-flight checks --
            context.log.info("Running pre-flight checks...")

            has_space, free_bytes = _check_disk_space(client, part.part_bytes, config.min_free_space_multiplier)
            if not has_space:
                free_gib = free_bytes / (1024**3)
                required_gib = part.part_gib * config.min_free_space_multiplier
                raise dagster.Failure(
                    description=f"Insufficient disk space: {free_gib:.1f} GiB free, "
                    f"need {required_gib:.1f} GiB (part is {part.part_gib:.1f} GiB)"
                )

            if not _check_no_active_breaker(client, staging_source, staging_target):
                raise dagster.Failure(description="Another part breaker INSERT SELECT is already running")

            if not _check_staging_table_empty(client, staging_source):
                context.log.warning(f"Staging source {staging_source} not empty — truncating")
                _truncate_staging(client, staging_source)
            if not _check_staging_table_empty(client, staging_target):
                context.log.warning(f"Staging target {staging_target} not empty — truncating")
                _truncate_staging(client, staging_target)

            if not _check_replication_healthy(client, source_table):
                raise dagster.Failure(description=f"Replication queue is backed up (>100 entries) for {source_table}")

            blocking_mutations = _check_no_mutations_for_part(client, source_table, partition_id, part.part_name)
            if blocking_mutations:
                raise dagster.Failure(
                    description=f"{len(blocking_mutations)} in-progress mutation(s) target part "
                    f"{part.part_name} on {source_table}: {blocking_mutations}. "
                    f"Part breaker would risk data inconsistency — skipping."
                )

            # Capture mutation_ids at start so we can detect any new mutations that
            # cover this specific part during our run (even ones that start AND complete
            # between FREEZE and ATTACH).
            baseline_mutation_ids = _get_mutation_ids_for_part(client, source_table, partition_id, part.part_name)

            # -- Setup: Get paths and establish SSH connection --
            disk_paths = _get_disk_paths(client)
            part_disk = _get_part_disk(client, source_table, part.part_name)
            part_disk_path = disk_paths[part_disk]

            # Find the primary disk — the first disk in the storage policy (where staging tables live).
            # Primary disk from the table's storage policy.
            primary_disk = _get_table_primary_disk(client, source_table)
            primary_disk_path = disk_paths[primary_disk]

            # Get the store-based path for staging source on the primary disk.
            # ClickHouse uses store/{prefix}/{uuid}/ layout — the data/{db}/{table}/ paths
            # are just symlinks and FREEZE snapshots use the real store/ paths.
            staging_src_store_path = _get_table_store_path(client, staging_source, primary_disk_path)
            staging_src_detached = f"{staging_src_store_path}detached/"

            context.log.info(
                f"Part {part.part_name} is on disk '{part_disk}' ({part_disk_path}), "
                f"primary disk is '{primary_disk}' ({primary_disk_path})"
            )

            host_rows = client.execute("SELECT hostName()")
            hostname = host_rows[0][0]

            context.log.info(f"Connecting via SSH to {hostname}...")
            ssh = _get_ssh_client(hostname)

            # -- Step 3: FREEZE the partition --
            # FREEZE creates hardlinks in shadow/ on the SAME disk as the part.
            # Use a named backup so we can UNFREEZE by name later.
            freeze_name = f"part_breaker_{part.part_name}_{time.strftime('%Y%m%d%H%M%S')}"
            context.log.info(f"Freezing partition {partition_id} on {source_table} (backup: {freeze_name})...")
            client.execute(
                f"ALTER TABLE {database}.{source_table} FREEZE PARTITION '{partition_id}' WITH NAME '{freeze_name}'"
            )

            # Named FREEZE creates shadow/<name>/ under the part's disk base path.
            # FREEZE snapshots use the real store/ layout, not the data/ symlink layer.
            # e.g. /data/nvme/shadow/part_breaker_XXX/store/f1c/f1c2e1b7-.../202511_.../
            shadow_backup_path = f"{part_disk_path}shadow/{freeze_name}/"

            # Verify the shadow backup directory exists
            _ssh_exec(ssh, f"test -d {shadow_backup_path}")
            context.log.info(f"Frozen to {shadow_backup_path}")

            # Get the source table's store path on the part's disk to construct the shadow path.
            # Shadow mirrors the store/ layout: shadow/<name>/store/{prefix}/{uuid}/{part_name}/
            source_store_on_part_disk = _get_table_store_path(client, source_table, part_disk_path)
            # Extract the relative store path (e.g. "store/f1c/f1c2e1b7-.../")
            relative_store_path = source_store_on_part_disk.replace(part_disk_path, "")
            frozen_part_path = f"{shadow_backup_path}{relative_store_path}{part.part_name}/"

            # Verify the frozen part exists
            _ssh_exec(ssh, f"test -d {frozen_part_path}")

            # -- Step 4: Copy frozen part to staging source's detached dir --
            # Use cp -rl (hardlink) if part is on the same disk as staging tables (primary disk),
            # cp -r (real copy) if cross-filesystem.
            # FREEZE creates shadow on the part's disk; staging tables live on the primary disk.
            # detached/ dir already exists (created by CH when the table is created).
            context.log.info(f"Copying frozen part to {staging_src_detached}...")
            if part_disk == primary_disk:
                _ssh_exec(ssh, f"cp -rl {frozen_part_path} {staging_src_detached}{part.part_name}/")
            else:
                context.log.info(f"Part is on '{part_disk}' disk (staging on '{primary_disk}'), using real copy")
                _ssh_exec(ssh, f"cp -r {frozen_part_path} {staging_src_detached}{part.part_name}/")
            # cp as root creates directories owned by root — fix ownership so CH can read them
            _ssh_exec(ssh, f"chown -R clickhouse:clickhouse {staging_src_detached}{part.part_name}/")

            # -- Step 5: ATTACH the part to staging source --
            context.log.info(f"Attaching part {part.part_name} to {staging_source}...")
            client.execute(f"ALTER TABLE {database}.{staging_source} ATTACH PART '{part.part_name}'")

            # Verify attach — count rows in staging source
            source_count_rows = client.execute(f"SELECT count() FROM {database}.{staging_source}")
            source_count = source_count_rows[0][0]
            context.log.info(f"Staging source: {source_count:,} rows (part had {part.part_rows:,} physical rows)")

            if source_count == 0:
                raise dagster.Failure(description=f"Staging source {staging_source} has 0 rows after ATTACH PART")

            # -- Step 6: INSERT SELECT from staging source → staging target --
            context.log.info(
                f"Starting INSERT SELECT: {staging_source} → {staging_target} "
                f"({part.part_gib:.1f} GiB, {source_count:,} rows)..."
            )
            query_id = _run_insert_select(client, staging_source, staging_target)
            context.log.info(f"INSERT SELECT complete (query_id: {query_id})")

            # -- Step 7: Verify staging target --
            context.log.info("Verifying staging target...")
            target_count, target_parts, target_largest_gib = _get_staging_stats(client, staging_target, partition_id)
            context.log.info(
                f"Staging target: {target_count:,} rows in {target_parts} parts (largest: {target_largest_gib:.1f} GiB)"
            )

            # Verify count is within tolerance (dedup may reduce slightly)
            if source_count > 0:
                diff_pct = abs(target_count - source_count) / source_count
                if diff_pct > config.count_tolerance:
                    raise dagster.Failure(
                        description=f"Target count {target_count:,} differs from source {source_count:,} "
                        f"by {diff_pct:.2%} (tolerance: {config.count_tolerance:.2%}). "
                        f"Investigate before retrying."
                    )

            # Check that parts are actually smaller
            if target_largest_gib > config.max_part_size_gib:
                context.log.warning(
                    f"Target's largest part ({target_largest_gib:.1f} GiB) still exceeds threshold "
                    f"({config.max_part_size_gib} GiB). INSERT SELECT may not have broken sufficiently."
                )

            # Pre-attach row count, excluding the old part by prefix (not exact name) so a
            # mid-flight mutation renaming the old part can't slip past the filter.
            old_part_prefix = "_".join(part.part_name.split("_")[:3])
            pre_attach_rows = client.execute(
                "SELECT sum(rows) FROM system.parts "
                "WHERE database = %(db)s AND table = %(table)s AND active "
                "AND partition_id = %(partition_id)s "
                "AND NOT startsWith(name, %(prefix)s)",
                {"db": database, "table": source_table, "partition_id": partition_id, "prefix": old_part_prefix},
            )
            pre_attach_row_count = (pre_attach_rows[0][0] or 0) if pre_attach_rows else 0

            # Re-read staging row count right before ATTACH. Background merges on staging
            # (ReplacingMergeTree) can dedupe further between step 8 and now, making the
            # earlier target_count snapshot stale and triggering false failures.
            staging_rows_now = client.execute(
                "SELECT sum(rows) FROM system.parts "
                "WHERE database = %(db)s AND table = %(table)s AND active "
                "AND partition_id = %(partition_id)s",
                {"db": database, "table": staging_target, "partition_id": partition_id},
            )
            expected_added_rows = (staging_rows_now[0][0] or 0) if staging_rows_now else 0

            # Re-check for new mutations targeting our part. If any appeared, abort
            # before ATTACH — they'd have mutated the old part but not our staging data.
            current_mutation_ids = _get_mutation_ids_for_part(client, source_table, partition_id, part.part_name)
            new_mutation_ids = current_mutation_ids - baseline_mutation_ids
            if new_mutation_ids:
                raise dagster.Failure(
                    description=f"{len(new_mutation_ids)} new mutation(s) targeting part "
                    f"{part.part_name} appeared during part break on {source_table}: "
                    f"{sorted(new_mutation_ids)}. Aborting before ATTACH to avoid data inconsistency."
                )

            # -- Step 8: ATTACH PARTITION FROM staging target → source table.
            # ClickHouse handles block renumbering and replication internally,
            # avoiding the silent-skip behavior of per-part ATTACH where parts
            # whose block ranges don't fit existing state get filtered out
            # (CH's tryLoadPartsToAttach — see ClickHouse/ClickHouse PR 97040).
            context.log.info(f"Attaching partition {partition_id} from {staging_target} to {source_table}...")
            client.execute(
                f"ALTER TABLE {database}.{source_table} "
                f"ATTACH PARTITION '{partition_id}' FROM {database}.{staging_target}"
            )
            attach_partition_from_succeeded = True

            # -- Step 9: Verify row delta matches staging target row count.
            # Source row delta must be >= staging row count (concurrent inserts
            # only inflate it — the check is one-sided).
            post_attach_rows = client.execute(
                "SELECT sum(rows) FROM system.parts "
                "WHERE database = %(db)s AND table = %(table)s AND active "
                "AND partition_id = %(partition_id)s "
                "AND NOT startsWith(name, %(prefix)s)",
                {"db": database, "table": source_table, "partition_id": partition_id, "prefix": old_part_prefix},
            )
            post_attach_row_count = (post_attach_rows[0][0] or 0) if post_attach_rows else 0
            added_rows = post_attach_row_count - pre_attach_row_count
            if added_rows < expected_added_rows:
                raise dagster.Failure(
                    description=f"ATTACH PARTITION added {added_rows:,} rows but staging had "
                    f"{expected_added_rows:,} immediately before ATTACH. Skipping DROP to avoid data loss."
                )
            context.log.info(
                f"Safety check passed: ATTACH PARTITION added {added_rows:,} rows (expected: {expected_added_rows:,})"
            )

            # -- Step 10: Wait for replication before dropping.
            log_index_rows = client.execute(
                "SELECT log_max_index FROM system.replicas WHERE database = %(db)s AND table = %(table)s",
                {"db": database, "table": source_table},
            )
            if not log_index_rows or log_index_rows[0][0] is None:
                raise dagster.Failure(description=f"Could not get log_max_index for {source_table}")
            target_log_index = log_index_rows[0][0]

            context.log.info(
                f"Waiting for all replicas to reach log index {target_log_index} before dropping old part..."
            )
            _wait_for_replication(client, source_table, target_log_index, part.shard_num)
            context.log.info("Replication complete — all replicas have the new parts")

            # -- Step 11: DROP the original part (re-query by prefix, mutations change suffix).
            current_parts = client.execute(
                "SELECT name FROM system.parts "
                "WHERE database = %(db)s AND table = %(table)s AND active "
                "AND partition_id = %(partition_id)s "
                "AND name LIKE %(prefix_pattern)s",
                {
                    "db": database,
                    "table": source_table,
                    "partition_id": partition_id,
                    "prefix_pattern": f"{old_part_prefix}_%",
                },
            )

            if current_parts:
                if len(current_parts) > 1:
                    context.log.warning(
                        f"Found {len(current_parts)} parts matching prefix {old_part_prefix}: "
                        f"{[r[0] for r in current_parts]}. Dropping the first match."
                    )
                current_part_name = current_parts[0][0]

                # DROP PART requires a shard leader replica so we route the DROP
                # to a (leader-eligible) replica on the same shard.
                context.log.info(f"Dropping oversized part {current_part_name} from {source_table}...")
                try:
                    client.execute(
                        f"ALTER TABLE {database}.{source_table} DROP PART '{current_part_name}'",
                        settings={"max_partition_size_to_drop": "0"},
                    )
                    context.log.info(f"Dropped {current_part_name}")
                    original_part_dropped = True
                except Exception as drop_err:
                    if "not a leader" not in str(drop_err):
                        raise
                    context.log.info(f"Current replica is not a leader — routing DROP to an online replica...")

                    def _drop_on_leader(leader_client: Client) -> None:
                        leader_client.execute(
                            f"ALTER TABLE {database}.{source_table} DROP PART '{current_part_name}'",
                            settings={"max_partition_size_to_drop": "0"},
                        )

                    cluster.map_any_host_in_shards_by_role(
                        {shard: _drop_on_leader},
                        node_role=NodeRole.DATA,
                        workload=Workload.ONLINE,
                    ).result()
                    context.log.info(f"Dropped {current_part_name} (via leader replica)")
                    original_part_dropped = True
            else:
                context.log.warning(
                    f"Original oversized part (prefix {old_part_prefix}) not found in "
                    f"{source_table} partition {partition_id} — "
                    f"it may have been merged or dropped already. Skipping DROP PART."
                )
                original_part_dropped = True  # Already gone — nothing to reconcile.

            # Use the verified staging target stats from Step 7 — these reflect exactly
            # what we created, not the whole partition which includes unrelated parts.
            new_part_count = target_parts
            new_largest_gib = target_largest_gib
            post_count = target_count

            # -- Step 12: Clean up --
            context.log.info("Cleaning up staging tables...")
            _truncate_staging(client, staging_source)
            _truncate_staging(client, staging_target)

            # SYSTEM UNFREEZE cleans up files AND empty directories across all disks
            try:
                client.execute(f"SYSTEM UNFREEZE WITH NAME '{freeze_name}'")
            except Exception as e:
                context.log.warning(f"UNFREEZE failed (backup '{freeze_name}'): {e}")

        except Exception:
            # Clean up on failure to avoid leaking shadow disk space and staging data
            context.log.warning("Error during part break — cleaning up")

            # ATTACH succeeded but DROP didn't → reconciliation needed (see runbook).
            if attach_partition_from_succeeded and not original_part_dropped:
                context.log.exception(
                    f"Incomplete part break in {database}.{source_table} partition "
                    f"{partition_id} (shard {part.shard_num}, original part "
                    f"{part.part_name}). See runbooks."
                )

            if freeze_name is not None:
                try:
                    client.execute(f"SYSTEM UNFREEZE WITH NAME '{freeze_name}'")
                except Exception as e:
                    context.log.warning(f"Failed to UNFREEZE {freeze_name}: {e}")
            try:
                _truncate_staging(client, staging_source)
            except Exception as e:
                context.log.exception(f"Failed to truncate {staging_source}: {e}")
            try:
                _truncate_staging(client, staging_target)
            except Exception as e:
                context.log.exception(f"Failed to truncate {staging_target}: {e}")
            raise

        finally:
            if ssh:
                ssh.close()

        duration = time.time() - start_time

        return BreakResult(
            part=part,
            source_count=source_count,
            post_count=post_count,
            new_largest_part_gib=new_largest_gib,
            new_part_count=new_part_count,
            duration_seconds=duration,
        )

    # Catch all exceptions so a single shard failure doesn't kill the entire job.
    workload = Workload[settings.PART_BREAKER_WORKLOAD]
    try:
        result = cluster.map_any_host_in_shards_by_role(
            {shard: _process},
            node_role=NodeRole.DATA,
            workload=workload,
        ).result()
    except Exception:
        context.log.exception(
            f"Failed to break {source_table} shard {shard}, part {part.part_name} — will retry on next run"
        )
        return None

    # Extract the single result
    break_result = next(iter(result.values()))

    context.log.info(
        f"{break_result.part.table} shard {break_result.part.shard_num}, part {break_result.part.part_name}: "
        f"{break_result.part.part_gib:.1f} GiB → {break_result.new_largest_part_gib:.1f} GiB largest "
        f"({break_result.new_part_count} parts), "
        f"count {break_result.source_count:,} → {break_result.post_count:,} "
        f"(diff: {break_result.count_diff_pct:.2%}), "
        f"took {break_result.duration_seconds / 3600:.1f}h"
    )

    # Emit structured metadata for Dagster UI visibility
    context.add_output_metadata(
        {
            "table": break_result.part.table,
            "shard": break_result.part.shard_num,
            "partition": break_result.part.partition_id,
            "part_name": break_result.part.part_name,
            "old_part_gib": round(break_result.part.part_gib, 1),
            "new_largest_gib": round(break_result.new_largest_part_gib, 1),
            "new_part_count": break_result.new_part_count,
            "duration_hours": round(break_result.duration_seconds / 3600, 1),
            "count_diff_pct": round(break_result.count_diff_pct * 100, 2),
        }
    )

    return break_result


@dagster.op
def report_results(
    context: dagster.OpExecutionContext,
    results: list[Optional[BreakResult]],
):
    """Summarize the results of the part breaking run."""
    dry_runs = [r for r in results if r is not None and r.dry_run]
    completed = [r for r in results if r is not None and not r.dry_run]
    failed_count = len(results) - len(completed) - len(dry_runs)

    if dry_runs and not completed and failed_count == 0:
        context.log.info(f"DRY RUN complete — checked {len(dry_runs)} part(s), no modifications made")
        context.add_output_metadata({"parts_checked": len(dry_runs), "status": "dry_run"})
        return

    if not completed and failed_count == 0:
        context.log.info("No parts were processed (nothing to do)")
        context.add_output_metadata({"parts_processed": 0, "status": "no_work"})
        return

    context.log.info(
        f"Part breaker completed: {len(completed)} succeeded, {failed_count} failed out of {len(results)} part(s)"
    )
    for r in completed:
        context.log.info(
            f"  {r.part.table} shard {r.part.shard_num}, part {r.part.part_name}: "
            f"{r.part.part_gib:.1f} GiB → {r.new_largest_part_gib:.1f} GiB "
            f"({r.new_part_count} parts, {r.duration_seconds / 3600:.1f}h, "
            f"count diff: {r.count_diff_pct:.2%})"
        )

    total_gib = sum(r.part.part_gib for r in completed)
    total_hours = sum(r.duration_seconds for r in completed) / 3600
    context.add_output_metadata(
        {
            "succeeded": len(completed),
            "failed": failed_count,
            "total_gib_processed": round(total_gib, 1),
            "total_duration_hours": round(total_hours, 1),
        }
    )

    if failed_count > 0:
        raise dagster.Failure(
            description=f"{failed_count} part(s) failed out of {len(results)} — check individual op logs for details"
        )


# -- Dagster Job --


@dagster.job(
    tags={
        "owner": JobOwners.TEAM_CLICKHOUSE.value,
    },
    resource_defs=PART_BREAKER_RESOURCE_DEFS,
    executor_def=dagster.multiprocess_executor.configured({"max_concurrent": settings.PART_BREAKER_MAX_CONCURRENT}),
)
def break_oversized_parts():
    """Find and break oversized parts across sharded ClickHouse tables.

    Discovers individual parts larger than the configured threshold across all
    eligible tables, then breaks them using FREEZE → copy → INSERT SELECT →
    attach → DROP PART on each shard's target node.
    """
    parts = discover_oversized_parts()
    results = parts.map(break_part).collect()
    report_results(results)


# -- Schedule --
# Starts STOPPED — enable via the Dagster UI when ready.


@dagster.schedule(
    job=break_oversized_parts,
    cron_schedule=settings.PART_BREAKER_SCHEDULE,
    execution_timezone="UTC",
    default_status=dagster.DefaultScheduleStatus.STOPPED,
)
@skip_if_already_running
def break_oversized_parts_schedule(context: dagster.ScheduleEvaluationContext):
    return dagster.RunRequest()
