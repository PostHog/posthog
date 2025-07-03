from datetime import datetime, timedelta
from functools import partial
from uuid import UUID

import pytest
from clickhouse_driver import Client

from dags.deletes import (
    AdhocEventDeletesDictionary,
    AdhocEventDeletesTable,
    deletes_job,
    PendingDeletesTable,
    PendingDeletesDictionary,
)

from posthog.clickhouse.cluster import ClickhouseCluster
from posthog.models.async_deletion import AsyncDeletion, DeletionType
from posthog.models.person.sql import PERSON_DISTINCT_ID_OVERRIDES_TABLE


@pytest.mark.django_db
def test_full_job_person_deletes(cluster: ClickhouseCluster):
    timestamp = (datetime.now() + timedelta(days=31)).replace(
        microsecond=0
    )  # we don't freeze time because we are namespaced by time
    hour_delay = 745  # 31 * 24
    event_count = 10000
    delete_count = 1000

    events = [(i, f"distinct_id_{i}", UUID(int=i), timestamp - timedelta(hours=i)) for i in range(event_count)]

    def insert_events(client: Client) -> None:
        client.execute(
            """INSERT INTO writable_events (team_id, distinct_id, person_id, timestamp)
            VALUES
            """,
            events,
        )

    cluster.any_host(insert_events).result()

    def get_oldest_override_timestamp(client: Client) -> datetime:
        result = client.execute(f"SELECT min(_timestamp) FROM {PERSON_DISTINCT_ID_OVERRIDES_TABLE}")
        if not result or result[0][0] is None:
            return datetime.max
        return result[0][0]

    # Insert some person overrides - we need this to establish high watermark for pending deletes
    def insert_overrides(client: Client) -> None:
        client.execute(
            "INSERT INTO person_distinct_id_overrides (distinct_id, person_id, _timestamp, version) VALUES",
            [(f"{i}", UUID(int=i), timestamp - timedelta(hours=i), 1) for i in range(hour_delay)],
        )

    cluster.any_host(insert_overrides).result()

    def get_events_by_person_team(client: Client) -> dict[tuple[int, UUID], int]:
        result = client.execute("SELECT team_id, person_id, count(1) FROM writable_events GROUP BY team_id, person_id")
        if not isinstance(result, list):
            return {}
        return {(row[0], row[1]): row[2] for row in result}

    # Insert some pending deletions
    def insert_pending_deletes() -> None:
        deletes = [(events[i][0], DeletionType.Person, events[i][2], None) for i in range(delete_count)]

        # insert the deletes into django
        for i, delete in enumerate(deletes):
            d = AsyncDeletion.objects.create(
                team_id=delete[0],
                deletion_type=delete[1],
                key=delete[2],
                delete_verified_at=delete[3],
            )
            d.created_at = events[i][3] + timedelta(hours=1)
            d.save()

    insert_pending_deletes()

    def get_pending_deletes() -> list[AsyncDeletion]:
        return list(AsyncDeletion.objects.filter(delete_verified_at__isnull=True))

    # Check preconditions
    initial_events = cluster.any_host(get_events_by_person_team).result()
    assert len(initial_events) == event_count  # All events present initially

    pending_deletes = get_pending_deletes()
    assert len(pending_deletes) == delete_count

    # Check overrides is correct
    oldest_override_timestamp = cluster.any_host(get_oldest_override_timestamp).result()
    assert oldest_override_timestamp == timestamp - timedelta(hours=hour_delay - 1)

    # Run the deletion job
    deletes_job.execute_in_process(
        run_config={"ops": {"create_pending_deletions_table": {"config": {"timestamp": timestamp.isoformat()}}}},
        resources={"cluster": cluster},
    )

    # Check postconditions
    final_events = cluster.any_host(get_events_by_person_team).result()
    assert len(final_events) == event_count - (delete_count - hour_delay)  # Only events for non-deleted persons remain

    # Check that events after the deletion window remain
    target_uuid = UUID(int=hour_delay - 2)
    assert any(
        target_uuid == uuid for _, uuid in final_events.keys()
    ), f"Expected to find UUID {target_uuid} in remaining events"

    # Check that early events were deleted
    deleted_uuid = UUID(int=hour_delay + 2)
    assert not any(
        deleted_uuid == uuid for _, uuid in final_events.keys()
    ), f"Expected UUID {deleted_uuid} to be deleted"

    # Verify that the deletions before oldest override timestamp have been marked verified
    pre_override_deletions = AsyncDeletion.objects.filter(created_at__lte=oldest_override_timestamp)
    assert len(pre_override_deletions) == delete_count - hour_delay
    assert all(deletion.delete_verified_at is not None for deletion in pre_override_deletions)

    # Verify that the deletions after oldest override timestamp have not been marked verified
    post_override_deletions = AsyncDeletion.objects.filter(created_at__gt=oldest_override_timestamp)
    assert len(post_override_deletions) == hour_delay
    assert not all(deletion.delete_verified_at is not None for deletion in post_override_deletions)

    # Verify the temporary tables were cleaned up
    table = PendingDeletesTable(timestamp=timestamp)
    assert not any(cluster.map_all_hosts(table.exists).result().values())
    deletes_dict = PendingDeletesDictionary(source=table)
    assert not any(cluster.map_all_hosts(deletes_dict.exists).result().values())


@pytest.mark.django_db
def test_full_job_team_deletes(cluster: ClickhouseCluster):
    timestamp = (datetime.now() + timedelta(days=31)).replace(
        microsecond=0
    )  # we don't freeze time because we are namespaced by time
    event_count = 10000
    delete_count = 1000

    events = [(i, f"distinct_id_{i}", UUID(int=i), timestamp) for i in range(event_count)]
    persons = [(i, UUID(int=i)) for i in range(event_count)]
    groups = [(i, f"group_key_{i}") for i in range(event_count)]
    cohortpeople = [(i, UUID(int=i), 1) for i in range(event_count)]
    person_static_cohort = [(i, i) for i in range(event_count)]
    plugin_log_entries = [(i, i) for i in range(event_count)]
    person_distinct_id2 = [(i, f"distinct_id_{i}") for i in range(event_count)]

    def insert_events(client: Client) -> None:
        client.execute(
            """INSERT INTO writable_events (team_id, distinct_id, person_id, timestamp)
            VALUES
            """,
            events,
        )

    # Insert some person overrides - we need this to establish high watermark for pending deletes
    def insert_overrides(client: Client) -> None:
        client.execute(
            "INSERT INTO person_distinct_id_overrides (distinct_id, person_id, _timestamp, version) VALUES",
            [(f"{i}", UUID(int=i), timestamp, 1) for i in range(1)],
        )

    def insert_persons(client: Client) -> None:
        client.execute(
            """INSERT INTO person (team_id, id)
            VALUES
            """,
            persons,
        )

    def insert_groups(client: Client) -> None:
        client.execute(
            """INSERT INTO groups (team_id, group_key)
            VALUES
            """,
            groups,
        )

    def insert_cohortpeople(client: Client) -> None:
        client.execute(
            """INSERT INTO cohortpeople (team_id, person_id, sign)
            VALUES
            """,
            cohortpeople,
        )

    def insert_person_static_cohort(client: Client) -> None:
        client.execute(
            """INSERT INTO person_static_cohort (team_id, cohort_id)
            VALUES
            """,
            person_static_cohort,
        )

    def insert_plugin_log_entries(client: Client) -> None:
        client.execute(
            """INSERT INTO plugin_log_entries (team_id, plugin_id)
            VALUES
            """,
            plugin_log_entries,
        )

    def insert_person_distinct_id2(client: Client) -> None:
        client.execute(
            """INSERT INTO person_distinct_id2 (team_id, distinct_id)
            VALUES
            """,
            person_distinct_id2,
        )

    cluster.any_host(insert_overrides).result()
    cluster.any_host(insert_events).result()
    cluster.any_host(insert_persons).result()
    cluster.any_host(insert_groups).result()
    cluster.any_host(insert_cohortpeople).result()
    cluster.any_host(insert_person_static_cohort).result()
    cluster.any_host(insert_plugin_log_entries).result()
    cluster.any_host(insert_person_distinct_id2).result()

    def get_by_team(table: str, client: Client) -> dict[tuple[int, UUID], int]:
        result = client.execute(f"SELECT team_id, count(1) FROM {table} GROUP BY team_id")
        if not isinstance(result, list):
            return {}
        return {(row[0]): row[1] for row in result}

    # Insert some pending deletions
    def insert_pending_deletes() -> None:
        deletes = [(events[i][0], DeletionType.Team, events[i][0], None) for i in range(delete_count)]

        # insert the deletes into django
        for delete in deletes:
            d = AsyncDeletion.objects.create(
                team_id=delete[0],
                deletion_type=delete[1],
                key=delete[2],
                delete_verified_at=delete[3],
                # for team deletes, we don't care about the created_at. If a team deletion was requested, we need to delete all its data.
                created_at=None,
            )
            d.save()

    insert_pending_deletes()

    def get_pending_deletes() -> list[AsyncDeletion]:
        return list(AsyncDeletion.objects.filter(delete_verified_at__isnull=True))

    # Check preconditions
    initial_events = cluster.any_host(partial(get_by_team, "writable_events")).result()
    assert len(initial_events) == event_count  # All events present initially

    initial_persons = cluster.any_host(partial(get_by_team, "person")).result()
    assert len(initial_persons) == event_count  # All persons present initially

    initial_groups = cluster.any_host(partial(get_by_team, "groups")).result()
    assert len(initial_groups) == event_count  # All groups present initially

    initial_cohortpeople = cluster.any_host(partial(get_by_team, "cohortpeople")).result()
    assert len(initial_cohortpeople) == event_count  # All cohortpeople present initially

    initial_person_static_cohort = cluster.any_host(partial(get_by_team, "person_static_cohort")).result()
    assert len(initial_person_static_cohort) == event_count  # All person_static_cohort present initially

    initial_plugin_log_entries = cluster.any_host(partial(get_by_team, "plugin_log_entries")).result()
    assert len(initial_plugin_log_entries) == event_count  # All plugin_log_entries present initially

    initial_person_distinct_id2 = cluster.any_host(partial(get_by_team, "person_distinct_id2")).result()
    assert len(initial_person_distinct_id2) == event_count  # All person_distinct_id2 present initially

    pending_deletes = get_pending_deletes()
    assert len(pending_deletes) == delete_count

    # Run the deletion job
    deletes_job.execute_in_process(
        run_config={"ops": {"create_pending_deletions_table": {"config": {"timestamp": timestamp.isoformat()}}}},
        resources={"cluster": cluster},
    )

    # Check postconditions
    final_events = cluster.any_host(partial(get_by_team, "writable_events")).result()
    assert len(final_events) == event_count - delete_count, f"expected events data was not deleted"

    final_persons = cluster.any_host(partial(get_by_team, "person")).result()
    assert len(final_persons) == event_count - delete_count, f"expected person data was not deleted"

    final_groups = cluster.any_host(partial(get_by_team, "groups")).result()
    assert len(final_groups) == event_count - delete_count, f"expected groups data was not deleted"

    # final_cohortpeople = cluster.any_host(partial(get_by_team, "cohortpeople")).result()
    # assert len(final_cohortpeople) == event_count - delete_count, f"expected cohortpeople data was not deleted"

    final_person_static_cohort = cluster.any_host(partial(get_by_team, "person_static_cohort")).result()
    assert (
        len(final_person_static_cohort) == event_count - delete_count
    ), f"expected person_static_cohort data was not deleted"

    final_plugin_log_entries = cluster.any_host(partial(get_by_team, "plugin_log_entries")).result()
    assert (
        len(final_plugin_log_entries) == event_count - delete_count
    ), f"expected plugin_log_entries data was not deleted"

    final_person_distinct_id2 = cluster.any_host(partial(get_by_team, "person_distinct_id2")).result()
    assert (
        len(final_person_distinct_id2) == event_count - delete_count
    ), f"expected person_distinct_id2 data was not deleted"

    # Check that events for non-deleted teams were actually not deleted
    assert all(
        event[0] in final_events.keys() for event in events if event[0] not in range(delete_count)
    ), f"There are events for non-deleted teams that were deleted"

    # Verify that the deletions for the teams have been marked verified
    marked_deletions = AsyncDeletion.objects.filter(
        team_id__in=list(range(delete_count)), delete_verified_at__isnull=False
    )
    assert len(marked_deletions) == delete_count

    # Verify the temporary tables were cleaned up
    table = PendingDeletesTable(timestamp=timestamp)
    assert not any(cluster.map_all_hosts(table.exists).result().values())
    deletes_dict = PendingDeletesDictionary(source=table)
    assert not any(cluster.map_all_hosts(deletes_dict.exists).result().values())


@pytest.mark.django_db
def test_full_job_adhoc_event_deletes(cluster: ClickhouseCluster):
    timestamp = (datetime.now() + timedelta(days=31)).replace(
        microsecond=0
    )  # we don't freeze time because we are namespaced by time
    event_count = 10000
    delete_count = 1000

    events = [(i, f"distinct_id_{i}", UUID(int=i), timestamp) for i in range(event_count)]

    def insert_events(client: Client) -> None:
        client.execute(
            """INSERT INTO writable_events (team_id, distinct_id, uuid, timestamp)
            VALUES
            """,
            events,
        )

    def get_by_team_and_uuid(table: str, client: Client) -> dict[tuple[int, UUID], int]:
        result = client.execute(f"SELECT team_id, uuid, count(1) FROM {table} GROUP BY team_id, uuid")
        if not isinstance(result, list):
            return {}
        return {(row[0], row[1]): row[2] for row in result}

    # Insert some pending deletions
    def insert_adhoc_event_deletes(client: Client) -> None:
        deletes = [(events[i][0], events[i][2]) for i in range(delete_count)]

        client.execute(
            """INSERT INTO adhoc_events_deletion (team_id, uuid)
            VALUES
            """,
            deletes,
        )

    def get_pending_deletes(client: Client) -> int:
        result = client.execute(f"SELECT count() FROM adhoc_events_deletion FINAL")
        if not isinstance(result, list):
            return 0
        return result[0][0]

    def get_optimized_rows(client: Client) -> int:
        result = client.execute(f"SELECT count() FROM adhoc_events_deletion WHERE is_deleted = 1")
        if not isinstance(result, list):
            return 0
        return result[0][0]

    cluster.any_host(insert_events).result()
    cluster.any_host(insert_adhoc_event_deletes).result()

    # Check preconditions
    initial_events = cluster.any_host(partial(get_by_team_and_uuid, "writable_events")).result()
    assert len(initial_events) == event_count  # All events present initially

    pending_deletes = cluster.any_host(get_pending_deletes).result()
    assert pending_deletes == delete_count

    # Run the deletion job
    deletes_job.execute_in_process(
        run_config={"ops": {"create_pending_deletions_table": {"config": {"timestamp": timestamp.isoformat()}}}},
        resources={"cluster": cluster},
    )

    # Check postconditions
    final_events = cluster.any_host(partial(get_by_team_and_uuid, "writable_events")).result()
    assert len(final_events) == event_count - delete_count, f"expected events data was not deleted"

    pending_deletes = cluster.any_host(get_pending_deletes).result()
    assert pending_deletes == 0, "there are events pending to be deleted"

    # Check that the events deletion table was optimized. We should have all rows marked as deleted.
    total_rows = cluster.any_host(get_optimized_rows).result()
    assert total_rows == delete_count, "Table was not optimized"

    # Check that events for non-deleted teams were actually not deleted
    assert all(
        (event[0], event[2]) in final_events.keys() for event in events if event[0] not in range(delete_count)
    ), f"There are non-requested deleted events that were deleted"
    # Verify the temporary tables were cleaned up
    deletes_dict = AdhocEventDeletesDictionary(source=AdhocEventDeletesTable())
    assert not any(cluster.map_all_hosts(deletes_dict.exists).result().values())
