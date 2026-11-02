from collections.abc import Callable, Sequence

from django.conf import settings

import dagster
import pydantic
from clickhouse_driver.client import Client

from posthog.clickhouse.cluster import AlterTableMutationRunner, ClickhouseCluster
from posthog.dags.common import JobOwners
from posthog.dags.deletes import _mutation_reuse_floor, ensure_no_concurrent_deletes_run
from posthog.dataclasses import frozen
from posthog.models.deletion_targets import EVENTS, EVENTS_JSON, DeletionTarget, TargetPlacement, placement_for


class FindDeletedMaskPartitionsConfig(dagster.Config):
    min_deleted_ratio: float = pydantic.Field(
        default=0.1,
        gt=0,
        le=1,
        description="Apply the deleted mask on a shard's partition when at least this share of its rows is deleted.",
    )
    partitions: list[str] = pydantic.Field(
        default_factory=list,
        description="Only check these months, as YYYYMM (e.g. ['202412']). Empty means every month.",
    )


class ApplyDeletedMaskConfig(dagster.Config):
    dry_run: bool = pydantic.Field(
        default=False,
        description="Only log the partitions this run would rewrite.",
    )


@frozen
class DeletedMaskPartition:
    partition: str
    shard: int
    physical_rows: int
    deleted_rows: int


@frozen
class PartitionRowCounts:
    physical_rows: int
    live_rows: int


def _partition_filter(partitions: Sequence[str], column: str) -> str:
    return f"AND {column} IN %(partitions)s" if partitions else ""


def _deleted_rows_by_partition(
    placement: TargetPlacement, partitions: Sequence[str]
) -> Callable[[Client], dict[str, PartitionRowCounts]]:
    """A callable that returns the row counts of each partition of the table on one host."""
    parameters = {
        "database": settings.CLICKHOUSE_DATABASE,
        "table": placement.target.data_table,
        "partitions": list(partitions),
    }

    def count(client: Client) -> dict[str, PartitionRowCounts]:
        # Patch parts sit in partitions of their own and hold no rows of the table, so only the
        # data parts count as physical rows. count() applies both the deleted mask and patch parts.
        physical = client.execute(
            f"""
            SELECT partition_id, sum(rows)
            FROM system.parts
            WHERE database = %(database)s AND table = %(table)s AND active
            AND NOT startsWith(partition_id, 'patch-')
            {_partition_filter(partitions, "partition_id")}
            GROUP BY partition_id
            """,
            parameters,
        )
        live = dict(
            client.execute(
                f"""
                SELECT _partition_id, count()
                FROM {settings.CLICKHOUSE_DATABASE}.{placement.target.data_table}
                WHERE 1 {_partition_filter(partitions, "_partition_id")}
                GROUP BY _partition_id
                """,
                parameters,
            )
        )
        return {
            partition_id: PartitionRowCounts(physical_rows=rows, live_rows=live.get(partition_id, 0))
            for partition_id, rows in physical
        }

    return count


def _find_deleted_mask_partitions_op(name: str, target: DeletionTarget) -> dagster.OpDefinition:
    @dagster.op(name=f"find_deleted_mask_partitions_{name}", ins={"start_after": dagster.In(dagster.Nothing)})
    def find(
        context: dagster.OpExecutionContext,
        config: FindDeletedMaskPartitionsConfig,
        cluster: dagster.ResourceParam[ClickhouseCluster],
    ) -> list[DeletedMaskPartition]:
        """Find each month and shard of one events table whose deleted rows reach the threshold, most deleted rows first."""
        placement = placement_for(cluster, target)
        if placement is None:
            context.log.info(f"{target.data_table} is not on any cluster this deployment reaches")
            return []

        found: list[DeletedMaskPartition] = []
        report: dict[str, dict[int, float]] = {}
        per_host = placement.cluster.map_one_host_per_shard(
            _deleted_rows_by_partition(placement, config.partitions)
        ).result()
        for host, counts in per_host.items():
            assert host.shard_num is not None
            for partition, rows in counts.items():
                if not rows.physical_rows:
                    continue
                deleted_rows = rows.physical_rows - rows.live_rows
                ratio = deleted_rows / rows.physical_rows
                report.setdefault(partition, {})[host.shard_num] = round(ratio, 4)
                if ratio >= config.min_deleted_ratio:
                    found.append(
                        DeletedMaskPartition(
                            partition=partition,
                            shard=host.shard_num,
                            physical_rows=rows.physical_rows,
                            deleted_rows=deleted_rows,
                        )
                    )

        found.sort(key=lambda item: item.deleted_rows, reverse=True)
        for item in found:
            context.log.info(
                f"{target.data_table} {item.partition} shard {item.shard}: {item.deleted_rows} of "
                f"{item.physical_rows} rows deleted ({item.deleted_rows / item.physical_rows:.1%})"
            )
        if not found:
            context.log.info(
                f"No {target.data_table} partition has {config.min_deleted_ratio:.0%} or more of its rows deleted"
            )

        context.add_output_metadata(
            {
                "deleted_ratio_by_partition_shard": dagster.MetadataValue.json(report),
                "partitions": dagster.MetadataValue.int(len(found)),
            }
        )
        return found

    return find


def _apply_deleted_mask_op(name: str, target: DeletionTarget) -> dagster.OpDefinition:
    @dagster.op(name=f"apply_deleted_mask_{name}")
    def apply(
        context: dagster.OpExecutionContext,
        config: ApplyDeletedMaskConfig,
        cluster: dagster.ResourceParam[ClickhouseCluster],
        partitions: list[DeletedMaskPartition],
    ) -> None:
        """Rewrite each found month on its shard without its deleted rows, one mutation at a time."""
        if config.dry_run or not partitions:
            context.log.info(
                f"Not rewriting {len(partitions)} {target.data_table} partition(s), dry run: {config.dry_run}"
            )
            return

        placement = placement_for(cluster, target)
        assert placement is not None
        # The commands name only the month, so a mask an earlier run applied matches them too.
        # Adopting that finished mutation would rewrite nothing.
        reuse_floor = _mutation_reuse_floor(cluster)

        for idx, item in enumerate(partitions, 1):
            context.log.info(
                f"{target.data_table} {item.partition} shard {item.shard}: removing {item.deleted_rows} rows "
                f"({idx}/{len(partitions)})"
            )
            commands = [f"APPLY DELETED MASK IN PARTITION '{item.partition}'"]
            if target.uses_patch_parts:
                # Rows deleted through a patch part are not in the deleted mask until the patch is
                # applied. One ALTER with both commands applies the mask first, so they run in turn.
                commands.insert(0, f"APPLY PATCHES IN PARTITION '{item.partition}'")
            for command in commands:
                # Each rewrite is heavy, so the next one starts only after every replica finishes this one.
                AlterTableMutationRunner(target.data_table, commands={command}, reuse_since=reuse_floor).run_on_shards(
                    placement.cluster, [item.shard]
                )

        context.add_output_metadata({"partitions_processed": dagster.MetadataValue.int(len(partitions))})

    return apply


# Each table sits on its own cluster with its own hardware, so each gets its own threshold, its own
# dry run switch, and its own queue of rewrites. The two queues run side by side.
_TABLE_OPS = {
    name: (_find_deleted_mask_partitions_op(name, target), _apply_deleted_mask_op(name, target))
    for name, target in (("events", EVENTS), ("events_json", EVENTS_JSON))
}


@dagster.job(
    tags={
        "owner": JobOwners.TEAM_CLICKHOUSE.value,
        # Shares the run-queue limit with deletes_job, the old events cleanup and squash, because
        # each rewrite is a mutation on the same events tables.
        "deletes_job_concurrency": "v1",
    }
)
def apply_deleted_mask_job():
    """Find events table months with many deleted rows, then remove those rows from disk, most deleted rows first."""
    guard = ensure_no_concurrent_deletes_run()
    for find, apply in _TABLE_OPS.values():
        apply(find(start_after=guard))
