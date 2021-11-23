import logging

from django.core.management.base import BaseCommand

from ee.clickhouse.client import sync_execute
from ee.clickhouse.materialized_columns.analyze import logger
from ee.clickhouse.materialized_columns.columns import TablesWithMaterializedColumns
from posthog.settings import CLICKHOUSE_CLUSTER, CLICKHOUSE_REPLICATION


class Command(BaseCommand):
    help = "Backfill full snapshot materialized column"

    def handle(self, *args, **options):
        logger.setLevel(logging.INFO)

        recording_table_name: TablesWithMaterializedColumns = "session_recording_events"

        updated_table = "sharded_{recording_table_name}" if CLICKHOUSE_REPLICATION else recording_table_name

        # Hack from https://github.com/ClickHouse/ClickHouse/issues/19785
        # Note that for this to work all inserts should list columns explicitly
        # Improve this if https://github.com/ClickHouse/ClickHouse/issues/27730 ever gets resolved
        sync_execute(
            f"""
            ALTER TABLE {updated_table}
            ON CLUSTER {CLICKHOUSE_CLUSTER}
            MODIFY COLUMN pmat_has_full_snapshot
            BOOLEAN DEFAULT JSONExtractBool(snapshot_data, 'has_full_snapshot')
            """
        )

        sync_execute(
            f"""
            ALTER TABLE {updated_table}
            ON CLUSTER {CLICKHOUSE_CLUSTER}
            UPDATE pmat_has_full_snapshot = JSONExtractBool(snapshot_data, 'has_full_snapshot') WHERE 1=1
            """
        )
