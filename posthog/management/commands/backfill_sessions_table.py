from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Optional

import structlog
from django.core.management.base import BaseCommand

from posthog.clickhouse.client.execute import sync_execute
from posthog.models.property.util import get_property_string_expr
from datetime import datetime, timedelta

logger = structlog.get_logger(__name__)


TARGET_TABLE = "sessions"


@dataclass
class BackfillQuery:
    start_date: datetime
    end_date: datetime

    def execute(
        self,
        dry_run: bool = True,
    ) -> None:
        def source_column(column_name: str) -> str:
            return get_property_string_expr(
                "events", property_name=column_name, var=f"'{column_name}'", column="properties"
            )[0]

        num_days = (self.end_date - self.start_date).days + 1

        logger.info(
            f"Backfilling sessions table from {self.start_date.strftime('%Y-%m-%d')} to {self.end_date.strftime('%Y-%m-%d')}, total numbers of days to insert: {num_days}"
        )

        current_url_property = source_column("$current_url")
        referring_domain_property = source_column("$referring_domain")
        utm_source_property = source_column("utm_source")
        utm_campaign_property = source_column("utm_campaign")
        utm_medium_property = source_column("utm_medium")
        utm_term_property = source_column("utm_term")
        utm_content_property = source_column("utm_content")
        gclid_property = source_column("gclid")
        gad_source_property = source_column("gad_source")

        def select_query(date: Optional[datetime] = None) -> str:
            if date:
                where = f"toStartOfDay(timestamp) = '{date.strftime('%Y-%m-%d')}'"
            else:
                where = "true"

            return f"""
SELECT
    `$session_id` as session_id,
    team_id,

    distinct_id,

    timestamp AS min_first_timestamp,
    timestamp AS max_last_timestamp,

    [{current_url_property}] AS urls,
    initializeAggregation('argMinState', {current_url_property}, timestamp) as entry_url,
    initializeAggregation('argMaxState', {current_url_property}, timestamp) as exit_url,

    initializeAggregation('argMinState', {referring_domain_property}, timestamp) as initial_referring_domain,
    initializeAggregation('argMinState', {utm_source_property}, timestamp) as initial_utm_source,
    initializeAggregation('argMinState', {utm_campaign_property}, timestamp) as initial_utm_campaign,
    initializeAggregation('argMinState', {utm_medium_property}, timestamp) as initial_utm_medium,
    initializeAggregation('argMinState', {utm_term_property}, timestamp) as initial_utm_term,
    initializeAggregation('argMinState', {utm_content_property}, timestamp) as initial_utm_content,
    initializeAggregation('argMinState', {gclid_property}, timestamp) as initial_gclid,
    initializeAggregation('argMinState', {gad_source_property}, timestamp) as initial_gad_source,

    CAST(([event], [1]), 'Map(String, UInt64)') as event_count_map,
    if(event='$pageview', 1, NULL) as pageview_count,
    if(event='$autocapture', 1, NULL) as autocapture_count

FROM events
WHERE `$session_id` IS NOT NULL AND `$session_id` != '' AND {where}
        """

        # print the count of entries in the main sessions table
        count_query = f"SELECT count(), uniq(session_id) FROM {TARGET_TABLE}"
        [(sessions_row_count, sessions_event_count)] = sync_execute(count_query)
        logger.info(f"{sessions_row_count} rows and {sessions_event_count} unique session_ids in sessions table")

        if dry_run:
            count_query = f"SELECT count(), uniq(session_id) FROM ({select_query()})"
            [(events_count, sessions_count)] = sync_execute(count_query)
            logger.info(f"{events_count} events and {sessions_count} sessions to backfill for")
            logger.info(f"The first select query would be:\n{select_query(self.start_date)}")
            return

        for i in range(num_days):
            date = self.start_date + timedelta(days=i)
            logging.info("Writing the sessions for day %s", date.strftime("%Y-%m-%d"))
            sync_execute(f"""INSERT INTO writable_sessions {select_query(date=date)}""")

        # print the count of entries in the main sessions table
        count_query = f"SELECT count(), uniq(session_id) FROM {TARGET_TABLE}"
        [(sessions_row_count, sessions_event_count)] = sync_execute(count_query)
        logger.info(f"{sessions_row_count} rows and {sessions_event_count} unique session_ids in sessions table")


class Command(BaseCommand):
    help = "Backfill person_distinct_id_overrides records."

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

    def handle(self, *, live_run: bool, start_date: str, end_date: str, **options):
        logger.setLevel(logging.INFO)

        start_date = datetime.strptime(start_date, "%Y-%m-%d")
        end_date = datetime.strptime(end_date, "%Y-%m-%d")

        BackfillQuery(start_date, end_date).execute(dry_run=not live_run)
