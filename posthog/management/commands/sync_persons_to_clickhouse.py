import json
import logging
from uuid import UUID

import structlog
from django.core.management.base import BaseCommand
from django.utils.timezone import now

from posthog.client import sync_execute
from posthog.models.group.group import Group
from posthog.models.group.util import raw_create_group_ch
from posthog.models.person import PersonDistinctId
from posthog.models.person.person import Person, PersonOverride
from posthog.models.person.util import (
    _delete_ch_distinct_id,
    create_person,
    create_person_distinct_id,
    create_person_override,
)

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
        parser.add_argument("--person-override", action="store_true", help="Sync person overrides")
        parser.add_argument("--group", action="store_true", help="Sync groups")
        parser.add_argument(
            "--deletes", action="store_true", help="process deletes for data in ClickHouse but not Postgres"
        )
        parser.add_argument("--live-run", action="store_true", help="Run changes, default is dry-run")
        parser.add_argument("--batch-size-pg", default=1000, type=int, help="Batch size to process by for Postgres")
        parser.add_argument("--batch-size-ch", default=10000, type=int, help="Batch size to process by for ClickHouse")
        parser.add_argument("--log-every-nth", default=1000, type=int, help="Print log line every nth element")

    def handle(self, *args, **options):
        run(options)


def run(options, sync: bool = False):  # sync used for unittests
    live_run = options["live_run"]
    deletes = options["deletes"]

    if not options["team_id"]:
        logger.error("You must specify --team-id to run this script")
        exit(1)

    team_id = options["team_id"]
    batch_size_pg = options["batch_size_pg"]
    batch_size_ch = options["batch_size_ch"]
    log_every_nth = options["log_every_nth"]

    if options["person"]:
        run_person_sync(team_id, live_run, deletes, sync, batch_size_pg, batch_size_ch, log_every_nth)

    if options["person_distinct_id"]:
        run_distinct_id_sync(team_id, live_run, deletes, sync, batch_size_pg, batch_size_ch, log_every_nth)

    if options["person_override"]:
        run_person_override_sync(team_id, live_run, deletes, sync, batch_size_pg, batch_size_ch, log_every_nth)

    if options["group"]:
        run_group_sync(team_id, live_run, sync)


def process_in_batches(get_pg, get_ch, get_key, sync_fn, log_every_nth: int) -> None:
    last_clickhouse_id = "00000000-0000-0000-0000-000000000000"  # start from the lowest possible UUID

    # Get objects from Django/PostgreSQL
    pg_objects = get_pg()

    for i, pg_obj in enumerate(pg_objects):
        key = get_key(pg_obj)
        if i % log_every_nth == 0:
            logger.info(f"Processed {i} objects")

        # If the current PostgreSQL ID is greater than the last ID we got from ClickHouse, fetch a new chunk from ClickHouse
        # If we didn't get any more new data, we'll mark the last id as the max possible to avoid useless fetches
        if key > last_clickhouse_id:
            ch_obj_to_version = get_ch(key)
            logger.info(f"Fetched from CH after {key}, got {len(ch_obj_to_version)} objects")

            if ch_obj_to_version:
                last_clickhouse_id = ch_obj_to_version[-1][0]
            else:
                last_clickhouse_id = "ffffffff-ffff-ffff-ffff-ffffffffffff"

        # If the current PostgreSQL ID is not in ClickHouse IDs or the version is smaller then sync it
        ch_version = ch_obj_to_version.get(key, None)
        pg_version = pg_obj.version or 0
        if ch_version is None or ch_version < pg_version:
            logger.info(f"*** Updating {key} to version {pg_version} ***")
            sync_fn(pg_obj)
        elif ch_version > pg_version:
            logger.info(
                f"Clickhouse version ({ch_version}) for '{key}' is higher than in Postgres ({pg_version}). Ignoring."
            )


def run_person_sync(
    team_id: int,
    live_run: bool,
    deletes: bool,
    sync: bool,
    batch_size_pg: int = 100,
    batch_size_ch: int = 100,
    log_every_nth: int = 100,
):
    logger.info("Running person table sync")

    def get_pg():
        return Person.objects.filter(team_id=team_id).order_by("id").iterator(chunk_size=batch_size_pg)

    def get_ch(last_id):
        rows = sync_execute(
            """
            SELECT id, max(version) FROM person WHERE team_id = %(team_id)s AND id > %(last_id)s GROUP BY id HAVING max(is_deleted) = 0 ORDER BY id LIMIT %(batch_size)s
        """,
            {"team_id": team_id, "last_id": last_id, "batch_size": batch_size_ch},
        )
        ch_persons_to_version = {row[0]: row[1] for row in rows}
        return ch_persons_to_version

    def get_key(person: Person):
        return str(person.uuid)

    def sync_fn(person: Person):
        if live_run:
            # Update ClickHouse via Kafka message
            create_person(
                team_id=team_id,
                version=person.version,
                uuid=str(person.uuid),
                properties=person.properties,
                is_identified=person.is_identified,
                created_at=person.created_at,
                sync=sync,
            )

    process_in_batches(get_pg, get_ch, get_key, sync_fn, log_every_nth)

    if deletes:
        # TODO: this will not work for large teams
        logger.info("Processing person deletions")
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


def run_distinct_id_sync(
    team_id: int,
    live_run: bool,
    deletes: bool,
    sync: bool,
    batch_size_pg: int = 100,
    batch_size_ch: int = 100,
    log_every_nth: int = 100,
):
    logger.info("Running person distinct id table sync")

    def get_pg():
        return PersonDistinctId.objects.filter(team_id=team_id).order_by("id").iterator(chunk_size=batch_size_pg)

    def get_ch(last_id):
        rows = sync_execute(
            """
            SELECT distinct_id, max(version) FROM person_distinct_id2 WHERE team_id = %(team_id)s AND distinct_id > %(last_id)s GROUP BY distinct_id HAVING max(is_deleted) = 0 ORDER BY distinct_id LIMIT %(batch_size)s
        """,
            {"team_id": team_id, "last_id": last_id, "batch_size": batch_size_ch},
        )
        ch_persons_to_version = {row[0]: row[1] for row in rows}
        return ch_persons_to_version

    def get_key(person_distinct_id: PersonDistinctId):
        return str(person_distinct_id.distinct_id)

    def sync_fn(person_distinct_id: PersonDistinctId):
        if live_run:
            # Update ClickHouse via Kafka message
            create_person_distinct_id(
                team_id=team_id,
                distinct_id=person_distinct_id.distinct_id,
                person_id=str(person_distinct_id.person.uuid),
                version=person_distinct_id.version,
                is_deleted=False,
                sync=sync,
            )

    process_in_batches(get_pg, get_ch, get_key, sync_fn, log_every_nth)

    if deletes:
        # TODO: this will not work for large teams
        logger.info("Processing distinct id deletions")
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
        postgres_distinct_ids = {person_distinct_id.distinct_id for person_distinct_id in person_distinct_ids}
        for distinct_id, version in ch_distinct_id_to_version.items():
            if distinct_id not in postgres_distinct_ids:
                logger.info(f"Deleting distinct ID {distinct_id}")
                if live_run:
                    _delete_ch_distinct_id(team_id, UUID(int=0), distinct_id, version, sync=sync)


def run_person_override_sync(
    team_id: int,
    live_run: bool,
    deletes: bool,
    sync: bool,
    batch_size_pg: int = 100,
    batch_size_ch: int = 100,
    log_every_nth: int = 100,
):
    logger.info("Running person override sync")

    def get_pg():
        return (
            PersonOverride.objects.filter(team_id=team_id)
            .select_related("old_person_id", "override_person_id")
            .order_by("id")
            .iterator(chunk_size=batch_size_pg)
        )

    def get_ch(last_id):
        rows = sync_execute(
            """
            SELECT old_person_id, max(version) FROM person_overrides WHERE team_id = %(team_id)s AND old_person_id > %(last_id)s GROUP BY old_person_id HAVING max(is_deleted) = 0 ORDER BY old_person_id LIMIT %(batch_size)s
        """,
            {"team_id": team_id, "last_id": last_id, "batch_size": batch_size_ch},
        )
        ch_persons_to_version = {row[0]: row[1] for row in rows}
        return ch_persons_to_version

    def get_key(pg_override: PersonOverride):
        return str(pg_override.old_person_id.uuid)

    def sync_fn(pg_override: PersonOverride):
        if live_run:
            # Update ClickHouse via Kafka message
            create_person_override(
                team_id,
                str(pg_override.old_person_id.uuid),
                str(pg_override.override_person_id.uuid),
                pg_override.version,
                now(),
                pg_override.oldest_event,
                sync=sync,
            )

    process_in_batches(get_pg, get_ch, get_key, sync_fn, log_every_nth)

    if deletes:
        logger.info("Override deletes aren't supported at this point")


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
                    group_type_index=pg_group["group_type_index"],  # type: ignore
                    group_key=pg_group["group_key"],
                    properties=pg_group["group_properties"],  # type: ignore
                    created_at=pg_group["created_at"],
                    sync=sync,
                )


def should_update_group(ch_group, pg_group) -> bool:
    return json.dumps(pg_group["group_properties"]) != ch_group["properties"] or pg_group["created_at"].strftime(
        "%Y-%m-%d %H:%M:%S"
    ) != ch_group["created_at"].strftime("%Y-%m-%d %H:%M:%S")
