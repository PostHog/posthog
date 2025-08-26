import logging
from datetime import timedelta

from django.core.management.base import BaseCommand
from django.db.models import F
from django.utils.timezone import now

import structlog
from dateutil.parser import isoparse

from posthog.kafka_client.client import KafkaProducer
from posthog.models.person.person import Person
from posthog.models.person.util import create_person

logger = structlog.get_logger(__name__)
logger.setLevel(logging.INFO)


class Command(BaseCommand):
    help = "Fix update persons created_at to not be in the future for a single team"

    def add_arguments(self, parser):
        parser.add_argument("--team-id", default=None, type=int, help="Specify a team to fix data for.")
        parser.add_argument("--new-date", default="2024-01-01", type=str, help="New create_at value to use")
        parser.add_argument("--live-run", action="store_true", help="Run changes, default is dry-run")

    def handle(self, *args, **options):
        run(options)


def run(options):
    live_run = options["live_run"]

    if not options["team_id"]:
        logger.error("You must specify --team-id to run this script")
        exit(1)

    team_id = options["team_id"]
    new_date = isoparse(options["new_date"])

    future_date = now() + timedelta(days=2)

    # Get all persons with future created_at value
    persons = Person.objects.filter(team_id=team_id, created_at__gt=future_date)

    logger.info(
        f'Found {len(persons)} persons with future created_at value, updating them to {new_date.strftime("%Y-%m-%d %H:%M:%S.%f")}'
    )

    # If someone else updated the person at the same time these could conflict, which isn't ideal, but this is a one-off script
    for person in persons:
        logger.info(f'Updating person {person.uuid} created_at to {new_date.strftime("%Y-%m-%d %H:%M:%S.%f")}')
        if live_run:
            Person.objects.filter(pk=person.id).update(version=F("version") + 1, created_at=new_date)
            create_person(
                uuid=str(person.uuid),
                team_id=team_id,
                properties=person.properties,
                is_identified=person.is_identified,
                is_deleted=False,
                created_at=person.created_at,
                version=person.version,
                sync=True,
            )

    logger.info("Waiting on Kafka producer flush, for up to 5 minutes")
    KafkaProducer().flush(5 * 60)
    logger.info("Kafka producer queue flushed.")
