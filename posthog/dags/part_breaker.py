"""
Automated ClickHouse Part Breaker

Finds oversized parts across sharded ClickHouse tables and breaks them into smaller
parts using INSERT SELECT + REPLACE PARTITION. Runs on offline nodes only.

Tables to scan are configured via the PART_BREAKER_ELIGIBLE_TABLES env var
(comma-separated list of table names). If not set, the job logs a warning and exits.

The process per partition:
1. Discover oversized parts across all shards
2. Pre-flight checks (disk space, no concurrent breaker, staging table empty)
3. Record baseline count()
4. INSERT SELECT from source table into staging table (creates smaller parts)
5. Verify staging table count matches baseline
6. REPLACE PARTITION atomically swaps data (no downtime, no double data)
7. Verify post-replace count matches baseline
8. Truncate staging table

Safety properties:
- Source table is never in a degraded state — all risk is in the staging table
- REPLACE PARTITION is atomic — either completes fully or not at all
- Staging table is non-replicated — no intermediate replication overhead
- Only targets OFFLINE workload nodes — no impact on online queries
"""

import time
import logging
from dataclasses import dataclass
from typing import Optional

from django.conf import settings

import dagster
from clickhouse_driver import Client

from posthog.clickhouse.client.connection import NodeRole, Workload
from posthog.clickhouse.cluster import ClickhouseCluster
from posthog.dags.common import JobOwners
from posthog.dags.common.resources import ClickhouseClusterResource

# -- Configuration --

STAGING_TABLE_SUFFIX = "_part_breaker"

PART_BREAKER_RESOURCE_DEFS = {
    "cluster": ClickhouseClusterResource(
        client_settings={
            "max_execution_time": "0",
            "max_memory_usage": "0",
            "receive_timeout": str(settings.PART_BREAKER_RECEIVE_TIMEOUT),
        }
    ),
}


class PartBreakerConfig(dagster.Config):
    # Size threshold for "oversized" parts (GiB)
    max_part_size_gib: int = settings.PART_BREAKER_MAX_PART_SIZE_GIB

    # Minimum free disk space ratio required before starting
    min_free_space_multiplier: float = settings.PART_BREAKER_MIN_FREE_SPACE_MULTIPLIER

    # Maximum partitions to process per run (across all tables)
    max_partitions_per_run: int = settings.PART_BREAKER_MAX_PARTITIONS_PER_RUN

    # Verification tolerance: count() difference allowed
    count_tolerance: float = settings.PART_BREAKER_COUNT_TOLERANCE

    # Only process partitions older than this many months
    # (avoids interfering with active ingestion)
    min_partition_age_months: int = settings.PART_BREAKER_MIN_PARTITION_AGE_MONTHS

    # Which tables to scan (empty = all ELIGIBLE_TABLES)
    tables: list[str] = []

    # Which shards to target (empty = all)
    target_shards: list[int] = []

    # Dry run mode: discover and report but don't break
    dry_run: bool = False


@dataclass
class OversizedPartition:
    """A partition on a specific shard/table that contains at least one oversized part."""

    table: str
    shard_num: int
    partition_id: str
    largest_part_name: str
    largest_part_bytes: int
    largest_part_rows: int
    total_partition_bytes: int
    total_partition_rows: int
    total_parts: int

    @property
    def staging_table(self) -> str:
        return f"{self.table}{STAGING_TABLE_SUFFIX}"

    @property
    def largest_part_gib(self) -> float:
        return self.largest_part_bytes / (1024**3)

    @property
    def total_partition_gib(self) -> float:
        return self.total_partition_bytes / (1024**3)


@dataclass
class BreakResult:
    """Result of breaking a single partition."""

    table: str
    shard_num: int
    partition_id: str
    baseline_count: int
    post_replace_count: int
    old_largest_part_gib: float
    new_largest_part_gib: float
    new_part_count: int
    duration_seconds: float

    @property
    def count_diff_pct(self) -> float:
        if self.baseline_count == 0:
            return 0.0
        return abs(self.post_replace_count - self.baseline_count) / self.baseline_count


# -- Helper functions --


def _get_database() -> str:
    """Return the ClickHouse database name from settings."""
    return settings.CLICKHOUSE_DATABASE


def _get_current_yyyymm() -> int:
    """Return current year-month as YYYYMM integer."""
    import datetime

    now = datetime.datetime.now(datetime.UTC)
    return now.year * 100 + now.month


def _partition_age_months(partition_id: str, current_yyyymm: int) -> int:
    """Return approximate age of a partition in months."""
    try:
        partition_yyyymm = int(partition_id)
    except ValueError:
        return 0

    current_year = current_yyyymm // 100
    current_month = current_yyyymm % 100
    part_year = partition_yyyymm // 100
    part_month = partition_yyyymm % 100

    return (current_year - part_year) * 12 + (current_month - part_month)


def _discover_oversized_partitions_on_host(
    client: Client,
    table: str,
    max_part_size_bytes: int,
) -> list[tuple]:
    """Query system.parts on a single host for partitions containing oversized parts.

    Returns raw rows: (partition_id, largest_part_name, largest_part_bytes,
    largest_part_rows, total_partition_bytes, total_partition_rows, total_parts).
    """
    database = _get_database()
    return client.execute(
        """
        SELECT
            partition_id,
            argMax(name, bytes_on_disk) AS largest_part_name,
            max(bytes_on_disk) AS largest_part_bytes,
            argMax(rows, bytes_on_disk) AS largest_part_rows,
            sum(bytes_on_disk) AS total_partition_bytes,
            sum(rows) AS total_partition_rows,
            count() AS total_parts
        FROM system.parts
        WHERE database = %(database)s
            AND table = %(table)s
            AND active
        GROUP BY partition_id
        HAVING max(bytes_on_disk) > %(max_size)s
        ORDER BY max(bytes_on_disk) DESC
        """,
        {
            "database": database,
            "table": table,
            "max_size": max_part_size_bytes,
        },
    )


def _discover_oversized_partitions(
    cluster: ClickhouseCluster,
    tables: list[str],
    max_part_size_bytes: int,
    min_partition_age_months: int,
    target_shards: list[int],
) -> list[OversizedPartition]:
    """Query system.parts across all shards for partitions containing oversized parts.

    Runs the discovery query on one host per shard (via map_one_host_per_shard),
    then aggregates results with shard numbers from the HostInfo.
    Scans all specified tables.
    """

    def _query_all_tables(client: Client) -> list[tuple]:
        """Query all eligible tables on this host, returning (table, ...row) tuples."""
        all_rows = []
        for table in tables:
            rows = _discover_oversized_partitions_on_host(client, table, max_part_size_bytes)
            for row in rows:
                all_rows.append((table, *row))
        return all_rows

    # Query one host per shard — each returns its local oversized partitions
    shard_results = cluster.map_one_host_per_shard(_query_all_tables).result()

    current_yyyymm = _get_current_yyyymm()
    results = []

    for host_info, rows in shard_results.items():
        shard_num = host_info.shard_num
        if shard_num is None:
            continue

        # Filter by target shards if specified
        if target_shards and shard_num not in target_shards:
            continue

        for row in rows:
            (table, partition_id, largest_name, largest_bytes, largest_rows, total_bytes, total_rows, parts) = row

            # Filter by partition age
            age = _partition_age_months(partition_id, current_yyyymm)
            if age < min_partition_age_months:
                continue

            results.append(
                OversizedPartition(
                    table=table,
                    shard_num=shard_num,
                    partition_id=partition_id,
                    largest_part_name=largest_name,
                    largest_part_bytes=largest_bytes,
                    largest_part_rows=largest_rows,
                    total_partition_bytes=total_bytes,
                    total_partition_rows=total_rows,
                    total_parts=parts,
                )
            )

    return results


def _check_disk_space(
    client: Client, source_table: str, partition_id: str, required_bytes: int, multiplier: float
) -> tuple[bool, int]:
    """Check if the node has enough free disk space on the disk(s) holding this partition.

    Looks up which disk(s) the partition's active parts reside on, then sums
    the free space across those disks. This handles setups where data lives on
    disks named something other than 'default'.

    Returns (has_enough, free_bytes).
    """
    database = _get_database()
    # Find the distinct disk(s) this partition's parts live on
    disk_result = client.execute(
        "SELECT DISTINCT disk_name FROM system.parts "
        "WHERE database = %(db)s AND table = %(table)s AND active AND partition_id = %(partition_id)s",
        {"db": database, "table": source_table, "partition_id": partition_id},
    )
    if not isinstance(disk_result, list) or not disk_result:
        return False, 0

    disk_names = [row[0] for row in disk_result]
    # Sum free space across all disks holding this partition's data
    space_result = client.execute(
        "SELECT sum(free_space) FROM system.disks WHERE name IN %(disks)s",
        {"disks": disk_names},
    )
    if not isinstance(space_result, list) or not space_result or space_result[0][0] is None:
        return False, 0

    free_bytes: int = space_result[0][0]
    return free_bytes >= required_bytes * multiplier, free_bytes


def _check_no_active_breaker(client: Client, staging_table: str) -> bool:
    """Check that no other part breaker INSERT SELECT is running for this staging table."""
    database = _get_database()
    rows = client.execute(
        """
        SELECT count()
        FROM system.processes
        WHERE query LIKE %(pattern1)s
           OR query LIKE %(pattern2)s
        """,
        {
            "pattern1": f"INSERT INTO {staging_table}%",
            "pattern2": f"INSERT INTO {database}.{staging_table}%",
        },
    )
    return rows[0][0] == 0


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


def _ensure_staging_table(client: Client, source_table: str, staging_table: str) -> None:
    """Create the non-replicated staging table if it doesn't exist.

    Uses SHOW CREATE TABLE to get the exact DDL from ClickHouse, then rewrites
    the engine from Replicated* to its non-replicated equivalent and swaps the
    table name. This preserves all clauses (PARTITION BY, ORDER BY, SAMPLE BY,
    TTL, SETTINGS, etc.) exactly as the source table defines them, without
    fragile regex parsing of engine_full.
    """
    import re

    database = _get_database()

    # Check if staging table already exists
    rows = client.execute(
        "SELECT count() FROM system.tables WHERE database = %(db)s AND name = %(table)s",
        {"db": database, "table": staging_table},
    )
    if rows[0][0] > 0:
        return

    # Get the exact CREATE TABLE statement from ClickHouse
    result = client.execute(f"SHOW CREATE TABLE {database}.{source_table}")
    if not result or not isinstance(result, list):
        raise RuntimeError(f"Source table {database}.{source_table} not found")

    create_ddl: str = result[0][0]

    # Replace the table name
    create_ddl = create_ddl.replace(
        f"CREATE TABLE {database}.{source_table}",
        f"CREATE TABLE IF NOT EXISTS {database}.{staging_table}",
        1,
    )

    # Replace Replicated* engine with non-replicated equivalent.
    # SHOW CREATE TABLE outputs e.g.:
    #   ENGINE = ReplicatedReplacingMergeTree('/path', '{replica}', ver)
    # We need:
    #   ENGINE = ReplacingMergeTree(ver)
    #
    # The pattern matches: Replicated<Engine>('<zk_path>', '{replica}'[, extra_args])
    def _strip_replication(m: re.Match) -> str:
        base_engine = m.group(1)  # e.g., "ReplacingMergeTree", "MergeTree"
        extra_args = m.group(2)  # e.g., "ver" or None

        if base_engine == "MergeTree" or not extra_args:
            return f"{base_engine}()"
        return f"{base_engine}({extra_args})"

    create_ddl, count = re.subn(
        r"Replicated(\w+)\('[^']*',\s*'\{replica\}'(?:,\s*(.+?))?\)",
        _strip_replication,
        create_ddl,
        count=1,
    )
    if count == 0:
        raise RuntimeError(
            f"Source table {source_table} does not use a Replicated engine, cannot create non-replicated staging table"
        )

    client.execute(create_ddl)


def _get_partition_key_expr(client: Client, table: str) -> str:
    """Get the partition key expression for a table.

    Returns the expression used in WHERE clauses to filter by partition,
    e.g. 'toYYYYMM(timestamp)'.
    """
    database = _get_database()
    rows = client.execute(
        "SELECT partition_key FROM system.tables WHERE database = %(db)s AND name = %(table)s",
        {"db": database, "table": table},
    )
    if not rows or not rows[0][0]:
        raise RuntimeError(f"Could not determine partition key for {database}.{table}")
    return rows[0][0]


def _cast_partition_id(partition_id: str):
    """Cast partition_id to the appropriate type for WHERE clause comparison.

    YYYYMM partition IDs are numeric, but some tables may use string partitions.
    """
    try:
        return int(partition_id)
    except ValueError:
        return partition_id


def _get_baseline_count(client: Client, source_table: str, partition_key_expr: str, partition_id: str) -> int:
    """Get the logical row count for a partition."""
    database = _get_database()
    rows = client.execute(
        f"SELECT count() FROM {database}.{source_table} WHERE {partition_key_expr} = %(partition_id)s",
        {"partition_id": _cast_partition_id(partition_id)},
    )
    return rows[0][0]


def _run_insert_select(
    client: Client, source_table: str, staging_table: str, partition_key_expr: str, partition_id: str
) -> str:
    """Run INSERT SELECT from source table into staging table.

    Returns the query_id for monitoring.
    Settings (max_execution_time, max_memory_usage) are inherited from the
    cluster resource — no per-query overrides needed.
    """
    import uuid

    database = _get_database()
    query_id = str(uuid.uuid4())

    client.execute(
        f"""
        INSERT INTO {database}.{staging_table}
        SELECT * FROM {database}.{source_table}
        WHERE {partition_key_expr} = %(partition_id)s
        """,
        {"partition_id": _cast_partition_id(partition_id)},
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


def _replace_partition(client: Client, source_table: str, staging_table: str, partition_id: str) -> None:
    """Atomically replace the partition in the source table from the staging table."""
    database = _get_database()
    client.execute(
        f"ALTER TABLE {database}.{source_table} REPLACE PARTITION '{partition_id}' FROM {database}.{staging_table}"
    )


def _wait_for_replication(client: Client, source_table: str, max_wait: int | None = None) -> None:
    """Wait for replication queue to drain for the source table."""
    if max_wait is None:
        max_wait = settings.PART_BREAKER_MAX_REPLICATION_WAIT_TIME

    database = _get_database()
    start = time.time()
    while time.time() - start < max_wait:
        rows = client.execute(
            "SELECT count() FROM system.replication_queue WHERE database = %(db)s AND table = %(table)s",
            {"db": database, "table": source_table},
        )
        queue_size = rows[0][0]
        if queue_size == 0:
            return
        elapsed = int(time.time() - start)
        # Log progress so long waits are visible in the Dagster UI
        logging.getLogger(__name__).info(
            f"Replication queue for {source_table}: {queue_size} entries remaining ({elapsed}s elapsed)"
        )
        time.sleep(30)

    raise RuntimeError(f"Replication queue did not drain within {max_wait}s for {source_table}")


def _truncate_staging(client: Client, staging_table: str) -> None:
    """Truncate the staging table."""
    database = _get_database()
    client.execute(
        f"TRUNCATE TABLE {database}.{staging_table}",
        settings={"max_table_size_to_drop": "0"},
    )


# -- Dagster Ops --


@dagster.op(out=dagster.DynamicOut())
def discover_oversized_partitions(
    context: dagster.OpExecutionContext,
    config: PartBreakerConfig,
    cluster: dagster.ResourceParam[ClickhouseCluster],
):
    """Find all partitions with oversized parts across the cluster."""
    if config.max_part_size_gib < settings.PART_BREAKER_MIN_PART_SIZE_GIB_FLOOR:
        raise dagster.Failure(
            f"max_part_size_gib={config.max_part_size_gib} is below the minimum of {settings.PART_BREAKER_MIN_PART_SIZE_GIB_FLOOR} GiB. "
            f"This would flag too many partitions. Raise the threshold or adjust PART_BREAKER_MIN_PART_SIZE_GIB_FLOOR env var."
        )

    max_size_bytes = config.max_part_size_gib * 1024**3
    tables = config.tables if config.tables else settings.PART_BREAKER_ELIGIBLE_TABLES

    if not tables:
        context.log.warning(
            "No eligible tables configured. Set PART_BREAKER_ELIGIBLE_TABLES env var "
            "as a comma-separated list of table names."
        )
        return

    # Query one host per shard to discover oversized partitions across all tables
    partitions = _discover_oversized_partitions(
        cluster,
        tables,
        max_size_bytes,
        config.min_partition_age_months,
        config.target_shards,
    )

    context.log.info(f"Found {len(partitions)} oversized partitions across the cluster")

    for p in partitions:
        context.log.info(
            f"  {p.table} shard {p.shard_num}, partition {p.partition_id}: "
            f"largest part {p.largest_part_gib:.1f} GiB ({p.largest_part_name}), "
            f"total {p.total_partition_gib:.1f} GiB in {p.total_parts} parts"
        )

    # Pick 1 partition per shard (smallest first — faster, lower risk),
    # then cap at max_partitions_per_run total.
    partitions.sort(key=lambda p: p.largest_part_bytes)
    seen_shards: set[int] = set()
    selected: list[OversizedPartition] = []
    for p in partitions:
        if p.shard_num in seen_shards:
            continue
        seen_shards.add(p.shard_num)
        selected.append(p)
        if len(selected) >= config.max_partitions_per_run:
            break
    partitions = selected

    for p in partitions:
        yield dagster.DynamicOutput(
            p,
            mapping_key=f"{p.table}_shard_{p.shard_num}_partition_{p.partition_id}",
        )


@dagster.op(out=dagster.Out(metadata={}))
def break_partition(
    context: dagster.OpExecutionContext,
    config: PartBreakerConfig,
    cluster: dagster.ResourceParam[ClickhouseCluster],
    partition: OversizedPartition,
) -> Optional[BreakResult]:
    """Break a single oversized partition on its shard's offline node."""
    shard = partition.shard_num
    partition_id = partition.partition_id
    source_table = partition.table
    staging_table = partition.staging_table
    database = _get_database()

    context.log.info(
        f"Processing {source_table} shard {shard}, partition {partition_id} "
        f"(largest part: {partition.largest_part_gib:.1f} GiB, {partition.largest_part_name})"
    )

    if config.dry_run:
        context.log.info("DRY RUN — skipping actual processing")
        return None

    start_time = time.time()

    def _process(client: Client) -> BreakResult:
        # Step 1: Ensure staging table exists
        context.log.info(f"Ensuring staging table {staging_table} exists...")
        _ensure_staging_table(client, source_table, staging_table)

        try:
            # Step 2: Pre-flight checks
            context.log.info("Running pre-flight checks...")

            has_space, free_bytes = _check_disk_space(
                client, source_table, partition_id, partition.total_partition_bytes, config.min_free_space_multiplier
            )
            if not has_space:
                free_gib = free_bytes / (1024**3)
                required_gib = partition.total_partition_gib * config.min_free_space_multiplier
                raise RuntimeError(
                    f"Insufficient disk space: {free_gib:.1f} GiB free, "
                    f"need {required_gib:.1f} GiB (partition is {partition.total_partition_gib:.1f} GiB)"
                )

            if not _check_no_active_breaker(client, staging_table):
                raise RuntimeError(f"Another part breaker INSERT SELECT is already running for {staging_table}")

            if not _check_staging_table_empty(client, staging_table):
                context.log.warning(f"Staging table {staging_table} not empty — truncating before proceeding")
                _truncate_staging(client, staging_table)

            if not _check_replication_healthy(client, source_table):
                raise RuntimeError(f"Replication queue is backed up (>100 entries) for {source_table}")

            # Step 3: Get partition key expression and record baseline count
            partition_key_expr = _get_partition_key_expr(client, source_table)
            context.log.info(f"Partition key: {partition_key_expr}")

            context.log.info(f"Recording baseline count for partition {partition_id}...")
            baseline_count = _get_baseline_count(client, source_table, partition_key_expr, partition_id)
            context.log.info(f"Baseline count: {baseline_count:,}")

            if baseline_count == 0:
                raise RuntimeError(
                    f"Baseline count is 0 for {source_table} partition {partition_id} — nothing to process"
                )

            # Step 4: INSERT SELECT into staging table
            context.log.info(
                f"Starting INSERT SELECT for {source_table} partition {partition_id} "
                f"({partition.total_partition_gib:.1f} GiB, {partition.total_partition_rows:,} physical rows)..."
            )
            query_id = _run_insert_select(client, source_table, staging_table, partition_key_expr, partition_id)
            context.log.info(f"INSERT SELECT complete (query_id: {query_id})")

            # Step 5: Verify staging table
            context.log.info("Verifying staging table...")
            staging_count, staging_parts, staging_largest_gib = _get_staging_stats(client, staging_table, partition_id)
            context.log.info(
                f"Staging table: {staging_count:,} rows in {staging_parts} parts "
                f"(largest: {staging_largest_gib:.1f} GiB)"
            )

            # Verify count is within tolerance
            if baseline_count > 0:
                diff_pct = abs(staging_count - baseline_count) / baseline_count
                if diff_pct > config.count_tolerance:
                    _truncate_staging(client, staging_table)
                    raise RuntimeError(
                        f"Staging count {staging_count:,} differs from baseline {baseline_count:,} "
                        f"by {diff_pct:.2%} (tolerance: {config.count_tolerance:.2%}). "
                        f"Staging table truncated. Investigate before retrying."
                    )

            # Check that parts are actually smaller
            max_size_gib = config.max_part_size_gib
            if staging_largest_gib > max_size_gib:
                context.log.warning(
                    f"Staging table's largest part ({staging_largest_gib:.1f} GiB) "
                    f"still exceeds threshold ({max_size_gib} GiB). "
                    f"INSERT SELECT may not have broken the part sufficiently."
                )

            # Step 6: REPLACE PARTITION (atomic swap)
            context.log.info(f"Replacing partition {partition_id} in {source_table}...")
            _replace_partition(client, source_table, staging_table, partition_id)
            context.log.info("REPLACE PARTITION complete")

            # Step 7: Wait for replication
            context.log.info("Waiting for replication to complete...")
            _wait_for_replication(client, source_table)
            context.log.info("Replication complete")

            # Step 8: Post-replace verification
            context.log.info("Verifying post-replace count...")
            post_count = _get_baseline_count(client, source_table, partition_key_expr, partition_id)
            context.log.info(f"Post-replace count: {post_count:,}")

            if baseline_count > 0:
                post_diff_pct = abs(post_count - baseline_count) / baseline_count
                if post_diff_pct > config.count_tolerance:
                    raise RuntimeError(
                        f"Post-replace count {post_count:,} differs from baseline {baseline_count:,} "
                        f"by {post_diff_pct:.2%} (tolerance: {config.count_tolerance:.2%}). "
                        f"REPLACE PARTITION succeeded but data may have diverged. Investigate."
                    )

            # Get new largest part size from the source table
            parts_rows = client.execute(
                "SELECT max(bytes_on_disk) FROM system.parts "
                "WHERE database = %(db)s AND table = %(table)s AND active AND partition_id = %(partition_id)s",
                {"db": database, "table": source_table, "partition_id": partition_id},
            )
            new_largest_bytes = parts_rows[0][0] if parts_rows[0][0] else 0
            new_largest_gib = new_largest_bytes / (1024**3)

        except Exception:
            # Ensure staging table is cleaned up on any failure to avoid blocking the next run
            context.log.warning("Error during partition break — truncating staging table before re-raising")
            try:
                _truncate_staging(client, staging_table)
            except Exception as cleanup_err:
                context.log.exception(f"Failed to truncate staging table during cleanup: {cleanup_err}")
            raise

        # Step 9: Truncate staging table (happy path)
        context.log.info("Truncating staging table...")
        _truncate_staging(client, staging_table)

        duration = time.time() - start_time

        return BreakResult(
            table=source_table,
            shard_num=shard,
            partition_id=partition_id,
            baseline_count=baseline_count,
            post_replace_count=post_count,
            old_largest_part_gib=partition.largest_part_gib,
            new_largest_part_gib=new_largest_gib,
            new_part_count=staging_parts,
            duration_seconds=duration,
        )

    # Execute on this shard's offline node.
    # Catch all exceptions so a single shard failure doesn't kill the entire job —
    # other shards' work is already committed (REPLACE PARTITION is atomic).
    try:
        result = cluster.map_any_host_in_shards_by_role(
            {shard: _process},
            node_role=NodeRole.DATA,
            workload=Workload.OFFLINE,
        ).result()
    except Exception:
        context.log.exception(
            f"Failed to break {source_table} shard {shard}, partition {partition_id} — will retry on next run"
        )
        return None

    # Extract the single result
    break_result = next(iter(result.values()))

    context.log.info(
        f"{break_result.table} shard {break_result.shard_num}, partition {break_result.partition_id}: "
        f"largest part {break_result.old_largest_part_gib:.1f} GiB → {break_result.new_largest_part_gib:.1f} GiB "
        f"({break_result.new_part_count} parts), "
        f"count {break_result.baseline_count:,} → {break_result.post_replace_count:,} "
        f"(diff: {break_result.count_diff_pct:.2%}), "
        f"took {break_result.duration_seconds / 3600:.1f}h"
    )

    # Emit structured metadata for Dagster UI visibility
    context.add_output_metadata(
        {
            "table": break_result.table,
            "shard": break_result.shard_num,
            "partition": break_result.partition_id,
            "old_largest_gib": round(break_result.old_largest_part_gib, 1),
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
    completed = [r for r in results if r is not None]
    failed_count = len(results) - len(completed)

    if not completed and failed_count == 0:
        context.log.info("No partitions were processed (dry run or nothing to do)")
        return

    context.log.info(
        f"Part breaker completed: {len(completed)} succeeded, {failed_count} failed out of {len(results)} partition(s)"
    )
    for r in completed:
        context.log.info(
            f"  {r.table} shard {r.shard_num}, partition {r.partition_id}: "
            f"{r.old_largest_part_gib:.1f} GiB → {r.new_largest_part_gib:.1f} GiB "
            f"({r.new_part_count} parts, {r.duration_seconds / 3600:.1f}h, "
            f"count diff: {r.count_diff_pct:.2%})"
        )

    if failed_count > 0:
        context.log.warning(f"{failed_count} partition(s) failed — check individual op logs for details")


# -- Dagster Job --


@dagster.job(
    tags={
        "owner": JobOwners.TEAM_CLICKHOUSE.value,
        # Disable slack alerts during initial validation — remove once stable
        "disable_slack_notifications": True,
    },
    resource_defs=PART_BREAKER_RESOURCE_DEFS,
    executor_def=dagster.multiprocess_executor.configured({"max_concurrent": settings.PART_BREAKER_MAX_CONCURRENT}),
)
def break_oversized_parts():
    """Find and break oversized parts across sharded ClickHouse tables.

    Discovers partitions with parts larger than the configured threshold
    across all eligible tables, then breaks them using INSERT SELECT +
    REPLACE PARTITION on each shard's offline node.
    """
    partitions = discover_oversized_partitions()
    results = partitions.map(break_partition).collect()
    report_results(results)


# -- Schedule --
# Starts STOPPED — enable via the Dagster UI when ready.


@dagster.schedule(
    job=break_oversized_parts,
    cron_schedule=settings.PART_BREAKER_SCHEDULE,
    execution_timezone="UTC",
    default_status=dagster.DefaultScheduleStatus.STOPPED,
)
def break_oversized_parts_schedule(context: dagster.ScheduleEvaluationContext):
    return dagster.RunRequest()
