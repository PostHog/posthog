from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Optional

from django.core.management.base import BaseCommand

import structlog

from posthog.clickhouse.client.connection import Workload
from posthog.clickhouse.client.execute import sync_execute
from posthog.models.property.util import get_property_string_expr

logger = structlog.get_logger(__name__)

TARGET_TABLE = "sessions"

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
        gclsrc_property = source_column("gclsrc")
        dclid_property = source_column("dclid")
        gbraid_property = source_column("gbraid")
        wbraid_property = source_column("wbraid")
        fbclid_property = source_column("fbclid")
        msclkid_property = source_column("msclkid")
        twclid_property = source_column("twclid")
        li_fat_id_property = source_column("li_fat_id")
        mc_cid_property = source_column("mc_cid")
        igshid_property = source_column("igshid")
        ttclid_property = source_column("ttclid")

        def select_query(select_date: Optional[datetime] = None, team_id=None) -> str:
            if select_date:
                where = f"toStartOfDay(timestamp) = '{select_date.strftime('%Y-%m-%d')}'"
            else:
                where = "true"

            if team_id is not None:
                team_where = f"team_id = {team_id}"
            else:
                team_where = "true"

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
    initializeAggregation('argMinState', {gclsrc_property}, timestamp) as initial_gclsrc,
    initializeAggregation('argMinState', {dclid_property}, timestamp) as initial_dclid,
    initializeAggregation('argMinState', {gbraid_property}, timestamp) as initial_gbraid,
    initializeAggregation('argMinState', {wbraid_property}, timestamp) as initial_wbraid,
    initializeAggregation('argMinState', {fbclid_property}, timestamp) as initial_fbclid,
    initializeAggregation('argMinState', {msclkid_property}, timestamp) as initial_msclkid,
    initializeAggregation('argMinState', {twclid_property}, timestamp) as initial_twclid,
    initializeAggregation('argMinState', {li_fat_id_property}, timestamp) as initial_li_fat_id,
    initializeAggregation('argMinState', {mc_cid_property}, timestamp) as initial_mc_cid,
    initializeAggregation('argMinState', {igshid_property}, timestamp) as initial_igshid,
    initializeAggregation('argMinState', {ttclid_property}, timestamp) as initial_ttclid,

    CAST(([event], [1]), 'Map(String, UInt64)') as event_count_map,
    if(event='$pageview', 1, NULL) as pageview_count,
    if(event='$autocapture', 1, NULL) as autocapture_count

FROM events
WHERE `$session_id` IS NOT NULL AND `$session_id` != '' AND {where} AND {team_where}
        """

        # print the count of entries in the main sessions table
        if print_counts:
            count_query = f"SELECT count(), uniq(session_id) FROM {TARGET_TABLE}"
            [(sessions_row_count, sessions_event_count)] = sync_execute(count_query, settings=SETTINGS)
            logger.info(f"{sessions_row_count} rows and {sessions_event_count} unique session_ids in sessions table")

        if dry_run:
            count_query = f"SELECT count(), uniq(session_id) FROM ({select_query()})"
            [(events_count, sessions_count)] = sync_execute(count_query, settings=SETTINGS)
            logger.info(f"{events_count} events and {sessions_count} sessions to backfill for")
            logger.info(f"The first select query would be:\n{select_query(self.start_date)}")
            return

        for i in range(num_days):
            date = self.start_date + timedelta(days=i)
            logging.info("Writing the sessions for day %s", date.strftime("%Y-%m-%d"))
            insert_query = (
                f"""INSERT INTO writable_sessions {select_query(select_date=date)} SETTINGS max_execution_time=3600"""
            )
            sync_execute(
                query=insert_query,
                workload=Workload.OFFLINE if self.use_offline_workload else Workload.DEFAULT,
                settings=SETTINGS,
            )

        # print the count of entries in the main sessions table
        if print_counts:
            count_query = f"SELECT count(), uniq(session_id) FROM {TARGET_TABLE}"
            [(sessions_row_count, sessions_event_count)] = sync_execute(count_query, settings=SETTINGS)
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
        parser.add_argument(
            "--use-offline-workload", action="store_true", help="actually execute INSERT queries (default is dry-run)"
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
        use_offline_workload: bool,
        print_counts: bool,
        team_id: Optional[int],
        **options,
    ):
        logger.setLevel(logging.INFO)

        start_datetime = datetime.strptime(start_date, "%Y-%m-%d")
        end_datetime = datetime.strptime(end_date, "%Y-%m-%d")

        BackfillQuery(start_datetime, end_datetime, use_offline_workload, team_id=team_id).execute(
            dry_run=not live_run,
            print_counts=print_counts,
        )
