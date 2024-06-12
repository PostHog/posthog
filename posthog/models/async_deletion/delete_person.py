from posthog.clickhouse.client import sync_execute

from posthog.models.async_deletion import MAX_QUERY_SIZE

from posthog.clickhouse.client.connection import Workload


def remove_deleted_person_data(mutations_sync=False):
    settings = {"mutations_sync": 1 if mutations_sync else 0, "max_query_size": MAX_QUERY_SIZE}
    sync_execute(
        """
        ALTER TABLE person
        DELETE WHERE id IN (SELECT id FROM person WHERE is_deleted > 0)
        """,
        settings=settings,
        workload=Workload.OFFLINE,
    )
