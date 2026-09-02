import uuid as uuid_module
from datetime import datetime, timedelta
from functools import partial
from uuid import UUID

import pytest
from unittest.mock import patch

from django.conf import settings as django_settings

import dagster
from clickhouse_driver import Client

from posthog.clickhouse.cluster import ClickhouseCluster
from posthog.dags.person_overrides import (
    GetExistingDictionaryConfig,
    PersonOverridesSnapshotDictionary,
    PersonOverridesSnapshotTable,
    PopulateSnapshotTableConfig,
    cleanup_orphaned_person_overrides_snapshot,
    get_existing_dictionary_for_run_id,
    populate_snapshot_table,
    run_person_id_update_mutations,
    squash_person_overrides,
    wait_for_overrides_delete_mutations,
)
from posthog.models.deletion_targets import EVENTS_JSON, TargetPlacement


def test_full_job(cluster: ClickhouseCluster):
    timestamp = datetime(2025, 1, 1)

    def insert_events(client: Client) -> None:
        client.execute(
            "INSERT INTO writable_events (distinct_id, person_id, timestamp) VALUES",
            [
                ("a", UUID(int=0), timestamp - timedelta(hours=24)),
                ("b", UUID(int=1), timestamp - timedelta(hours=24)),
                ("c", UUID(int=2), timestamp - timedelta(hours=24)),
                ("d", UUID(int=3), timestamp - timedelta(hours=12)),
                ("e", UUID(int=4), timestamp - timedelta(hours=6)),
                ("z", UUID(int=100), timestamp - timedelta(hours=3)),
            ],
        )

    cluster.any_host(insert_events).result()

    def insert_overrides(client: Client) -> None:
        client.execute(
            "INSERT INTO person_distinct_id_overrides (distinct_id, person_id, _timestamp, version) VALUES",
            [
                ("c", UUID(int=0), timestamp - timedelta(hours=12), 1),  # 0: {"a", "c"}
                ("e", UUID(int=3), timestamp - timedelta(hours=6), 1),  # 3: {"d", "e"}
                ("d", UUID(int=1), timestamp - timedelta(hours=5), 1),  # 1: {"b", "d"}
                ("e", UUID(int=1), timestamp - timedelta(hours=5), 2),  # 1: {"b", "d", "e"}
                ("z", UUID(int=0), timestamp + timedelta(hours=1), 1),  # arrived after timestamp, ignored this run
            ],
        )

    cluster.any_host(insert_overrides).result()

    def get_distinct_ids_on_events_by_person(client: Client) -> dict[UUID, set[str]]:
        rows = client.execute("SELECT person_id, groupUniqArray(distinct_id) FROM events GROUP BY ALL")
        result = {person_id: set(distinct_ids) for person_id, distinct_ids in rows}
        assert len(rows) == len(result)
        return result

    def get_distinct_ids_with_overrides(client: Client) -> set[str]:
        rows = client.execute("SELECT distinct_id FROM person_distinct_id_overrides FINAL")
        result = {distinct_id for [distinct_id] in rows}
        assert len(rows) == len(result)
        return result

    # check preconditions
    assert cluster.any_host(get_distinct_ids_on_events_by_person).result() == {
        UUID(int=0): {"a"},
        UUID(int=1): {"b"},
        UUID(int=2): {"c"},
        UUID(int=3): {"d"},
        UUID(int=4): {"e"},
        UUID(int=100): {"z"},
    }
    assert cluster.any_host(get_distinct_ids_with_overrides).result() == {"c", "d", "e", "z"}

    # run with limit
    limited_run_result = squash_person_overrides.execute_in_process(
        run_config=dagster.RunConfig(
            {populate_snapshot_table.name: PopulateSnapshotTableConfig(timestamp=timestamp.isoformat(), limit=2)}
        ),
        resources={"cluster": cluster},
    )

    # ensure we cleaned up after ourselves
    table = PersonOverridesSnapshotTable(UUID(limited_run_result.dagster_run.run_id))
    dictionary = PersonOverridesSnapshotDictionary(source=table)
    assert not any(cluster.map_all_hosts(table.exists).result().values())
    assert not any(cluster.map_all_hosts(dictionary.exists).result().values())

    remaining_overrides = cluster.any_host(get_distinct_ids_with_overrides).result()
    assert len(remaining_overrides) == 2  # one candidate discarded due to limit, one out of timestamp range
    assert "z" in remaining_overrides  # outside of timestamp range

    # run without limit to handle the remaining item(s)
    full_run_result = squash_person_overrides.execute_in_process(
        run_config=dagster.RunConfig(
            {populate_snapshot_table.name: PopulateSnapshotTableConfig(timestamp=timestamp.isoformat())}
        ),
        resources={"cluster": cluster},
    )

    # ensure we cleaned up after ourselves again
    table = PersonOverridesSnapshotTable(UUID(full_run_result.dagster_run.run_id))
    dictionary = PersonOverridesSnapshotDictionary(source=table)
    assert not any(cluster.map_all_hosts(table.exists).result().values())
    assert not any(cluster.map_all_hosts(dictionary.exists).result().values())

    # check postconditions
    assert cluster.any_host(get_distinct_ids_on_events_by_person).result() == {
        UUID(int=0): {"a", "c"},
        UUID(int=1): {"b", "d", "e"},
        UUID(int=100): {"z"},
    }
    assert cluster.any_host(get_distinct_ids_with_overrides).result() == {"z"}


def test_cleanup_job(cluster: ClickhouseCluster) -> None:
    timestamp = datetime(2025, 1, 1)

    partial_squash_run_result = squash_person_overrides.execute_in_process(
        run_config=dagster.RunConfig(
            {populate_snapshot_table.name: PopulateSnapshotTableConfig(timestamp=timestamp.isoformat())},
        ),
        resources={"cluster": cluster},
        op_selection=[f"*{wait_for_overrides_delete_mutations.name}"],
    )

    # ensure we left some resources dangling around due to the op selection
    table = PersonOverridesSnapshotTable(UUID(partial_squash_run_result.dagster_run.run_id))
    dictionary = PersonOverridesSnapshotDictionary(source=table)
    assert all(cluster.map_all_hosts(table.exists).result().values())
    assert all(cluster.map_all_hosts(dictionary.exists).result().values())

    cleanup_orphaned_person_overrides_snapshot.execute_in_process(
        run_config=dagster.RunConfig(
            {
                get_existing_dictionary_for_run_id.name: GetExistingDictionaryConfig(
                    id=partial_squash_run_result.dagster_run.run_id
                )
            }
        ),
        resources={"cluster": cluster},
    )

    # cleanup should have removed any dangling resources from the partial job
    assert not any(cluster.map_all_hosts(table.exists).result().values())
    assert not any(cluster.map_all_hosts(dictionary.exists).result().values())


def _create_snapshot_with(cluster: ClickhouseCluster, rows: list[tuple]) -> PersonOverridesSnapshotDictionary:
    table = PersonOverridesSnapshotTable(id=uuid_module.uuid4())
    cluster.any_host(table.create).result()

    def insert(client: Client) -> None:
        client.execute(f"INSERT INTO {table.qualified_name} (team_id, distinct_id, person_id, version) VALUES", rows)

    cluster.any_host(insert).result()
    return PersonOverridesSnapshotDictionary(source=table)


@pytest.mark.django_db
def test_a_staged_snapshot_dictionary_holds_the_same_rows_as_the_snapshot_table(cluster: ClickhouseCluster):
    # A cluster that shares no Keeper with the job's own never receives the replicated snapshot
    # table, so it builds the dictionary from a staged object. The squash is gated on both sides
    # checksumming alike, which only means something if every column round-trips exactly. This one
    # carries a UUID and a String key, neither of which the deletes dictionaries exercise.
    dictionary = _create_snapshot_with(cluster, [(1, "a", UUID(int=7), 3), (2, "b", UUID(int=8), 4)])
    create = partial(dictionary.create, shards=1, max_execution_time=0, max_memory_usage=0)
    recreate = partial(dictionary.recreate, shards=1, max_execution_time=0, max_memory_usage=0)

    try:
        cluster.any_host(create).result()
        from_snapshot_table = cluster.any_host(dictionary.load).result()

        staged = dictionary.staged()
        cluster.any_host(partial(staged.export, source_query=dictionary.query)).result()
        cluster.any_host(partial(recreate, query=staged.query)).result()
        from_staged_object = cluster.any_host(dictionary.load).result()

        assert from_staged_object == from_snapshot_table
    finally:
        cluster.any_host(dictionary.drop).result()
        cluster.any_host(dictionary.source.drop).result()


@pytest.mark.django_db
def test_run_person_id_update_mutations_rewrites_events_json_on_its_own_cluster(cluster: ClickhouseCluster):
    # sharded_events_json may sit on a cluster whose shards only its own handle enumerates. Running
    # its rewrite over the job's handle would skip those rows, and the overrides that record the
    # correct person_id are deleted in the very next op, so the divergence would be permanent.
    dictionary = _create_snapshot_with(cluster, [(1, "a", UUID(int=7), 3)])
    sibling = cluster.sibling(django_settings.CLICKHOUSE_SINGLE_SHARD_CLUSTER)

    with (
        patch(
            "posthog.dags.person_overrides.placement_for",
            return_value=TargetPlacement(target=EVENTS_JSON, cluster=sibling),
        ),
        patch.object(
            type(dictionary.events_json_update_mutation_runner), "run_on_shards", autospec=True
        ) as run_on_shards,
    ):
        run_person_id_update_mutations(cluster, dictionary)

    dispatched = [call.args[1] for call in run_on_shards.call_args_list]
    assert sibling in dispatched
    cluster.any_host(dictionary.source.drop).result()
