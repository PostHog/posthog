"""Reconcile a team's person, distinct-id, and group rows from Postgres to ClickHouse.

LOCAL/DEV USE ONLY for now: this loads the whole team's rows into memory (no batching), so it
is not safe to run against large production teams. It exists to seed local ClickHouse from the
local persons database (e.g. via the generate_persons command).
"""

import json
import logging
from typing import Literal, cast
from uuid import UUID

from django.core.management.base import BaseCommand

import structlog

from posthog.clickhouse.client import sync_execute
from posthog.kafka_client.routing import flush_all_producers
from posthog.models.group.util import raw_create_group_ch
from posthog.models.person.deletion import orphan_share_refusal
from posthog.models.person.util import (
    PersonVersionFloor,
    VersionFloorOutcome,
    create_person,
    create_person_distinct_id,
    ensure_person_version_floors,
)
from posthog.persons_db import persons_db_connection

logger = structlog.get_logger(__name__)
logger.setLevel(logging.INFO)


class Command(BaseCommand):
    help = """Sync person or distinct id tables from postgres to ClickHouse.
        Lookup from Postgres and with a lower version in ClickHouse will be updated.
        Note higher versions in ClickHouse will be ignored.
        Recommended: run first without `--live-run` and first for person table, then distinct_id table

        Local/dev use only for now: this materializes the whole team in memory and is not safe
        for large production teams.
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
        parser.add_argument(
            "--force",
            action="store_true",
            help="Process deletes even when persons missing from Postgres are more than 5%% of ClickHouse's.",
        )

    def handle(self, *args, **options):
        run(options)


def run(options):
    live_run = options["live_run"]
    deletes = options["deletes"]

    if not options["team_id"]:
        logger.error("You must specify --team-id to run this script")
        exit(1)

    team_id = options["team_id"]

    if options["person"]:
        run_person_sync(team_id, live_run, deletes, force=options.get("force", False))

    if options["person_distinct_id"]:
        run_distinct_id_sync(team_id, live_run, deletes)

    if options["group"]:
        run_group_sync(team_id, live_run)

    logger.info("Waiting on Kafka producer flush, for up to 5 minutes")
    flush_all_producers(5 * 60)
    logger.info("Kafka producer queue flushed.")


def run_person_sync(team_id: int, live_run: bool, deletes: bool, force: bool = False):
    logger.info("Running person table sync")
    # lookup what needs to be updated in ClickHouse and send kafka messages for only those
    with persons_db_connection(writer=False) as conn, conn.cursor() as cursor:
        cursor.execute(
            "SELECT uuid, version, properties, is_identified, created_at FROM posthog_person"
            " WHERE team_id = %s AND is_deleted = false",
            [team_id],
        )
        persons = [
            {
                "uuid": uuid,
                "version": version,
                "properties": properties,
                "is_identified": is_identified,
                "created_at": created_at,
            }
            for uuid, version, properties, is_identified, created_at in cursor.fetchall()
        ]
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
        ch_version = ch_persons_to_version.get(person["uuid"], None)
        pg_version = person["version"] or 0
        if ch_version is None or ch_version < pg_version:
            logger.info(f"Updating {person['uuid']} to version {pg_version}")
            if live_run:
                # Update ClickHouse via Kafka message
                create_person(
                    team_id=team_id,
                    version=pg_version,
                    uuid=str(person["uuid"]),
                    properties=person["properties"],
                    is_identified=person["is_identified"],
                    created_at=person["created_at"],
                )
        elif ch_version > pg_version:
            logger.info(
                f"Clickhouse version ({ch_version}) for '{person['uuid']}' is higher than in Postgres ({pg_version}). Ignoring."
            )

    if deletes:
        logger.info("Processing person deletions")
        postgres_uuids = {person["uuid"] for person in persons}
        tombstone_versions = _postgres_person_tombstone_versions(team_id)
        stored: list[tuple[UUID, int]] = []
        floors: list[PersonVersionFloor] = []
        for uuid, version in ch_persons_to_version.items():
            if uuid in postgres_uuids:
                continue
            ch_version = int(version or 0)
            tombstone_version = tombstone_versions.get(uuid)
            if tombstone_version is not None and tombstone_version > ch_version:
                logger.info(f"Deleting person with uuid={uuid} at version {tombstone_version}")
                stored.append((uuid, tombstone_version))
                continue
            # No Postgres row outranks ClickHouse, so Postgres takes a tombstone above it first; publishing
            # above Postgres alone would hide the next revival.
            logger.info(f"Deleting person with uuid={uuid} at version {ch_version + 1} or above")
            floors.append(PersonVersionFloor(uuid=UUID(str(uuid)), min_version=ch_version + 1))
        missing = sum(1 for floor in floors if floor.uuid not in tombstone_versions)
        refusal = orphan_share_refusal(team_id, missing, len(ch_persons_to_version))
        if refusal:
            if live_run and not force:
                logger.error(refusal)
                exit(1)
            logger.warning(refusal)
        if live_run:
            for uuid, tombstone_version in stored:
                _publish_person_tombstone(team_id, uuid, tombstone_version)
        if live_run and floors:
            for result in ensure_person_version_floors(team_id, floors):
                if result.outcome == VersionFloorOutcome.LIVE:
                    logger.warning(f"Skipping person uuid={result.uuid}: the Postgres primary holds it live")
                    continue
                _publish_person_tombstone(team_id, result.uuid, result.version)


def _publish_person_tombstone(team_id: int, uuid: UUID, version: int) -> None:
    create_person(uuid=str(uuid), team_id=team_id, properties={}, version=version, is_deleted=True)


def _postgres_person_tombstone_versions(team_id: int) -> dict[UUID, int]:
    """The version each tombstoned person holds in Postgres, so its ClickHouse tombstone matches."""
    with persons_db_connection(writer=False) as conn, conn.cursor() as cursor:
        cursor.execute(
            "SELECT uuid, version FROM posthog_person WHERE team_id = %s AND is_deleted = true",
            [team_id],
        )
        return {uuid: int(version or 0) for uuid, version in cursor.fetchall()}


def _postgres_distinct_id_tombstones(team_id: int) -> dict[str, tuple[UUID, int]]:
    """The person and version each tombstoned mapping holds in Postgres."""
    with persons_db_connection(writer=False) as conn, conn.cursor() as cursor:
        cursor.execute(
            "SELECT pdi.distinct_id, p.uuid, pdi.version "
            "FROM posthog_persondistinctid pdi JOIN posthog_person p ON p.id = pdi.person_id "
            "WHERE pdi.team_id = %s AND pdi.is_deleted = true",
            [team_id],
        )
        return {distinct_id: (uuid, int(version or 0)) for distinct_id, uuid, version in cursor.fetchall()}


def run_distinct_id_sync(team_id: int, live_run: bool, deletes: bool):
    logger.info("Running person distinct id table sync")
    # lookup what needs to be updated in ClickHouse and send kafka messages for only those
    with persons_db_connection(writer=False) as conn, conn.cursor() as cursor:
        cursor.execute(
            "SELECT pdi.distinct_id, pdi.version, p.uuid "
            "FROM posthog_persondistinctid pdi JOIN posthog_person p ON p.id = pdi.person_id "
            "WHERE pdi.team_id = %s AND pdi.is_deleted = false AND p.is_deleted = false",
            [team_id],
        )
        person_distinct_ids = [
            {"distinct_id": distinct_id, "version": version, "person_uuid": person_uuid}
            for distinct_id, version, person_uuid in cursor.fetchall()
        ]
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
        ch_version = ch_distinct_id_to_version.get(person_distinct_id["distinct_id"], None)
        pg_version = person_distinct_id["version"] or 0
        if ch_version is None or ch_version < pg_version:
            logger.info(f"Updating {person_distinct_id['distinct_id']} to version {pg_version}")
            if live_run:
                # Update ClickHouse via Kafka message
                create_person_distinct_id(
                    team_id=team_id,
                    distinct_id=person_distinct_id["distinct_id"],
                    person_id=str(person_distinct_id["person_uuid"]),
                    version=pg_version,
                    is_deleted=False,
                )
        elif ch_version > pg_version:
            # This could be happening due to person deletions - check out fix_person_distinct_ids_after_delete management cmd.
            # Ignoring here to be safe.
            logger.info(
                f"Clickhouse version ({ch_version}) for '{person_distinct_id['distinct_id']}' is higher than in Postgres ({pg_version}). Ignoring."
            )
            continue

    if deletes:
        logger.info("Processing distinct id deletions")
        postgres_distinct_ids = {pdi["distinct_id"] for pdi in person_distinct_ids}
        tombstones = _postgres_distinct_id_tombstones(team_id)
        for distinct_id, version in ch_distinct_id_to_version.items():
            if distinct_id in postgres_distinct_ids:
                continue
            tombstone = tombstones.get(distinct_id)
            if tombstone is None:
                # Without a Postgres row there is no version to publish at; the sweep removes the mapping once
                # it deletes the owner.
                logger.warning(f"Skipping distinct ID {distinct_id}: Postgres has no row for it")
                continue
            person_uuid, tombstone_version = tombstone
            if tombstone_version <= int(version or 0):
                logger.warning(
                    f"Skipping distinct ID {distinct_id}: ClickHouse is at version {version}, "
                    f"the Postgres tombstone only at {tombstone_version}"
                )
                continue
            logger.info(f"Deleting distinct ID {distinct_id} at version {tombstone_version}")
            if live_run:
                create_person_distinct_id(
                    team_id=team_id,
                    distinct_id=distinct_id,
                    person_id=str(person_uuid),
                    version=tombstone_version,
                    is_deleted=True,
                )


def run_group_sync(team_id: int, live_run: bool):
    logger.info("Running group table sync")
    # lookup what needs to be updated in ClickHouse and send kafka messages for only those
    with persons_db_connection(writer=False) as conn, conn.cursor() as cursor:
        cursor.execute(
            "SELECT group_type_index, group_key, group_properties, created_at FROM posthog_group WHERE team_id = %s",
            [team_id],
        )
        pg_groups = [
            {
                "group_type_index": gti,
                "group_key": group_key,
                "group_properties": group_properties,
                "created_at": created_at,
            }
            for gti, group_key, group_properties, created_at in cursor.fetchall()
        ]
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
                    group_type_index=cast(Literal[0, 1, 2, 3, 4], pg_group["group_type_index"]),
                    group_key=pg_group["group_key"],
                    properties=pg_group["group_properties"],
                    created_at=pg_group["created_at"],
                )


def should_update_group(ch_group, pg_group) -> bool:
    return json.dumps(pg_group["group_properties"]) != ch_group["properties"] or pg_group["created_at"].strftime(
        "%Y-%m-%d %H:%M:%S"
    ) != ch_group["created_at"].strftime("%Y-%m-%d %H:%M:%S")
