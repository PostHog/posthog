from posthog.clickhouse.client import sync_execute


def remove_deleted_person_data(mutations_sync=False):
    settings = {"mutations_sync": 1 if mutations_sync else 0}
    sync_execute(
        """
        ALTER TABLE person
        DELETE WHERE id IN (SELECT id FROM person WHERE is_deleted > 0)
        """,
        settings=settings,
    )
