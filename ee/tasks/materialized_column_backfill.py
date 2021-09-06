from ee.clickhouse.client import sync_execute
from ee.clickhouse.materialized_columns.columns import TRIM_AND_EXTRACT_PROPERTY, get_materialized_columns
from posthog.celery import app
from posthog.models.property import PropertyName, TableWithProperties
from posthog.settings import CLICKHOUSE_CLUSTER, CLICKHOUSE_REPLICATION

DELAY_SECONDS = 4 * 60 * 60


@app.task(ignore_result=True, max_retries=3)
def check_backfill_done(table: TableWithProperties, property: PropertyName) -> None:
    should_retry = True

    try:
        updated_table = "sharded_events" if CLICKHOUSE_REPLICATION and table == "events" else table
        # :TRICKY: On cloud, we ON CLUSTER updates to events/sharded_events but not to persons. Why? ¯\_(ツ)_/¯
        execute_on_cluster = f"ON CLUSTER {CLICKHOUSE_CLUSTER}" if table == "events" else ""
        column_name = get_materialized_columns(table, use_cache=False)[property]

        results = sync_execute(
            f"""
            SELECT count(*)
            FROM system.mutations
            WHERE table = '{table}'
              AND command LIKE '%UPDATE%'
              AND command LIKE '%{column_name} = {column_name}%'
        """
        )

        if results[0][0] == 0:
            sync_execute(
                f"""
                ALTER TABLE {updated_table}
                {execute_on_cluster}
                MODIFY COLUMN
                {column_name} VARCHAR MATERIALIZED {TRIM_AND_EXTRACT_PROPERTY}
                """,
                {"property": property},
            )
            should_retry = False
    finally:
        if should_retry:
            check_backfill_done.apply_async((table, property,), countdown=DELAY_SECONDS)
