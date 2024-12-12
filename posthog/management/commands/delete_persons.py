import logging
from time import sleep
from typing import Optional

import structlog
from django.core.management.base import BaseCommand
from django.db import transaction

from posthog.client import sync_execute
from posthog.kafka_client.client import KafkaProducer
from posthog.models.person import PersonDistinctId
from posthog.models.person.person import Person
from posthog.models.person.util import create_person_distinct_id

logger = structlog.get_logger(__name__)
logger.setLevel(logging.INFO)


class Command(BaseCommand):
    help = "Fix state for person distinct IDs in ClickHouse after person deletion and id re-use for a single team"

    def add_arguments(self, parser):
        parser.add_argument("--team-id", default=None, type=int, help="Specify a team to fix data for.")
        parser.add_argument(
            "--person-ids", default=None, type=str, help="Specify a list of comma separated person ids to be deleted."
        )
        parser.add_argument("--limit", default=100, type=int, help="Number of rows to be deleted")
        parser.add_argument(
            "--include-distinct-ids", action="store_true", help="Whether to fix *all* distinct IDs for the team."
        )
        parser.add_argument("--live-run", action="store_true", help="Run changes, default is dry-run")

    def handle(self, *args, **options):
        run(options)


def run(options, sync: bool = False):
    live_run = options["live_run"]
    team_id = options["team_id"]
    person_ids = options["person_ids"].split(",") if options["person_ids"] else None
    limit = options["limit"]
    include_distinct_ids = options["include_distinct_ids"]

    if not team_id:
        logger.error("You must specify --team-id to run this script")
        return exit(1)

    # Print the plan
    logger.info("Plan:")
    if team_id:
        logger.info(f"Team ID: {team_id}")
    if person_ids:
        logger.info(f"Person IDs: {person_ids}")
    if include_distinct_ids:
        logger.info(f"Include distinctIDs table")
    logger.info(f"Number of rows to delete: {limit}")

    if not live_run:
        logger.info("Dry run, not deleting anything.")
        return exit(0)

    person_queryset = Person.objects.filter(team_id=team_id)

    if person_ids:
        person_queryset = person_queryset.filter(id__in=person_ids)

    person_queryset = person_queryset[:limit]

    count = person_queryset.count()

    logger.info(f"Will delete {count} rows. You have 10 seconds to cancel...")

    sleep(5)
    logger.info(f"5 seconds left...")
    sleep(5)

    logger.info(f"Deleting {count} rows...")
    person_queryset.delete()

    logger.info(f"Deleting {count} rows...")
