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
    date: datetime
    use_offline_workload: bool

    def execute(
        self,
    ) -> None:
        logger.info(f"Recreating sessions table for {self.date.strftime('%Y-%m-%d')}")

        events_where = f"toStartOfDay(timestamp) = '{self.date.strftime('%Y-%m-%d')}'"
        sessions_where = f"toStartOfDay(min_timestamp) = '{self.date.strftime('%Y-%m-%d')}'"
        select_query = get_session_table_mv_select_sql(source_column_mode="json_or_mat", extra_where=events_where)

        logging.info("Deleting the existing sessions for day %s", self.date.strftime("%Y-%m-%d"))
        sync_execute(
            query=f"""DELETE FROM sharded_sessions WHERE {sessions_where}""",
            workload=Workload.OFFLINE if self.use_offline_workload else Workload.DEFAULT,
            settings=SETTINGS,
        )

        logging.info("Writing the new sessions for day %s", self.date.strftime("%Y-%m-%d"))
        sync_execute(
            query=f"""INSERT INTO writable_sessions {select_query}""",
            workload=Workload.OFFLINE if self.use_offline_workload else Workload.DEFAULT,
            settings=SETTINGS,
        )


class Command(BaseCommand):
    help = "Backfill person_distinct_id_overrides records."

    def add_arguments(self, parser):
        parser.add_argument("--date", required=True, type=str, help="Day to replace (format YYYY-MM-DD)")
        parser.add_argument(
            "--use-offline-workload", action="store_true", help="actually execute INSERT queries (default is dry-run)"
        )

    def handle(
        self,
        *,
        date: str,
        use_offline_workload: bool,
        **options,
    ):
        logger.setLevel(logging.INFO)

        date_datetime = datetime.strptime(date, "%Y-%m-%d")

        RecreateSessionsTable(date_datetime, use_offline_workload).execute()
