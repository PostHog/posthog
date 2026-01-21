import os
import json
import dataclasses
from urllib.parse import quote_plus

from django.conf import settings

import psycopg
import temporalio.activity
from structlog import get_logger

from posthog.models.person.util import create_person, create_person_distinct_id
from posthog.temporal.common.clickhouse import get_client
from posthog.temporal.common.heartbeat import Heartbeater

LOGGER = get_logger(__name__)


def get_persons_database_url() -> str:
    """Get the connection URL for the persons database reader.

    Falls back to DATABASE_URL for hobby deployments without separate persons DB.
    """
    url = os.getenv("PERSONS_DB_READER_URL")
    if url:
        return url

    if "persons_db_reader" in settings.DATABASES:
        db = settings.DATABASES["persons_db_reader"]
        user = db.get("USER", "")
        password = db.get("PASSWORD", "")
        host = db.get("HOST", "localhost")
        port = db.get("PORT", "5432")
        name = db.get("NAME", "")
        if password:
            return f"postgres://{quote_plus(user)}:{quote_plus(password)}@{host}:{port}/{name}"
        return f"postgres://{quote_plus(user)}@{host}:{port}/{name}"

    return settings.DATABASE_URL


@dataclasses.dataclass
class OrphanedPerson:
    """Represents an orphaned person from ClickHouse."""

    person_id: str
    team_id: int
    created_at: str
    version: int


@dataclasses.dataclass
class FindOrphanedPersonsInputs:
    """Inputs for the find_orphaned_persons activity."""

    team_id: int
    limit: int | None = None
    person_ids: list[str] | None = None  # If provided, only check these specific persons


@dataclasses.dataclass
class FindOrphanedPersonsResult:
    """Result of finding orphaned persons in ClickHouse."""

    orphaned_persons: list[OrphanedPerson]


@temporalio.activity.defn
async def find_orphaned_persons(inputs: FindOrphanedPersonsInputs) -> FindOrphanedPersonsResult:
    """Find all persons in ClickHouse that have no corresponding distinct IDs.

    This runs a single query to get all orphaned persons for the team.
    The result set is small (just UUIDs + metadata), so it's efficient to fetch all at once.
    Batching happens in the workflow when processing (PG lookups, CH writes).
    """
    async with Heartbeater() as heartbeater:
        logger = LOGGER.bind(team_id=inputs.team_id, limit=inputs.limit, person_ids_count=len(inputs.person_ids or []))
        await logger.ainfo("Finding orphaned persons in ClickHouse")

        heartbeater.details = ("Finding all orphaned persons",)

        limit_clause = f"LIMIT {inputs.limit}" if inputs.limit else ""
        person_ids_clause = "AND id IN %(person_ids)s" if inputs.person_ids else ""

        query = f"""
            SELECT
                id AS person_id,
                team_id,
                toString(created_at) AS created_at,
                version
            FROM person FINAL
            WHERE team_id = %(team_id)s
              AND is_deleted = 0
              AND id NOT IN (
                SELECT DISTINCT person_id
                FROM person_distinct_id2 FINAL
                WHERE team_id = %(team_id)s
              )
              {person_ids_clause}
            ORDER BY created_at ASC
            {limit_clause}
            FORMAT JSONEachRow
        """

        query_params: dict = {"team_id": inputs.team_id}
        if inputs.person_ids:
            query_params["person_ids"] = inputs.person_ids

        async with get_client(team_id=inputs.team_id) as client:
            response = await client.read_query(
                query,
                query_parameters=query_params,
            )

        orphaned_persons: list[OrphanedPerson] = []

        if response:
            lines = response.decode("utf-8").strip().split("\n")
            for line in lines:
                if line:
                    data = json.loads(line)
                    orphaned_persons.append(
                        OrphanedPerson(
                            person_id=data["person_id"],
                            team_id=int(data["team_id"]),
                            created_at=data["created_at"],
                            version=int(data["version"]),
                        )
                    )

        await logger.ainfo("Found orphaned persons", count=len(orphaned_persons))
        return FindOrphanedPersonsResult(orphaned_persons=orphaned_persons)


@dataclasses.dataclass
class PersonDistinctIdMapping:
    """Maps a person UUID to their distinct IDs from PostgreSQL.

    Each distinct ID has its own version, as versions are per-DID and increment
    during merges when DIDs move between persons.
    """

    person_uuid: str
    distinct_id_versions: dict[str, int]  # Maps distinct_id -> version


@dataclasses.dataclass
class LookupPgDistinctIdsInputs:
    """Inputs for the lookup_pg_distinct_ids activity."""

    team_id: int
    person_uuids: list[str]
    categorize_not_found: bool = False  # If True, run extra query to distinguish truly orphaned vs CH-only


@dataclasses.dataclass
class LookupPgDistinctIdsResult:
    """Result of looking up distinct IDs in PostgreSQL."""

    mappings: list[PersonDistinctIdMapping]
    persons_not_found: list[str]  # All persons without DIDs in PG (truly orphaned + CH-only)
    persons_truly_orphaned: list[str]  # Persons in PG but without DIDs (only populated if categorize_not_found=True)
    persons_ch_only: list[str]  # Persons not in PG at all (only populated if categorize_not_found=True)


@temporalio.activity.defn
async def lookup_pg_distinct_ids(inputs: LookupPgDistinctIdsInputs) -> LookupPgDistinctIdsResult:
    """Look up distinct IDs in PostgreSQL for given person UUIDs."""
    async with Heartbeater() as heartbeater:
        logger = LOGGER.bind(team_id=inputs.team_id, person_count=len(inputs.person_uuids))
        await logger.ainfo("Looking up distinct IDs in PostgreSQL")

        heartbeater.details = (f"Looking up {len(inputs.person_uuids)} persons in PostgreSQL",)

        query = """
            SELECT
                p.uuid::text as person_uuid,
                pdi.distinct_id,
                COALESCE(pdi.version, 0) as version
            FROM posthog_person p
            JOIN posthog_persondistinctid pdi ON pdi.person_id = p.id
            WHERE p.team_id = %(team_id)s
              AND p.uuid = ANY(%(person_uuids)s::uuid[])
            ORDER BY p.uuid, pdi.id
        """

        persons_db_url = get_persons_database_url()
        conn = await psycopg.AsyncConnection.connect(persons_db_url)
        async with conn:
            async with conn.cursor() as cursor:
                await cursor.execute(
                    query,
                    {"team_id": inputs.team_id, "person_uuids": inputs.person_uuids},
                )
                rows = await cursor.fetchall()

        person_to_distinct_ids: dict[str, dict[str, int]] = {}
        for row in rows:
            person_uuid, distinct_id, version = row
            if person_uuid not in person_to_distinct_ids:
                person_to_distinct_ids[person_uuid] = {}
            person_to_distinct_ids[person_uuid][distinct_id] = version

        mappings: list[PersonDistinctIdMapping] = []
        persons_not_found: list[str] = []

        for person_uuid in inputs.person_uuids:
            if person_uuid in person_to_distinct_ids:
                mappings.append(
                    PersonDistinctIdMapping(
                        person_uuid=person_uuid,
                        distinct_id_versions=person_to_distinct_ids[person_uuid],
                    )
                )
            else:
                persons_not_found.append(person_uuid)

        # Categorize persons_not_found into truly orphaned vs CH-only (optional extra query)
        persons_truly_orphaned: list[str] = []
        persons_ch_only: list[str] = []

        if inputs.categorize_not_found and persons_not_found:
            heartbeater.details = (f"Categorizing {len(persons_not_found)} persons not found",)

            # Find which of the not-found persons exist in PG (without DIDs)
            categorize_query = """
                SELECT uuid::text
                FROM posthog_person
                WHERE team_id = %(team_id)s
                  AND uuid = ANY(%(person_uuids)s::uuid[])
            """
            conn = await psycopg.AsyncConnection.connect(persons_db_url)
            async with conn:
                async with conn.cursor() as cursor:
                    await cursor.execute(
                        categorize_query,
                        {"team_id": inputs.team_id, "person_uuids": persons_not_found},
                    )
                    rows = await cursor.fetchall()

            persons_in_pg = {row[0] for row in rows}

            for person_uuid in persons_not_found:
                if person_uuid in persons_in_pg:
                    persons_truly_orphaned.append(person_uuid)
                else:
                    persons_ch_only.append(person_uuid)

            await logger.ainfo(
                "PostgreSQL lookup complete",
                found=len(mappings),
                truly_orphaned=len(persons_truly_orphaned),
                ch_only=len(persons_ch_only),
            )
        else:
            await logger.ainfo(
                "PostgreSQL lookup complete",
                found=len(mappings),
                not_found=len(persons_not_found),
            )

        return LookupPgDistinctIdsResult(
            mappings=mappings,
            persons_not_found=persons_not_found,
            persons_truly_orphaned=persons_truly_orphaned,
            persons_ch_only=persons_ch_only,
        )


@dataclasses.dataclass
class SyncDistinctIdsToChInputs:
    """Inputs for the sync_distinct_ids_to_ch activity."""

    team_id: int
    mappings: list[PersonDistinctIdMapping]
    dry_run: bool


@dataclasses.dataclass
class SyncDistinctIdsToChResult:
    """Result of syncing distinct IDs to ClickHouse."""

    distinct_ids_synced: int
    persons_synced: int


@temporalio.activity.defn
async def sync_distinct_ids_to_ch(inputs: SyncDistinctIdsToChInputs) -> SyncDistinctIdsToChResult:
    """Sync missing distinct IDs to ClickHouse via Kafka."""
    async with Heartbeater() as heartbeater:
        logger = LOGGER.bind(team_id=inputs.team_id, mapping_count=len(inputs.mappings), dry_run=inputs.dry_run)

        total_distinct_ids = sum(len(m.distinct_id_versions) for m in inputs.mappings)
        heartbeater.details = (f"Syncing {total_distinct_ids} distinct IDs to ClickHouse",)

        if inputs.dry_run:
            await logger.ainfo(
                "DRY RUN: Would sync distinct IDs to ClickHouse",
                persons=len(inputs.mappings),
                distinct_ids=total_distinct_ids,
            )
            for mapping in inputs.mappings:
                await logger.ainfo(
                    "DRY RUN: Would sync",
                    person_uuid=mapping.person_uuid,
                    distinct_id_versions=mapping.distinct_id_versions,
                )
            return SyncDistinctIdsToChResult(
                distinct_ids_synced=total_distinct_ids,
                persons_synced=len(inputs.mappings),
            )

        await logger.ainfo(
            "Syncing distinct IDs to ClickHouse",
            persons=len(inputs.mappings),
            distinct_ids=total_distinct_ids,
        )

        for mapping in inputs.mappings:
            for distinct_id, version in mapping.distinct_id_versions.items():
                create_person_distinct_id(
                    team_id=inputs.team_id,
                    distinct_id=distinct_id,
                    person_id=mapping.person_uuid,
                    version=version,
                    is_deleted=False,
                    sync=False,
                )

        await logger.ainfo(
            "Synced distinct IDs to ClickHouse",
            persons=len(inputs.mappings),
            distinct_ids=total_distinct_ids,
        )

        return SyncDistinctIdsToChResult(
            distinct_ids_synced=total_distinct_ids,
            persons_synced=len(inputs.mappings),
        )


@dataclasses.dataclass
class MarkChOnlyOrphansDeletedInputs:
    """Inputs for the mark_ch_only_orphans_deleted activity."""

    team_id: int
    person_versions: dict[str, int]  # Maps person_uuid -> current version
    dry_run: bool


@dataclasses.dataclass
class MarkChOnlyOrphansDeletedResult:
    """Result of marking CH-only orphans as deleted."""

    persons_marked_deleted: int


@temporalio.activity.defn
async def mark_ch_only_orphans_deleted(inputs: MarkChOnlyOrphansDeletedInputs) -> MarkChOnlyOrphansDeletedResult:
    """Mark persons without PostgreSQL data as deleted in ClickHouse."""
    async with Heartbeater() as heartbeater:
        logger = LOGGER.bind(team_id=inputs.team_id, person_count=len(inputs.person_versions), dry_run=inputs.dry_run)

        heartbeater.details = (f"Marking {len(inputs.person_versions)} CH-only orphans as deleted",)

        if inputs.dry_run:
            await logger.ainfo(
                "DRY RUN: Would mark CH-only orphans as deleted",
                count=len(inputs.person_versions),
            )
            for person_uuid, version in inputs.person_versions.items():
                await logger.ainfo("DRY RUN: Would mark as deleted", person_uuid=person_uuid, version=version)
            return MarkChOnlyOrphansDeletedResult(persons_marked_deleted=len(inputs.person_versions))

        await logger.ainfo("Marking CH-only orphans as deleted", count=len(inputs.person_versions))

        for person_uuid, current_version in inputs.person_versions.items():
            create_person(
                uuid=person_uuid,
                team_id=inputs.team_id,
                version=current_version + 1,
                is_deleted=True,
                sync=False,
            )

        await logger.ainfo("Marked CH-only orphans as deleted", count=len(inputs.person_versions))

        return MarkChOnlyOrphansDeletedResult(persons_marked_deleted=len(inputs.person_versions))
