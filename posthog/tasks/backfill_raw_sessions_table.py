import time
from typing import Optional

import structlog

from datetime import datetime, timedelta
from posthog.clickhouse.client import sync_execute
from posthog.clickhouse.client.connection import Workload
from posthog.models.raw_sessions.sql import RAW_SESSION_TABLE_BACKFILL_SELECT_SQL

logger = structlog.get_logger(__name__)

TARGET_TABLE = "raw_sessions"

SETTINGS = {
    "max_execution_time": 3600  # 1 hour
}


def run_backfill_raw_sessions_table_for_day(
    date: datetime, team_id: Optional[int] = None, use_offline_workload: bool = True
):
    time.sleep(10)
    logger.info(f"Starting backfill for {date.strftime('%Y-%m-%d')}")
    date_where = f"toStartOfDay(timestamp) = '{date.strftime('%Y-%m-%d')}'"

    if team_id is not None:
        team_where = f"team_id = {team_id}"
    else:
        team_where = "true"

    select_query = (
        RAW_SESSION_TABLE_BACKFILL_SELECT_SQL()
        + f"""
AND and(
    {date_where},
    {team_where}
)"""
    )

    insert_query = f"""INSERT INTO {TARGET_TABLE} {select_query} SETTINGS max_execution_time=3600"""
    sync_execute(
        query=insert_query,
        workload=Workload.OFFLINE if use_offline_workload else Workload.DEFAULT,
        settings=SETTINGS,
    )
    logger.info(f"Finished backfill for {date.strftime('%Y-%m-%d')}")


def get_days_to_backfill(start_date: datetime, end_date: datetime):
    num_days = (end_date - start_date).days + 1
    return [start_date + timedelta(days=i) for i in reversed(range(num_days))]
