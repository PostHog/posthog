import logging
from typing import Optional

import structlog
from django.core.management.base import BaseCommand
from django.db import transaction

from posthog.client import sync_execute
from posthog.kafka_client.client import KafkaProducer
from posthog.models.person import PersonDistinctId
from posthog.models.person.util import create_person_distinct_id

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
        parser.add_argument("--live-run", action="store_true", help="Run changes, default is dry-run")

    def handle(self, *args, **options):
        run(options)


def run(options, sync: bool = False):
    live_run = options["live_run"]

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
        distinct_ids = get_distinct_ids_tied_to_deleted_persons(team_id)
        distinct_ids_and_versions = [(distinct_id, version) for distinct_id in distinct_ids]
    else:
        existing_version = get_version_for_distinct_id(team_id, distinct_id)
        distinct_ids_and_versions = [(distinct_id, existing_version + 100)]

    for distinct_id, new_version in distinct_ids_and_versions:
        # this can throw but this script can safely be re-run as
        # updated distinct_ids won't show up in the search anymore
        # since they no longer belong to deleted persons
        # it's safer to throw and exit if anything went wrong
        update_distinct_id(distinct_id, new_version, team_id, live_run, sync)

    if live_run:
        logger.info("Waiting on Kafka producer flush, for up to 5 minutes")
        KafkaProducer().flush(5 * 60)
        logger.info("Kafka producer queue flushed.")


def get_distinct_ids_tied_to_deleted_persons(team_id: int) -> list[tuple[str, int]]:
    # find distinct_ids where the person is set to be deleted
    rows = sync_execute(
        """
            SELECT distinct_id FROM (
                SELECT distinct_id, argMax(person_id, version) AS person_id FROM person_distinct_id2 WHERE team_id = %(team)s GROUP BY distinct_id
            ) AS pdi2
            WHERE pdi2.person_id NOT IN (SELECT id FROM person WHERE team_id = %(team)s)
            OR
            pdi2.person_id IN (SELECT id FROM person WHERE team_id = %(team)s AND is_deleted = 1)
        """,
        {
            "team": team_id,
        },
    )
    return [row[0] for row in rows]


def get_version_for_distinct_id(team_id: int, distinct_id: str) -> int:
    rows = sync_execute(
        """
            SELECT max(version) as version FROM person_distinct_id2 WHERE team_id = %(team)s AND distinct_id = %(distinct_id)s
        """,
        {
            "team": team_id,
            "distinct_id": distinct_id,
        },
    )
    assert (
        len(rows) == 1
    ), f"Expected to find exactly one row in person_distinct_id2 for team_id:{team_id}, distinct_id:{distinct_id}, got {len(rows)}"
    return rows[0][0]


def update_distinct_id(distinct_id: str, version: int, team_id: int, live_run: bool, sync: bool):
    # update the version if the distinct_id exists in postgres, otherwise do nothing
    # also to avoid collisions we're doing this one-by-one locking postgres for a transaction
    if live_run:
        with transaction.atomic():
            person_distinct_id = update_distinct_id_in_postgres(distinct_id, version, team_id, live_run)
    else:
        person_distinct_id = update_distinct_id_in_postgres(distinct_id, version, team_id, live_run)
    # Update ClickHouse via Kafka message
    if person_distinct_id and live_run:
        create_person_distinct_id(
            team_id=team_id,
            distinct_id=distinct_id,
            person_id=str(person_distinct_id.person.uuid),
            version=version,
            is_deleted=False,
            sync=sync,
        )


def update_distinct_id_in_postgres(
    distinct_id: str, version: int, team_id: int, live_run: bool
) -> Optional[PersonDistinctId]:
    person_distinct_id = PersonDistinctId.objects.filter(team_id=team_id, distinct_id=distinct_id).first()
    if person_distinct_id is None:
        logger.info(f"Distinct id {distinct_id} hasn't been re-used yet and can cause problems in the future")
        return None
    logger.info(f"Updating {distinct_id} to version {version} for person uuid = {person_distinct_id.person.uuid}")
    if live_run:
        person_distinct_id.version = version
        person_distinct_id.save()
    return person_distinct_id
