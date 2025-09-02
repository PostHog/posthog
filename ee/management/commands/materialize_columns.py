import logging
import argparse

from django.core.management.base import BaseCommand

from posthog.settings import (
    MATERIALIZE_COLUMNS_ANALYSIS_PERIOD_HOURS,
    MATERIALIZE_COLUMNS_BACKFILL_PERIOD_DAYS,
    MATERIALIZE_COLUMNS_MAX_AT_ONCE,
    MATERIALIZE_COLUMNS_MINIMUM_QUERY_TIME,
)

from ee.clickhouse.materialized_columns.analyze import logger, materialize_properties_task
from ee.clickhouse.materialized_columns.columns import DEFAULT_TABLE_COLUMN


class Command(BaseCommand):
    help = "Materialize properties into columns in clickhouse"

    def add_arguments(self, parser):
        parser.add_argument("--dry-run", action="store_true", help="Print plan instead of executing it")

        parser.add_argument(
            "--property",
            help="Properties to materialize. Skips analysis. Allows multiple arguments --property abc '$.abc.def'",
            nargs="+",
        )
        parser.add_argument(
            "--property-table",
            type=str,
            default="events",
            choices=["events", "person"],
            help="Table of --property",
        )
        parser.add_argument(
            "--table-column",
            type=str,
            help="The column to which --property should be materialised from.",
            default=DEFAULT_TABLE_COLUMN,
            choices=[
                "properties",
                "group_properties",
                "person_properties",
            ],
        )
        parser.add_argument(
            "--backfill-period",
            type=int,
            default=MATERIALIZE_COLUMNS_BACKFILL_PERIOD_DAYS,
            help="How many days worth of data to backfill. 0 to disable. Same as MATERIALIZE_COLUMNS_BACKFILL_PERIOD_DAYS env variable.",
        )

        parser.add_argument(
            "--min-query-time",
            type=int,
            default=MATERIALIZE_COLUMNS_MINIMUM_QUERY_TIME,
            help="Minimum query time (ms) before a query if considered for optimization. Same as MATERIALIZE_COLUMNS_MINIMUM_QUERY_TIME env variable.",
        )
        parser.add_argument(
            "--analyze-period",
            type=int,
            default=MATERIALIZE_COLUMNS_ANALYSIS_PERIOD_HOURS,
            help="How long of a time period to analyze. Same as MATERIALIZE_COLUMNS_ANALYSIS_PERIOD_HOURS env variable.",
        )
        parser.add_argument(
            "--analyze-team-id",
            type=int,
            default=None,
            help="Analyze queries only for a specific team_id",
        )
        parser.add_argument(
            "--max-columns",
            type=int,
            default=MATERIALIZE_COLUMNS_MAX_AT_ONCE,
            help="Max number of columns to materialize via single invocation. Same as MATERIALIZE_COLUMNS_MAX_AT_ONCE env variable.",
        )
        parser.add_argument(
            "--nullable",
            action=argparse.BooleanOptionalAction,
            default=True,
            dest="is_nullable",
        )

    def handle(self, *, is_nullable: bool, **options):
        logger.setLevel(logging.INFO)

        if options["dry_run"]:
            logger.warn("Dry run: No changes to the tables will be made!")

        if options.get("property"):
            logger.info(f"Materializing column. table={options['property_table']}, property_name={options['property']}")

            materialize_properties_task(
                properties_to_materialize=[
                    (
                        options["property_table"],
                        options["table_column"],
                        prop,
                    )
                    for prop in options.get("property")
                ],
                backfill_period_days=options["backfill_period"],
                dry_run=options["dry_run"],
                is_nullable=is_nullable,
            )
        else:
            materialize_properties_task(
                time_to_analyze_hours=options["analyze_period"],
                maximum=options["max_columns"],
                min_query_time=options["min_query_time"],
                backfill_period_days=options["backfill_period"],
                dry_run=options["dry_run"],
                team_id_to_analyze=options["analyze_team_id"],
                is_nullable=is_nullable,
            )
