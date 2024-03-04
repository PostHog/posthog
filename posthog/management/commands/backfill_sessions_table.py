from __future__ import annotations

import logging
import time
from dataclasses import dataclass

import structlog
from django.core.management.base import BaseCommand, CommandError

from posthog.clickhouse.client.execute import sync_execute, query_with_columns
from posthog.models.property.util import get_property_string_expr
from posthog.models.team.team import Team

logger = structlog.get_logger(__name__)


TARGET_TABLE = "sessions"


@dataclass
class BackfillQuery:
    team_id: int

    def execute(self, dry_run: bool = True) -> None:
        # Find the earliest timestamp where there is an existing entry in the sessions table, we need to backfill before this point
        timestamp_response = query_with_columns(
            f"""
            SELECT
                min_first_timestamp
            FROM {TARGET_TABLE}
            WHERE
                team_id = %(team_id)s
            ORDER BY min_first_timestamp ASC
        """,
            {"team_id": self.team_id},
        )

        try:
            earliest_existing_timestamp = timestamp_response[0]["min_first_timestamp"]
        except IndexError:
            earliest_existing_timestamp = None

        logger.info(f"Earliest existing timestamp: {earliest_existing_timestamp}")

        where = "true"
        if earliest_existing_timestamp is not None:
            where = (
                f"timestamp < toDateTime64('{earliest_existing_timestamp.isoformat().replace('+00:00', '')}', 6, 'UTC')"
            )

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

    initializeAggregation('sumMapState', ([event], [toInt64(1)])) as event_count_map,
    if(event='$pageview', 1, NULL) as pageview_count,
    if(event='$autocapture', 1, NULL) as autocapture_count

FROM events
WHERE team_id = %(team_id)s AND `$session_id` IS NOT NULL AND `$session_id` != '' AND {where}
        """

        if dry_run:
            count_query = f"SELECT count(), uniq(session_id) FROM ({select_query})"
            [(events_count, sessions_count)] = sync_execute(count_query, {"team_id": self.team_id})
            logger.info(f"{events_count} events and {sessions_count} sessions to backfill for team {self.team_id}")
            return

        # create a new import table, and populate it with the data we want to backfill
        # if that goes to plan then attach the partition to the main sessions table
        # see https://kb.altinity.com/altinity-kb-schema-design/materialized-views/backfill-populate-mv-in-a-controlled-manner/
        partition_number = int(time.time() * 1000)
        import_table_name = f"sessions_import_table_{self.team_id}_{partition_number}"

        logging.info(f"Creating import table {import_table_name}")
        sync_execute(f"""CREATE TABLE {import_table_name} on cluster 'posthog' AS {TARGET_TABLE};""")

        logging.info("Populating the import table with the data we want to backfill, using a partition expression")
        sync_execute(
            f"""INSERT INTO {import_table_name} {select_query} = {partition_number}""", {"team_id": self.team_id}
        )

        # print the count of entries in the import table
        count_query = f"SELECT count(), uniq(session_id) FROM {import_table_name}"
        [(import_table_row_count, import_table_event_count)] = sync_execute(count_query, {"team_id": self.team_id})
        logger.info(f"{import_table_row_count} rows and {import_table_event_count} in import table {import_table_name}")

        # TODO this step fails!
        logging.info(f"Attaching the import table to the {TARGET_TABLE} table")
        sync_execute(
            f"""ALTER TABLE {TARGET_TABLE} ATTACH PARTITION ID '{partition_number}' FROM  {import_table_name};"""
        )

        # print the count of entries in the main sessions table
        count_query = f"SELECT count(), uniq(session_id) FROM {TARGET_TABLE}"
        [(sessions_row_count, sessions_event_count)] = sync_execute(count_query, {"team_id": self.team_id})
        logger.info(f"{sessions_row_count} rows and {sessions_event_count} in sessions table")


class Command(BaseCommand):
    help = "Backfill person_distinct_id_overrides records."

    def add_arguments(self, parser):
        parser.add_argument("--team-id", required=True, type=int, help="team to backfill for")
        parser.add_argument(
            "--live-run", action="store_true", help="actually execute INSERT queries (default is dry-run)"
        )

    def handle(self, *, live_run: bool, team_id: int, **options):
        logger.setLevel(logging.INFO)

        if not Team.objects.filter(id=team_id).exists():
            raise CommandError(f"Team with id={team_id!r} does not exist")

        BackfillQuery(team_id).execute(dry_run=not live_run)
