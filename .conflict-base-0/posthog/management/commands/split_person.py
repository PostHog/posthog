import logging

from django.core.management.base import BaseCommand

import structlog

from posthog.kafka_client.client import KafkaProducer
from posthog.models import Person

logger = structlog.get_logger(__name__)
logger.setLevel(logging.INFO)


class Command(BaseCommand):
    help = (
        "Split a person into one new person per distinct_id, to recover from bad merges. "
        "Useful when the API endpoint timeouts."
    )

    def add_arguments(self, parser):
        parser.add_argument("--team-id", default=None, type=int, help="Specify a team to fix data for.")
        parser.add_argument(
            "--person-id",
            default=None,
            type=int,
            help="Specify the person ID to split.",
        )
        parser.add_argument("--live-run", action="store_true", help="Run changes, default is dry-run")
        parser.add_argument(
            "--max-splits",
            default=None,
            type=int,
            help="Only split off a given number of distinct_ids and exit.",
        )

    def handle(self, *args, **options):
        run(options)


def run(options):
    live_run = options["live_run"]

    if options["team_id"] is None:
        logger.error("You must specify --team-id to run this script")
        exit(1)

    if options["person_id"] is None:
        logger.error("You must specify --person-id to run this script")
        exit(1)

    team_id = options["team_id"]
    person_id = options["person_id"]
    max_splits = options["max_splits"]

    person = Person.objects.get(pk=person_id)
    if person.team_id != team_id:
        logger.error(f"Specified person belongs to different team {person.team_id}")
        exit(1)

    distinct_id_count = len(person.distinct_ids)
    if distinct_id_count < 2:
        logger.error(f"Specified person only has {distinct_id_count} IDs, cannot split")
        exit(1)

    if max_splits:
        will_split = min(max_splits, distinct_id_count)
        logger.info(f"Splitting {will_split} of the {distinct_id_count} distinct_ids")
    else:
        logger.info(f"Splitting all of the {distinct_id_count} distinct_ids")

    if live_run:
        person.split_person(None, max_splits)
        logger.info("Waiting on Kafka producer flush, for up to 5 minutes")
        KafkaProducer().flush(5 * 60)
        logger.info("Kafka producer queue flushed.")
    else:
        logger.info("Skipping the split, pass --live-run to run it")
