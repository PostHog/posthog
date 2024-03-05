from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Optional

import structlog
from django.core.management.base import BaseCommand, CommandError

from posthog.clickhouse.client.execute import sync_execute
from posthog.models.property.util import get_property_string_expr
from posthog.models.team.team import Team

logger = structlog.get_logger(__name__)


TARGET_TABLE = "sessions"


@dataclass
class BackfillQuery:
    team_id: int

    def execute(self, dry_run: bool = True, month: Optional[str] = None) -> None:
        where = "true"
        if month is not None:
            where = f"toYYYYMM(timestamp) < {month}"

        def source_column(column_name: str) -> str:
            return get_property_string_expr(
                "events", property_name=column_name, var=f"'{column_name}'", column="properties"
            )[0]

        current_url_property = source_column("$current_url")
        referring_domain_property = source_column("$referring_domain")
        utm_source_property = source_column("utm_source")
        utm_campaign_property = source_column("utm_campaign")
        utm_medium_property = source_column("utm_medium")
        utm_term_property = source_column("utm_term")
        utm_content_property = source_column("utm_content")
        gclid_property = source_column("gclid")
        gad_source_property = source_column("gad_source")

        select_query = f"""
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
WHERE team_id = %(team_id)s AND `$session_id` IS NOT NULL AND `$session_id` != '' AND {where}
        """

        # print the count of entries in the main sessions table
        count_query = f"SELECT count(), uniq(session_id) FROM {TARGET_TABLE}"
        [(sessions_row_count, sessions_event_count)] = sync_execute(count_query, {"team_id": self.team_id})
        logger.info(f"{sessions_row_count} rows and {sessions_event_count} unique session_ids in sessions table")

        if dry_run:
            count_query = f"SELECT count(), uniq(session_id) FROM ({select_query})"
            [(events_count, sessions_count)] = sync_execute(count_query, {"team_id": self.team_id})
            logger.info(f"{events_count} events and {sessions_count} sessions to backfill for team {self.team_id}")
            return

        logging.info("Populating the import table with the data we want to backfill, using a partition expression")
        sync_execute(f"""INSERT INTO writable_sessions {select_query}""", {"team_id": self.team_id})

        # print the count of entries in the main sessions table
        count_query = f"SELECT count(), uniq(session_id) FROM {TARGET_TABLE}"
        [(sessions_row_count, sessions_event_count)] = sync_execute(count_query, {"team_id": self.team_id})
        logger.info(f"{sessions_row_count} rows and {sessions_event_count} unique session_ids in sessions table")


class Command(BaseCommand):
    help = "Backfill person_distinct_id_overrides records."

    def add_arguments(self, parser):
        parser.add_argument("--team-id", required=True, type=int, help="team to backfill for")
        parser.add_argument("--month", type=str, help="month to backfill for (format: YYYY-MM)")
        parser.add_argument(
            "--live-run", action="store_true", help="actually execute INSERT queries (default is dry-run)"
        )

    def handle(self, *, live_run: bool, team_id: int, **options):
        logger.setLevel(logging.INFO)

        if not Team.objects.filter(id=team_id).exists():
            raise CommandError(f"Team with id={team_id!r} does not exist")

        BackfillQuery(team_id).execute(dry_run=not live_run)
