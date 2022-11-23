from uuid import UUID

import structlog
from django.core.management.base import BaseCommand

from posthog.client import sync_execute
from posthog.models.person import PersonDistinctId
from posthog.models.person.person import Person
from posthog.models.person.util import _delete_ch_distinct_id, create_person, create_person_distinct_id

logger = structlog.get_logger(__name__)

PERSON_TABLE = "person"
DISTINCT_ID_TABLE = "persondistinctid"


class Command(BaseCommand):
    help = """Sync person or distinct id tables from postgres to ClickHouse.
        Lookup from Postgres and with a lower version in ClickHouse will be updated.
        Note higher versions in ClickHouse will be ignored.
        Recommended: run first without `--live-run` and first for person table, then distinct_id table
        """

    def add_arguments(self, parser):
        parser.add_argument("--team-id", default=None, type=int, help="Specify a team to fix data for.")
        parser.add_argument(
            "--tables", default=[PERSON_TABLE, DISTINCT_ID_TABLE], action="append", help="Which tables to sync"
        )
        parser.add_argument(
            "--deletes", action="store_true", help="process deletes for data in ClickHouse but not Postgres"
        )
        parser.add_argument("--live-run", action="store_true", help="Run changes, default is dry-run")

    def handle(self, *args, **options):
        run(options)


def run(options):
    live_run = options["live_run"]
    deletes = options["deletes"]

    if not options["team_id"]:
        logger.error("You must specify --team-id to run this script")
        exit(1)

    if not set(options["tables"]) <= {PERSON_TABLE, DISTINCT_ID_TABLE}:
        logger.error("Illegal value in --tables")
        exit(1)

    team_id = options["team_id"]

    if PERSON_TABLE in options["tables"]:
        run_person_sync(team_id, live_run, deletes)

    if DISTINCT_ID_TABLE in options["tables"]:
        run_distinct_id_sync(team_id, live_run, deletes)


def run_person_sync(team_id: int, live_run: bool, deletes: bool):
    logger.info("Running person table sync")
    # lookup what needs to be updated in ClickHouse and send kafka messages for only those
    persons = Person.objects.filter(team_id=team_id)
    rows = sync_execute(
        """
            SELECT id, max(version) FROM person WHERE team_id = %(team)s GROUP BY id HAVING max(is_deleted) = 0
        """,
        {
            "team": team_id,
        },
    )
    ch_persons_to_version = {row[0]: row[1] for row in rows}

    for person in persons:
        ch_version = ch_persons_to_version.get(person.uuid, None)
        if ch_version > person.version:
            logger.info(
                f"Clickhouse version ({ch_version}) for '{person.uuid}' is higher than in Postgres ({person.version}). Ignoring."
            )
            continue
        if ch_version != person.version:
            logger.info(f"Updating {person.uuid} to version {person.version}")
            if live_run:
                # Update ClickHouse via Kafka message
                create_person(
                    team_id=team_id,
                    version=person.version,
                    uuid=str(person.uuid),
                    properties=person.properties,  # TODO: check that the format is correct
                    is_identified=person.is_identified,
                    created_at=person.created_at,  # TODO: check formatting
                )

    if deletes:
        logger.info("Processing person deletions")
        postgres_uuids = {person.uuid for person in persons}
        for uuid, version in ch_persons_to_version.items():
            if uuid not in postgres_uuids:
                logger.info(f"Deleting person with uuid={uuid}")
                if live_run:
                    create_person(
                        uuid=str(uuid),
                        team_id=team_id,
                        properties={},
                        version=int(version or 0)
                        + 100,  # keep in sync with deletePerson in plugin-server/src/utils/db/db.ts
                        is_deleted=True,
                    )


def run_distinct_id_sync(team_id: int, live_run: bool, deletes: bool):
    logger.info("Running person distinct id table sync")
    # lookup what needs to be updated in ClickHouse and send kafka messages for only those
    person_distinct_ids = PersonDistinctId.objects.filter(team_id=team_id)
    rows = sync_execute(
        """
            SELECT distinct_id, max(version) FROM person_distinct_id2 WHERE team_id = %(team)s GROUP BY distinct_id HAVING max(is_deleted) = 0
        """,
        {
            "team": team_id,
        },
    )
    ch_distinct_id_to_version = {row[0]: row[1] for row in rows}

    for pdid in person_distinct_ids:
        ch_version = ch_distinct_id_to_version.get(pdid.distinct_id, None)
        # logger.info(f"{pdid.distinct_id} - {pdid.version} -  {ch_version}")
        if ch_version or 0 > pdid.version:
            # This could be happening due to person deletions - check out fix_person_distinct_ids_after_delete management cmd.
            # Ignoring here to be safe.
            logger.info(
                f"Clickhouse version ({ch_version}) for '{pdid.distinct_id}' is higher than in Postgres ({pdid.version}). Ignoring."
            )
            continue
        if ch_version != pdid.version:
            logger.info(f"Updating {pdid.distinct_id} to version {pdid.version}")
            if live_run:
                # Update ClickHouse via Kafka message
                create_person_distinct_id(
                    team_id=team_id,
                    distinct_id=pdid.distinct_id,
                    person_id=str(pdid.person.uuid),
                    version=pdid.version,
                    is_deleted=False,
                )

    if deletes:
        for distinct_id, version in ch_distinct_id_to_version.items():
            if distinct_id in person_distinct_ids:
                logger.info(f"Deleting distinct ID {distinct_id}")
                if live_run:
                    _delete_ch_distinct_id(team_id, UUID(int=0), distinct_id, version)
