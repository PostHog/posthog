import json
import logging
from uuid import UUID

from django.core.management.base import BaseCommand

import structlog

from posthog.clickhouse.client import sync_execute
from posthog.kafka_client.client import KafkaProducer
from posthog.models.group.group import Group
from posthog.models.group.util import raw_create_group_ch
from posthog.models.person import PersonDistinctId
from posthog.models.person.person import Person
from posthog.models.person.util import _delete_ch_distinct_id, create_person, create_person_distinct_id

logger = structlog.get_logger(__name__)
logger.setLevel(logging.INFO)


class Command(BaseCommand):
    help = """Sync person or distinct id tables from postgres to ClickHouse.
        Lookup from Postgres and with a lower version in ClickHouse will be updated.
        Note higher versions in ClickHouse will be ignored.
        Recommended: run first without `--live-run` and first for person table, then distinct_id table
        """

    def add_arguments(self, parser):
        parser.add_argument("--team-id", default=None, type=int, help="Specify a team to fix data for.")
        parser.add_argument("--person", action="store_true", help="Sync persons")
        parser.add_argument("--person-distinct-id", action="store_true", help="Sync person distinct IDs")
        parser.add_argument("--group", action="store_true", help="Sync groups")
        parser.add_argument(
            "--deletes",
            action="store_true",
            help="process deletes for data in ClickHouse but not Postgres",
        )
        parser.add_argument("--live-run", action="store_true", help="Run changes, default is dry-run")

    def handle(self, *args, **options):
        run(options)


def run(options, sync: bool = False):  # sync used for unittests
    live_run = options["live_run"]
    deletes = options["deletes"]

    if not options["team_id"]:
        logger.error("You must specify --team-id to run this script")
        exit(1)

    team_id = options["team_id"]

    if options["person"]:
        run_person_sync(team_id, live_run, deletes, sync)

    if options["person_distinct_id"]:
        run_distinct_id_sync(team_id, live_run, deletes, sync)

    if options["group"]:
        run_group_sync(team_id, live_run, sync)

    logger.info("Waiting on Kafka producer flush, for up to 5 minutes")
    KafkaProducer().flush(5 * 60)
    logger.info("Kafka producer queue flushed.")


def run_person_sync(team_id: int, live_run: bool, deletes: bool, sync: bool):
    logger.info("Running person table sync")
    # lookup what needs to be updated in ClickHouse and send kafka messages for only those
    persons = Person.objects.filter(team_id=team_id)
    rows = sync_execute(
        """
            SELECT id, max(version) FROM person WHERE team_id = %(team_id)s GROUP BY id HAVING max(is_deleted) = 0
        """,
        {
            "team_id": team_id,
        },
    )
    ch_persons_to_version = {row[0]: row[1] for row in rows}
    total_pg = len(persons)
    logger.info(f"Got ${total_pg} in PG and ${len(ch_persons_to_version)} in CH")

    for i, person in enumerate(persons):
        if i % (max(total_pg // 10, 1)) == 0 and i > 0:
            logger.info(f"Processed {i / total_pg * 100}%")
        ch_version = ch_persons_to_version.get(person.uuid, None)
        pg_version = person.version or 0
        if ch_version is None or ch_version < pg_version:
            logger.info(f"Updating {person.uuid} to version {pg_version}")
            if live_run:
                # Update ClickHouse via Kafka message
                create_person(
                    team_id=team_id,
                    version=pg_version,
                    uuid=str(person.uuid),
                    properties=person.properties,
                    is_identified=person.is_identified,
                    created_at=person.created_at,
                    sync=sync,
                )
        elif ch_version > pg_version:
            logger.info(
                f"Clickhouse version ({ch_version}) for '{person.uuid}' is higher than in Postgres ({pg_version}). Ignoring."
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
                        sync=sync,
                    )


def run_distinct_id_sync(team_id: int, live_run: bool, deletes: bool, sync: bool):
    logger.info("Running person distinct id table sync")
    # lookup what needs to be updated in ClickHouse and send kafka messages for only those
    person_distinct_ids = PersonDistinctId.objects.filter(team_id=team_id)
    rows = sync_execute(
        """
            SELECT distinct_id, max(version) FROM person_distinct_id2 WHERE team_id = %(team_id)s GROUP BY distinct_id HAVING max(is_deleted) = 0
        """,
        {
            "team_id": team_id,
        },
    )
    ch_distinct_id_to_version = {row[0]: row[1] for row in rows}

    total_pg = len(person_distinct_ids)
    logger.info(f"Got ${total_pg} in PG and ${len(ch_distinct_id_to_version)} in CH")

    for i, person_distinct_id in enumerate(person_distinct_ids):
        if i % (max(total_pg // 10, 1)) == 0 and i > 0:
            logger.info(f"Processed {i / total_pg * 100}%")
        ch_version = ch_distinct_id_to_version.get(person_distinct_id.distinct_id, None)
        pg_version = person_distinct_id.version or 0
        if ch_version is None or ch_version < pg_version:
            logger.info(f"Updating {person_distinct_id.distinct_id} to version {pg_version}")
            if live_run:
                # Update ClickHouse via Kafka message
                create_person_distinct_id(
                    team_id=team_id,
                    distinct_id=person_distinct_id.distinct_id,
                    person_id=str(person_distinct_id.person.uuid),
                    version=pg_version,
                    is_deleted=False,
                    sync=sync,
                )
        elif ch_version > pg_version:
            # This could be happening due to person deletions - check out fix_person_distinct_ids_after_delete management cmd.
            # Ignoring here to be safe.
            logger.info(
                f"Clickhouse version ({ch_version}) for '{person_distinct_id.distinct_id}' is higher than in Postgres ({pg_version}). Ignoring."
            )
            continue

    if deletes:
        logger.info("Processing distinct id deletions")
        postgres_distinct_ids = {person_distinct_id.distinct_id for person_distinct_id in person_distinct_ids}
        for distinct_id, version in ch_distinct_id_to_version.items():
            if distinct_id not in postgres_distinct_ids:
                logger.info(f"Deleting distinct ID {distinct_id}")
                if live_run:
                    _delete_ch_distinct_id(team_id, UUID(int=0), distinct_id, version, sync=sync)


def run_group_sync(team_id: int, live_run: bool, sync: bool):
    logger.info("Running group table sync")
    # lookup what needs to be updated in ClickHouse and send kafka messages for only those
    pg_groups = Group.objects.filter(team_id=team_id).values(
        "group_type_index", "group_key", "group_properties", "created_at"
    )
    # unfortunately we don't have version column for groups table
    rows = sync_execute(
        """
            SELECT group_type_index, group_key, group_properties, created_at FROM groups WHERE team_id = %(team_id)s ORDER BY _timestamp DESC LIMIT 1 BY group_type_index, group_key
        """,
        {
            "team_id": team_id,
        },
    )
    ch_groups = {(row[0], row[1]): {"properties": row[2], "created_at": row[3]} for row in rows}
    total_pg = len(pg_groups)
    logger.info(f"Got ${total_pg} in PG and ${len(ch_groups)} in CH")

    for i, pg_group in enumerate(pg_groups):
        if i % (max(total_pg // 10, 1)) == 0 and i > 0:
            logger.info(f"Processed {i / total_pg * 100}%")
        ch_group = ch_groups.get((pg_group["group_type_index"], pg_group["group_key"]), None)
        if ch_group is None or should_update_group(ch_group, pg_group):
            logger.info(
                f"Updating {pg_group['group_type_index']} - {pg_group['group_key']} with properties {pg_group['group_properties']} and created_at {pg_group['created_at']}"
            )
            if live_run:
                # Update ClickHouse via Kafka message
                raw_create_group_ch(
                    team_id=team_id,
                    group_type_index=pg_group["group_type_index"],
                    group_key=pg_group["group_key"],
                    properties=pg_group["group_properties"],
                    created_at=pg_group["created_at"],
                    sync=sync,
                )


def should_update_group(ch_group, pg_group) -> bool:
    return json.dumps(pg_group["group_properties"]) != ch_group["properties"] or pg_group["created_at"].strftime(
        "%Y-%m-%d %H:%M:%S"
    ) != ch_group["created_at"].strftime("%Y-%m-%d %H:%M:%S")
