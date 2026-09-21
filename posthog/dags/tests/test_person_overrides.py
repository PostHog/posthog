import uuid as uuid_module
from datetime import datetime, timedelta
from functools import partial
from uuid import UUID

import pytest
from unittest.mock import Mock, call, patch

from django.conf import settings as django_settings

import dagster
from clickhouse_driver import Client

from posthog.clickhouse.cluster import AlterTableMutationRunner, ClickhouseCluster
from posthog.dags.deletes import deletes_job
from posthog.dags.person_overrides import (
    PERSON_ID_REWRITE_CONCURRENCY_TAGS,
    GetExistingDictionaryConfig,
    PersonOverridesSnapshotDictionary,
    PersonOverridesSnapshotTable,
    PopulateSnapshotTableConfig,
    cleanup_orphaned_person_overrides_snapshot,
    flag_evaluations_person_id_rewrite_schedule,
    get_existing_dictionary_for_run_id,
    populate_snapshot_table,
    rewrite_flag_evaluations_person_id,
    run_person_id_update_mutations,
    squash_person_overrides,
    wait_for_overrides_delete_mutations,
)
from posthog.dags.tests.conftest import insert_flag_evaluations
from posthog.models.async_deletion import AsyncDeletion, DeletionType
from posthog.models.deletion_targets import EVENTS, EVENTS_JSON, FLAG_EVALUATIONS, TargetPlacement
from posthog.models.event.sql import EVENTS_DATA_TABLE, EVENTS_JSON_DATA_TABLE
from posthog.models.flag_evaluations.sql import FLAG_EVALUATIONS_DATA_TABLE


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


@pytest.mark.django_db
def test_a_person_deletion_after_a_merge_reaches_flag_evaluations(cluster: ClickhouseCluster):
    # A merge moves a distinct_id's rows onto the surviving person, and a deletion of that person
    # names only the surviving uuid. The squash is what makes the two agree, so a table it skips
    # keeps the absorbed uuid and the sweep never matches those rows, permanently, because the
    # override that recorded the mapping is deleted in the same squash run. This runs both dags
    # because the regression lives at the seam between them, which neither dag's own test covers.
    # nosemgrep: test-datetime-now-without-freeze (every timestamp here is an offset from this base, so no assertion reads a day bucket)
    timestamp = (datetime.now() + timedelta(days=31)).replace(microsecond=0)
    team_id = 4242
    absorbed_person, surviving_person = UUID(int=9001), UUID(int=9002)
    row_uuid = UUID(int=9003)

    cluster.any_host(
        partial(
            insert_flag_evaluations,
            [(team_id, "merged", absorbed_person, row_uuid, timestamp - timedelta(hours=2))],
        )
    ).result()

    def insert_override(client: Client) -> None:
        client.execute(
            "INSERT INTO person_distinct_id_overrides (team_id, distinct_id, person_id, _timestamp, version) VALUES",
            [(team_id, "merged", surviving_person, timestamp - timedelta(hours=1), 1)],
        )

    cluster.any_host(insert_override).result()

    def surviving_flag_evaluation_person_ids(client: Client) -> set[UUID]:
        # _row_exists = 1 drops rows a lightweight delete already hid; without it a swept row
        # still reads back until its part merges.
        rows = client.execute(
            "SELECT person_id FROM flag_evaluations WHERE uuid = %(uuid)s AND _row_exists = 1",
            {"uuid": row_uuid},
        )
        return {person_id for [person_id] in rows}

    squash_person_overrides.execute_in_process(
        run_config=dagster.RunConfig(
            {populate_snapshot_table.name: PopulateSnapshotTableConfig(timestamp=timestamp.isoformat())}
        ),
        resources={"cluster": cluster},
    )

    assert cluster.any_host(surviving_flag_evaluation_person_ids).result() == {surviving_person}

    deletion = AsyncDeletion.objects.create(
        team_id=team_id, deletion_type=DeletionType.Person, key=str(surviving_person)
    )
    deletion.created_at = timestamp
    deletion.save()

    # A person sweep only picks up requests made before the oldest surviving override, and the
    # squash consumed the only one this test wrote. An empty overrides table pins that watermark at
    # the epoch, so give the sweep an unrelated later override, which is what production always has.
    def insert_later_override(client: Client) -> None:
        client.execute(
            "INSERT INTO person_distinct_id_overrides (team_id, distinct_id, person_id, _timestamp, version) VALUES",
            [(team_id, "unrelated", UUID(int=9004), timestamp + timedelta(hours=1), 1)],
        )

    cluster.any_host(insert_later_override).result()

    deletes_job.execute_in_process(
        run_config={"ops": {"create_pending_deletions_table": {"config": {"team_id": team_id}}}},
        resources={"cluster": cluster},
    )

    assert cluster.any_host(surviving_flag_evaluation_person_ids).result() == set()


def test_the_daily_rewrite_applies_overrides_to_flag_evaluations_and_leaves_them_in_place(
    cluster: ClickhouseCluster,
):
    # The daily job closes the window in which flag_evaluations rows still carry the person a merge
    # absorbed. It must leave the overrides it applies behind: the weekly squash is what applies
    # them to the events tables, and it deletes them only after it has. A daily run that deleted
    # them, or that rewrote the events tables as well, would take work away from the weekly one.
    timestamp = datetime(2025, 6, 1)
    team_id = 4243
    absorbed_person, surviving_person = UUID(int=9101), UUID(int=9102)
    row_uuid = UUID(int=9103)

    cluster.any_host(
        partial(
            insert_flag_evaluations,
            [(team_id, "merged", absorbed_person, row_uuid, timestamp - timedelta(hours=2))],
        )
    ).result()

    def insert_event(client: Client) -> None:
        client.execute(
            "INSERT INTO writable_events (distinct_id, person_id, timestamp) VALUES",
            [("merged", absorbed_person, timestamp - timedelta(hours=2))],
        )

    def insert_override(client: Client) -> None:
        client.execute(
            "INSERT INTO person_distinct_id_overrides (team_id, distinct_id, person_id, _timestamp, version) VALUES",
            [(team_id, "merged", surviving_person, timestamp - timedelta(hours=1), 1)],
        )

    cluster.any_host(insert_event).result()
    cluster.any_host(insert_override).result()

    def flag_evaluation_person_ids(client: Client) -> set[UUID]:
        rows = client.execute("SELECT person_id FROM flag_evaluations WHERE uuid = %(uuid)s", {"uuid": row_uuid})
        return {person_id for [person_id] in rows}

    def event_person_ids(client: Client) -> set[UUID]:
        rows = client.execute("SELECT person_id FROM events WHERE distinct_id = 'merged'")
        return {person_id for [person_id] in rows}

    def overrides(client: Client) -> set[tuple[str, UUID]]:
        rows = client.execute("SELECT distinct_id, person_id FROM person_distinct_id_overrides FINAL")
        return {(distinct_id, person_id) for [distinct_id, person_id] in rows}

    run_result = rewrite_flag_evaluations_person_id.execute_in_process(
        run_config=dagster.RunConfig(
            {populate_snapshot_table.name: PopulateSnapshotTableConfig(timestamp=timestamp.isoformat())}
        ),
        resources={"cluster": cluster},
    )

    assert cluster.any_host(flag_evaluation_person_ids).result() == {surviving_person}
    assert cluster.any_host(event_person_ids).result() == {absorbed_person}
    assert cluster.any_host(overrides).result() == {("merged", surviving_person)}

    table = PersonOverridesSnapshotTable(UUID(run_result.dagster_run.run_id))
    dictionary = PersonOverridesSnapshotDictionary(source=table)
    assert not any(cluster.map_all_hosts(table.exists).result().values())
    assert not any(cluster.map_all_hosts(dictionary.exists).result().values())


def test_the_daily_schedule_snapshots_the_window_ending_at_its_own_tick():
    # The op's config default is a literal evaluated at import, so a job that took it would snapshot
    # the same window on every run for as long as the code server lives, and never see a merge
    # recorded after that import. The schedule has to carry the timestamp instead.
    ticks = [dagster.build_schedule_context(scheduled_execution_time=datetime(2025, 6, day, 4, 0)) for day in (1, 2)]
    timestamps = [
        request.run_config["ops"][populate_snapshot_table.name]["config"]["timestamp"]
        for tick in ticks
        for request in [flag_evaluations_person_id_rewrite_schedule(tick)]
    ]

    assert timestamps == ["2025-05-30 04:00:00", "2025-05-31 04:00:00"]


def test_every_run_computes_its_own_snapshot_cutoff():
    # The cutoff used to be a literal in the field definition, which pydantic evaluates once when
    # the module is imported. Every later run on the same code server then re-snapshotted a window
    # the first run had already consumed: the weekly squash silently stopped rewriting events, and
    # a manual run of either job could not repair the merges it was launched for.
    first = PopulateSnapshotTableConfig().timestamp
    with patch("posthog.dags.person_overrides.datetime.datetime") as clock:
        clock.now.return_value = datetime(2030, 1, 1)
        later = PopulateSnapshotTableConfig().timestamp

    assert later == "2029-12-30 00:00:00"
    assert later != first


def test_both_person_id_rewrites_share_a_concurrency_key():
    # The two jobs write person_id on flag_evaluations from separate snapshots, and the per-table
    # capacity wait orders neither run. A Dagster run-queue limit is what serializes them, and it
    # attaches to a tag both jobs carry, so a job that loses the key silently leaves the limit.
    assert "person_id_rewrite_concurrency" in PERSON_ID_REWRITE_CONCURRENCY_TAGS
    assert squash_person_overrides.tags == PERSON_ID_REWRITE_CONCURRENCY_TAGS
    assert rewrite_flag_evaluations_person_id.tags == PERSON_ID_REWRITE_CONCURRENCY_TAGS


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
def test_run_person_id_update_mutations_rewrites_each_target_on_its_own_cluster(cluster: ClickhouseCluster):
    # sharded_events_json and sharded_flag_evaluations may each sit on a cluster whose shards only
    # its own handle enumerates. Running one of those rewrites over the job's handle would skip its
    # rows, and the overrides that record the correct person_id are deleted in the very next op, so
    # the divergence would be permanent. The assertion is keyed by table because a weaker one --
    # that some mutation reached the sibling -- still passes when a target is dropped entirely.
    dictionary = _create_snapshot_with(cluster, [(1, "a", UUID(int=7), 3)])
    sibling = cluster.sibling(django_settings.CLICKHOUSE_SINGLE_SHARD_CLUSTER)
    placements = [
        TargetPlacement(target=EVENTS, cluster=cluster),
        TargetPlacement(target=EVENTS_JSON, cluster=sibling),
        TargetPlacement(target=FLAG_EVALUATIONS, cluster=sibling),
    ]
    calls = Mock()
    enqueued = {
        EVENTS_DATA_TABLE(): {0: Mock()},
        EVENTS_JSON_DATA_TABLE: {0: Mock()},
        FLAG_EVALUATIONS_DATA_TABLE: {0: Mock()},
    }

    with (
        patch("posthog.dags.person_overrides.resolve_placements", return_value=placements) as resolve_placements,
        patch.object(
            AlterTableMutationRunner,
            "enqueue_on_shards",
            autospec=True,
            side_effect=lambda runner, handle, shards=None: enqueued[runner.table],
        ) as enqueue_on_shards,
        patch("posthog.dags.person_overrides.wait_for_mutations_on_shards") as wait_for_mutations,
    ):
        calls.attach_mock(enqueue_on_shards, "enqueue")
        calls.attach_mock(wait_for_mutations, "wait")
        run_person_id_update_mutations(cluster, dictionary)

    # This assertion names the targets literally instead of reusing SQUASH_TARGETS or EVENTS_TARGETS.
    # Either constant would still match after someone drops a target from its definition.
    resolve_placements.assert_called_once_with(cluster, (EVENTS, EVENTS_JSON, FLAG_EVALUATIONS))
    assert {enqueue.args[0].table: enqueue.args[1] for enqueue in enqueue_on_shards.call_args_list} == {
        EVENTS_DATA_TABLE(): cluster,
        EVENTS_JSON_DATA_TABLE: sibling,
        FLAG_EVALUATIONS_DATA_TABLE: sibling,
    }
    # Each wait has to receive the mutations its own enqueue returned. A wait handed an empty set
    # returns at once, and the next op deletes the overrides that record the mapping.
    wait_for_mutations.assert_has_calls(
        [
            call(cluster, enqueued[EVENTS_DATA_TABLE()]),
            call(sibling, enqueued[EVENTS_JSON_DATA_TABLE]),
            call(sibling, enqueued[FLAG_EVALUATIONS_DATA_TABLE]),
        ],
        any_order=True,
    )
    # Waiting on each mutation as it is enqueued would cost the sum of their completion times
    # rather than the longest, which is the whole reason the op enqueues in one pass.
    assert [name for name, *_ in calls.mock_calls] == ["enqueue"] * 3 + ["wait"] * 3
    cluster.any_host(dictionary.source.drop).result()
