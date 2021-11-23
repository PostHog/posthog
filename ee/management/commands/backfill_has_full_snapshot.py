from django.core.management.base import BaseCommand

from ee.clickhouse.client import sync_execute
from ee.clickhouse.sql.session_recording_events import SESSION_RECORDING_EVENTS_TABLE
from posthog.settings import CLICKHOUSE_CLUSTER, CLICKHOUSE_REPLICATION


class Command(BaseCommand):
    help = "Backfill the has_full_snapshot materialized column on session_recording_events"

    def handle(self, *args, **options):
        updated_table = (
            f"sharded_{SESSION_RECORDING_EVENTS_TABLE}" if CLICKHOUSE_REPLICATION else SESSION_RECORDING_EVENTS_TABLE
        )

        # Hack from https://github.com/ClickHouse/ClickHouse/issues/19785
        # Note that for this to work all inserts should list columns explicitly
        # Improve this if https://github.com/ClickHouse/ClickHouse/issues/27730 ever gets resolved
        sync_execute(
            f"""
            ALTER TABLE {updated_table}
            ON CLUSTER {CLICKHOUSE_CLUSTER}
            MODIFY COLUMN has_full_snapshot
            BOOLEAN DEFAULT JSONExtractBool(snapshot_data, 'has_full_snapshot')
            """
        )

        sync_execute(
            f"""
            ALTER TABLE {updated_table}
            ON CLUSTER {CLICKHOUSE_CLUSTER}
            UPDATE has_full_snapshot = JSONExtractBool(snapshot_data, 'has_full_snapshot') WHERE 1=1
            """
        )
