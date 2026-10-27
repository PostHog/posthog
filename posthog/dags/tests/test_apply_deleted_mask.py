from datetime import datetime
from uuid import UUID

import pytest

from django.conf import settings

from clickhouse_driver import Client

from posthog.clickhouse.cluster import ClickhouseCluster, LightweightDeleteMutationRunner, Query
from posthog.dags.apply_deleted_mask import DeletedMaskPartition, apply_deleted_mask_job
from posthog.models.deletion_targets import EVENTS_TARGETS, resolve_placements
from posthog.models.event.sql import EVENTS_DATA_TABLE, EVENTS_JSON_DATA_TABLE

TEAM_ID = 4242
MOSTLY_DELETED = "202412"
FEW_DELETED = "202501"
MOST_DELETED = "202502"
# The events_json threshold sits between the 50% and 80% months, so it rewrites only one of them.
MIN_DELETED_RATIO = {"events": 0.1, "events_json": 0.6}


def _insert_events(cluster: ClickhouseCluster) -> None:
    rows = [
        (TEAM_ID, f"user_{i}", UUID(int=i), datetime(2024, 12, 10) if i < 100 else datetime(2025, i // 100, 10))
        for i in range(300)
    ]

    def insert(client: Client) -> None:
        client.execute("INSERT INTO writable_events (team_id, distinct_id, uuid, timestamp) VALUES", rows)
        client.execute(f"INSERT INTO {EVENTS_JSON_DATA_TABLE} (team_id, distinct_id, uuid, timestamp) VALUES", rows)

    cluster.any_host(insert).result()


def _delete(cluster: ClickhouseCluster, partition: str, below_uuid: int) -> None:
    for placement in resolve_placements(cluster, EVENTS_TARGETS):
        LightweightDeleteMutationRunner(
            table=placement.target.data_table,
            predicate="team_id = %(team_id)s AND uuid < %(below)s",
            parameters={"team_id": TEAM_ID, "below": UUID(int=below_uuid)},
            partition=partition,
            settings={"lightweight_deletes_sync": 2},
            patch_parts=placement.target.uses_patch_parts,
        ).run_on_shards(placement.cluster)


def _physical_rows(cluster: ClickhouseCluster) -> dict[tuple[str, str], int]:
    counts: dict[tuple[str, str], int] = {}
    for placement in resolve_placements(cluster, EVENTS_TARGETS):

        def count(client: Client, table: str = placement.target.data_table) -> list[tuple[str, int]]:
            return client.execute(
                """
                SELECT partition_id, sum(rows) FROM system.parts
                WHERE database = %(database)s AND table = %(table)s AND active AND partition_id IN %(partitions)s
                GROUP BY partition_id
                """,
                {
                    "database": settings.CLICKHOUSE_DATABASE,
                    "table": table,
                    "partitions": [MOSTLY_DELETED, FEW_DELETED, MOST_DELETED],
                },
            )

        for rows in placement.cluster.map_one_host_per_shard(count).result().values():
            for partition, physical in rows:
                key = (placement.target.data_table, partition)
                counts[key] = counts.get(key, 0) + physical
    return counts


def _run(cluster: ClickhouseCluster, dry_run: bool) -> dict[str, list[DeletedMaskPartition]]:
    partitions = [MOSTLY_DELETED, FEW_DELETED, MOST_DELETED]
    result = apply_deleted_mask_job.execute_in_process(
        run_config={
            "ops": {
                **{
                    f"find_deleted_mask_partitions_{name}": {
                        "config": {"partitions": partitions, "min_deleted_ratio": ratio}
                    }
                    for name, ratio in MIN_DELETED_RATIO.items()
                },
                **{f"apply_deleted_mask_{name}": {"config": {"dry_run": dry_run}} for name in MIN_DELETED_RATIO},
            }
        },
        resources={"cluster": cluster},
    )
    return {name: result.output_for_node(f"find_deleted_mask_partitions_{name}") for name in MIN_DELETED_RATIO}


@pytest.mark.django_db
def test_found_partitions_lose_their_deleted_rows_and_others_stay_untouched(cluster: ClickhouseCluster):
    try:
        _find_and_apply(cluster)
    finally:
        cluster.map_one_host_per_shard(Query(f"TRUNCATE TABLE {EVENTS_JSON_DATA_TABLE}")).result()


def _find_and_apply(cluster: ClickhouseCluster) -> None:
    _insert_events(cluster)
    _delete(cluster, MOSTLY_DELETED, below_uuid=50)
    _delete(cluster, FEW_DELETED, below_uuid=101)
    _delete(cluster, MOST_DELETED, below_uuid=280)
    before = _physical_rows(cluster)

    _run(cluster, dry_run=True)
    assert _physical_rows(cluster) == before

    found = _run(cluster, dry_run=False)
    assert {name: {item.partition for item in items} for name, items in found.items()} == {
        "events": {MOSTLY_DELETED, MOST_DELETED},
        "events_json": {MOST_DELETED},
    }
    deleted_rows = [item.deleted_rows for item in found["events"]]
    assert deleted_rows == sorted(deleted_rows, reverse=True)

    after = _physical_rows(cluster)
    # sharded_events_json deletes through patch parts, which the mask only removes after APPLY PATCHES.
    assert {table for table, _ in before} == {EVENTS_DATA_TABLE(), EVENTS_JSON_DATA_TABLE}
    removed = {
        EVENTS_DATA_TABLE(): {MOSTLY_DELETED: 50, FEW_DELETED: 0, MOST_DELETED: 80},
        EVENTS_JSON_DATA_TABLE: {MOSTLY_DELETED: 0, FEW_DELETED: 0, MOST_DELETED: 80},
    }
    for table, partition in before:
        assert after[(table, partition)] == before[(table, partition)] - removed[table][partition]
