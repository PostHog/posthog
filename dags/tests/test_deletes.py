from datetime import datetime, timedelta
from uuid import UUID

import pytest
from clickhouse_driver import Client

from dags.deletes import (
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
    report_table = PendingDeletesTable(timestamp=timestamp, is_reporting=True)
    assert all(cluster.map_all_hosts(report_table.exists).result().values())

    # clean up the reporting table
    cluster.map_all_hosts(report_table.drop).result()


@pytest.mark.django_db
def test_full_job_team_deletes(cluster: ClickhouseCluster):
    timestamp = (datetime.now() + timedelta(days=31)).replace(
        microsecond=0
    )  # we don't freeze time because we are namespaced by time
    event_count = 10000
    delete_count = 1000

    events = [(i, f"distinct_id_{i}", UUID(int=i), timestamp) for i in range(event_count)]

    def insert_events(client: Client) -> None:
        client.execute(
            """INSERT INTO writable_events (team_id, distinct_id, person_id, timestamp)
            VALUES
            """,
            events,
        )

    cluster.any_host(insert_events).result()

    def get_events_by_team(client: Client) -> dict[tuple[int, UUID], int]:
        result = client.execute("SELECT team_id, count(1) FROM writable_events GROUP BY team_id")
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
                created_at=None,  # for team deletes, we don't care about the created_at. If a team deletion was requested, we need to delete all its data.
            )
            d.save()

    insert_pending_deletes()

    def get_pending_deletes() -> list[AsyncDeletion]:
        return list(AsyncDeletion.objects.filter(delete_verified_at__isnull=True))

    # Check preconditions
    initial_events = cluster.any_host(get_events_by_team).result()
    assert len(initial_events) == event_count  # All events present initially

    pending_deletes = get_pending_deletes()
    assert len(pending_deletes) == delete_count

    # Run the deletion job
    deletes_job.execute_in_process(
        run_config={"ops": {"create_pending_deletions_table": {"config": {"timestamp": timestamp.isoformat()}}}},
        resources={"cluster": cluster},
    )

    # Check postconditions
    final_events = cluster.any_host(get_events_by_team).result()
    assert len(final_events) == event_count - delete_count

    # Check that events for non-deleted teams were actually not deleted
    assert all(
        event[0] in final_events.keys() for event in events if event[0] not in range(delete_count)
    ), f"There are events for non-deleted teams that were deleted"

    # Verify that the deletions for the teams have been marked verified
    # TODO: Uncomment next two lines once we setup deletion of all team data in other tables and we actually mark team deletions as processed
    # marked_deletions = AsyncDeletion.objects.filter(
    #     team_id__in=list(range(delete_count)), delete_verified_at__isnull=False
    # )
    # assert len(marked_deletions) == delete_count

    # Verify the temporary tables were cleaned up
    table = PendingDeletesTable(timestamp=timestamp)
    assert not any(cluster.map_all_hosts(table.exists).result().values())
    deletes_dict = PendingDeletesDictionary(source=table)
    assert not any(cluster.map_all_hosts(deletes_dict.exists).result().values())
    report_table = PendingDeletesTable(timestamp=timestamp, is_reporting=True)
    assert all(cluster.map_all_hosts(report_table.exists).result().values())

    # clean up the reporting table
    cluster.map_all_hosts(report_table.drop).result()
