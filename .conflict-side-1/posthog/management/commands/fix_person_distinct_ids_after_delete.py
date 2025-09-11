import logging

from django.core.management.base import BaseCommand

import structlog

from posthog.kafka_client.client import KafkaProducer
from posthog.models.person.deletion import reset_all_deleted_person_distinct_ids, reset_deleted_person_distinct_ids

logger = structlog.get_logger(__name__)
logger.setLevel(logging.INFO)


class Command(BaseCommand):
    help = "Fix state for person distinct IDs in ClickHouse after person deletion and id re-use for a single team"

    def add_arguments(self, parser):
        parser.add_argument("--team-id", default=None, type=int, help="Specify a team to fix data for.")
        parser.add_argument(
            "--new-version", default=2500, type=int, help="New version value to use when in --all-distinct-ids mode."
        )
        parser.add_argument("--distinct-id", default=None, type=str, help="Specify a distinct ID to fix.")
        parser.add_argument(
            "--all-distinct-ids", action="store_true", help="Whether to fix *all* distinct IDs for the team."
        )

    def handle(self, *args, **options):
        run(options)


def run(options, sync: bool = False):
    if not options["team_id"]:
        logger.error("You must specify --team-id to run this script")
        exit(1)

    team_id = options["team_id"]

    distinct_id = options.get("distinct_id")
    all_distinct_ids = options.get("all_distinct_ids", False)
    if (not distinct_id and not all_distinct_ids) or (distinct_id and all_distinct_ids):
        logger.error("You must specify one of --distinct-id or --all-distinct-ids to run this script")
        exit(1)

    if all_distinct_ids:
        version = options["new_version"]
        reset_all_deleted_person_distinct_ids(team_id, version)
    else:
        reset_deleted_person_distinct_ids(team_id, distinct_id)

    logger.info("Waiting on Kafka producer flush, for up to 5 minutes")
    KafkaProducer().flush(5 * 60)
    logger.info("Kafka producer queue flushed.")
