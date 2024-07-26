from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Optional

import structlog
from django.core.management.base import BaseCommand

from datetime import datetime


from posthog.tasks.tasks import backfill_raw_sessions_table

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
    ) -> None:
        task = backfill_raw_sessions_table.apply_async(
            kwargs={
                "start_date": self.start_date,
                "end_date": self.end_date,
                "use_offline_workload": self.use_offline_workload,
                "team_id": self.team_id,
            }
        )
        # wait for completion
        task.get()


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
        team_id: Optional[int],
        **options,
    ):
        logger.setLevel(logging.INFO)

        start_datetime = datetime.strptime(start_date, "%Y-%m-%d")
        end_datetime = datetime.strptime(end_date, "%Y-%m-%d")

        BackfillQuery(
            start_datetime, end_datetime, use_offline_workload=not no_use_offline_workload, team_id=team_id
        ).execute()
