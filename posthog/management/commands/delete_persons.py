import logging
from time import sleep

import structlog
from django.core.management.base import BaseCommand

from posthog.models.person.person import Person

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
        logger.info(f"-> Team ID: {team_id}")
    if person_ids:
        logger.info(f"-> Person IDs: {person_ids}")
    if include_distinct_ids:
        logger.info(f"-> Include distinctIDs table")
    logger.info(f"-> Limit: {limit}")

    list_query = Person.objects.filter(team_id=team_id)

    if person_ids:
        list_query = list_query.filter(id__in=person_ids)

    list_query = list_query.order_by("id")[:limit]

    num_to_delete = list_query.count()

    if not live_run:
        logger.info(f"Dry run. Would have deleted {num_to_delete} people.")
        logger.info("Set --live-run to actually delete.")
        return exit(0)

    if num_to_delete == 0:
        logger.info("No people to delete")
        return exit(0)

    logger.info(f"Will run the deletion for {num_to_delete} people.")
    confirm = input("Type 'delete' to confirm: ")

    if confirm != "delete":
        logger.info("Aborting")
        return exit(0)

    logger.info(f"Executing delete query...")

    Person.objects.filter(team_id=team_id, id__in=list_query.values_list("id", flat=True)).delete()

    logger.info("Done")
