from collections.abc import Iterator
from datetime import datetime, timedelta
from uuid import UUID


import pytest
from clickhouse_driver import Client

from django.conf import settings
from dags.deletes import (
    deletes_job,
    PendingPersonEventDeletesTable,
)
from posthog.clickhouse.cluster import ClickhouseCluster, get_cluster
from posthog.models.async_deletion import AsyncDeletion, DeletionType


@pytest.fixture
def cluster(django_db_setup) -> Iterator[ClickhouseCluster]:
    yield get_cluster()


@pytest.mark.django_db
def test_full_job(cluster: ClickhouseCluster):
    timestamp = datetime.now() + timedelta(days=31)
    event_count = 10000
    delete_count = 1000
    hour_lookback = 24

    events = [(i, f"distinct_id_{i}", UUID(int=i), timestamp - timedelta(hours=i)) for i in range(event_count)]

    def truncate_events(client: Client) -> None:
        client.execute(f"TRUNCATE TABLE sharded_events ON CLUSTER '{settings.CLICKHOUSE_CLUSTER}'")

    cluster.any_host(truncate_events).result()

    def insert_events(client: Client) -> None:
        client.execute(
            """INSERT INTO writable_events (team_id, distinct_id, person_id, timestamp)
            VALUES
            """,
            events,
        )

    cluster.any_host(insert_events).result()

    def get_events_by_person_team(client: Client) -> dict[tuple[int, UUID], int]:
        result = client.execute("SELECT team_id, person_id, count(1) FROM writable_events GROUP BY team_id, person_id")
        if not isinstance(result, list):
            return {}
        return {(row[0], row[1]): row[2] for row in result}

    # Insert some pending deletions
    def insert_pending_deletes() -> None:
        deletes = [(events[i][0], DeletionType.Person, events[i][1], None) for i in range(delete_count)]

        # insert the deletes into django
        for delete in deletes:
            AsyncDeletion.objects.create(
                team_id=delete[0],
                deletion_type=delete[1],
                key=delete[2],
                delete_verified_at=delete[3],
            ).save()

    insert_pending_deletes()

    def get_pending_deletes() -> list[AsyncDeletion]:
        return list(AsyncDeletion.objects.filter(delete_verified_at__isnull=True))

    # Check preconditions
    initial_events = cluster.any_host(get_events_by_person_team).result()
    assert len(initial_events) == event_count  # All events present initially

    pending_deletes = get_pending_deletes()
    assert len(pending_deletes) == delete_count

    # Run the deletion job
    deletes_job.execute_in_process(
        run_config={
            "ops": {"create_pending_deletes_table": {"config": {"timestamp": timestamp.isoformat(), "cleanup": False}}}
        },
        resources={"cluster": cluster},
    )

    # Check postconditions
    final_events = cluster.any_host(get_events_by_person_team).result()
    assert len(final_events) == event_count - delete_count  # Only events for non-deleted persons remain
    assert UUID(int=hour_lookback - 1) in final_events  # Person 3 events remain (future deletion)
    assert UUID(int=delete_count + 1) in final_events  # Person 4 events remain (not marked for deletion)

    # Verify the temporary tables were cleaned up
    table = PendingPersonEventDeletesTable(timestamp=timestamp)
    assert not any(cluster.map_all_hosts(table.exists).result().values())
