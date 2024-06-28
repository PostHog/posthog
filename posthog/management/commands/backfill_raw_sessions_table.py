from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Optional

import structlog
from django.core.management.base import BaseCommand

from posthog.clickhouse.client.connection import Workload
from posthog.clickhouse.client.execute import sync_execute
from datetime import datetime, timedelta

from posthog.models.raw_sessions.sql import RAW_SESSION_TABLE_BACKFILL_SELECT_SQL

logger = structlog.get_logger(__name__)

TARGET_TABLE = "raw_sessions"

SETTINGS = {
    "max_execution_time": 3600  # 1 hour
}


@dataclass
class BackfillQuery:
    start_date: datetime
    end_date: datetime
    use_offline_workload: bool
    team_id: Optional[int]

    def execute(
        self,
        dry_run: bool = True,
        print_counts: bool = True,
    ) -> None:
        num_days = (self.end_date - self.start_date).days + 1

        logger.info(
            f"Backfilling sessions table from {self.start_date.strftime('%Y-%m-%d')} to {self.end_date.strftime('%Y-%m-%d')}, total numbers of days to insert: {num_days}"
        )

        def select_query(select_date: Optional[datetime] = None, team_id=None) -> str:
            if select_date:
                date_where = f"toStartOfDay(timestamp) = '{select_date.strftime('%Y-%m-%d')}'"
            else:
                date_where = "true"

            if team_id is not None:
                team_where = f"team_id = {team_id}"
            else:
                team_where = "true"

            return (
                RAW_SESSION_TABLE_BACKFILL_SELECT_SQL()
                + f"""
AND and(
    {date_where},
    {team_where}
)"""
            )

        # print the count of entries in the main sessions table
        if print_counts:
            count_query = f"SELECT count(), uniq(session_id_v7) FROM {TARGET_TABLE}"
            [(sessions_row_count, sessions_event_count)] = sync_execute(count_query, settings=SETTINGS)
            logger.info(
                f"{sessions_row_count} rows and {sessions_event_count} unique session_ids in {TARGET_TABLE} table"
            )

        if dry_run:
            count_query = f"SELECT count(), uniq(session_id_v7) FROM ({select_query()})"
            [(events_count, sessions_count)] = sync_execute(count_query, settings=SETTINGS)
            logger.info(f"{events_count} events and {sessions_count} sessions to backfill for")
            logger.info(f"The first select query to run would be:\n{select_query(self.end_date)}")
            return

        for i in reversed(range(num_days)):
            date = self.start_date + timedelta(days=i)
            logging.info("Writing the sessions for day %s", date.strftime("%Y-%m-%d"))
            insert_query = (
                f"""INSERT INTO {TARGET_TABLE} {select_query(select_date=date)} SETTINGS max_execution_time=3600"""
            )
            sync_execute(
                query=insert_query,
                workload=Workload.OFFLINE if self.use_offline_workload else Workload.DEFAULT,
                settings=SETTINGS,
            )

        # print the count of entries in the main sessions table
        if print_counts:
            count_query = f"SELECT count(), uniq(session_id_v7) FROM {TARGET_TABLE}"
            [(sessions_row_count, sessions_event_count)] = sync_execute(count_query, settings=SETTINGS)
            logger.info(
                f"{sessions_row_count} rows and {sessions_event_count} unique session_ids in {TARGET_TABLE} table"
            )


class Command(BaseCommand):
    help = f"Backfill the {TARGET_TABLE} table from events."

    def add_arguments(self, parser):
        parser.add_argument(
            "--start-date", required=True, type=str, help="first day to run backfill on (format YYYY-MM-DD)"
        )
        parser.add_argument(
            "--end-date", required=True, type=str, help="last day to run backfill, inclusive, on (format YYYY-MM-DD)"
        )
        parser.add_argument(
            "--live-run", action="store_true", help="actually execute INSERT queries (default is dry-run)"
        )
        parser.add_argument(
            "--no-use-offline-workload",
            action="store_true",
            help="enable this to not run this on the offline nodes. Defaults to running on offline nodes unless this flag is set",
        )
        parser.add_argument(
            "--print-counts", action="store_true", help="print events and session count beforehand and afterwards"
        )
        parser.add_argument("--team-id", type=int, help="Team id (will do all teams if not set)")

    def handle(
        self,
        *,
        live_run: bool,
        start_date: str,
        end_date: str,
        no_use_offline_workload: bool,
        print_counts: bool,
        team_id: Optional[int],
        **options,
    ):
        logger.setLevel(logging.INFO)

        start_datetime = datetime.strptime(start_date, "%Y-%m-%d")
        end_datetime = datetime.strptime(end_date, "%Y-%m-%d")

        BackfillQuery(
            start_datetime, end_datetime, use_offline_workload=not no_use_offline_workload, team_id=team_id
        ).execute(
            dry_run=not live_run,
            print_counts=print_counts,
        )
