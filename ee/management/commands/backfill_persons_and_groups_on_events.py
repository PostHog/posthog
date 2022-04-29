import re
from collections import defaultdict
from typing import Dict, Set

import structlog
from django.conf import settings
from django.core.management.base import BaseCommand

from ee.clickhouse.materialized_columns.replication import clickhouse_is_replicated
from ee.clickhouse.sql.schema import CREATE_TABLE_QUERIES, get_table_name
from posthog.client import sync_execute

logger = structlog.get_logger(__name__)



class Command(BaseCommand):
    help = "Backfill persons and groups data on events for a given team"

    def add_arguments(self, parser):
        parser.add_argument(
            "--team-id", default=None, type=int, help="Specify a team to backfill data for."
        )

    def handle(self, *args, **options):
        
        if not options["team_id"]:
            logger.error("You must specify --team-id to run this script")


        