from __future__ import annotations

import logging
from dataclasses import dataclass

import structlog
from django.core.management.base import BaseCommand

from posthog.clickhouse.client.connection import Workload
from posthog.clickhouse.client.execute import sync_execute
from datetime import datetime

from posthog.models.sessions.sql import get_session_table_mv_select_sql

logger = structlog.get_logger(__name__)


SETTINGS = {
    "max_execution_time": 3600  # 1 hour
}


@dataclass
class RecreateSessionsTable:
    month: datetime
    use_offline_workload: bool

    def execute(self, print_counts=False) -> None:
        logger.info(f"Recreating sessions table for {self.month.strftime('%Y-%m')}")

        events_where = f"toYYYYMM(timestamp) = {self.month.strftime('%Y%m')}"
        sessions_where = f"toYYYYMM(min_timestamp) = {self.month.strftime('%Y%m')}"
        select_query = get_session_table_mv_select_sql(source_column_mode="json_or_mat", extra_where=events_where)

        if print_counts:
            count_query = f"SELECT count(), uniq(session_id) FROM sharded_sessions WHERE {sessions_where}"
            [(sessions_row_count, sessions_event_count)] = sync_execute(count_query, settings=SETTINGS)
            logger.info(f"{sessions_row_count} rows and {sessions_event_count} unique session_ids in sessions table")

        logging.info("Deleting the existing sessions for month %s", self.month.strftime("%Y-%m"))
        sync_execute(
            query=f"""ALTER TABLE sharded_sessions DROP PARTITION {self.month.strftime('%Y%m')}""",
            workload=Workload.OFFLINE if self.use_offline_workload else Workload.DEFAULT,
            settings=SETTINGS,
        )

        if print_counts:
            count_query = f"SELECT count(), uniq(session_id) FROM ({select_query})"
            [(sessions_row_count, sessions_event_count)] = sync_execute(count_query, settings=SETTINGS)
            logger.info(f"{sessions_row_count} rows and {sessions_event_count} unique session_ids in events table")

        logging.info("Writing the new sessions for day %s", self.month.strftime("%Y-%m"))
        sync_execute(
            query=f"""INSERT INTO writable_sessions {select_query}""",
            workload=Workload.OFFLINE if self.use_offline_workload else Workload.DEFAULT,
            settings=SETTINGS,
        )

        if print_counts:
            count_query = f"SELECT count(), uniq(session_id) FROM sharded_sessions WHERE {sessions_where}"
            [(sessions_row_count, sessions_event_count)] = sync_execute(count_query, settings=SETTINGS)
            logger.info(f"{sessions_row_count} rows and {sessions_event_count} unique session_ids in sessions table")


class Command(BaseCommand):
    help = "Backfill person_distinct_id_overrides records."

    def add_arguments(self, parser):
        parser.add_argument("--month", required=True, type=str, help="Month to replace (format YYYY-MM)")
        parser.add_argument(
            "--use-offline-workload", action="store_true", help="Where possible, use the offline workload"
        )
        parser.add_argument(
            "--print-counts",
            required=False,
            action="store_true",
            help="Print the number of rows and session ids at each stage",
        )

    def handle(
        self,
        *,
        month: str,
        use_offline_workload: bool,
        print_counts: bool = False,
        **options,
    ):
        logger.setLevel(logging.INFO)

        month_datetime = datetime.strptime(month, "%Y-%m")

        RecreateSessionsTable(month_datetime, use_offline_workload).execute(print_counts=print_counts)
