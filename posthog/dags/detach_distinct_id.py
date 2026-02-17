"""Dagster job to detach a distinct_id from its person.

Deletes the mapping in Postgres (posthog_persondistinctid), publishes a
deletion message to Kafka so ClickHouse person_distinct_id2 follows suit,
and inserts a person_distinct_id_overrides row so the squash job can fix
the person_id embedded on historical events.

Typical use: removing a sentinel ``$posthog_cookieless`` distinct_id that was
erroneously associated with a real person due to a cookieless-ingestion bug.
"""

import json
import uuid
from datetime import datetime

import dagster
import pydantic
import psycopg2.extensions

from posthog.clickhouse.client import sync_execute
from posthog.dags.common import JobOwners
from posthog.kafka_client.client import _KafkaProducer
from posthog.kafka_client.topics import KAFKA_PERSON_DISTINCT_ID


class DetachDistinctIdConfig(dagster.Config):
    """Configuration for the detach distinct_id job."""

    team_id: int = pydantic.Field(description="Team ID that owns the distinct_id")
    distinct_id: str = pydantic.Field(description="The distinct_id to detach (e.g. $posthog_cookieless)")
    expected_person_id: str = pydantic.Field(
        description="UUID of the person we expect the distinct_id to belong to (safety check)"
    )
    override_person_id: str | None = pydantic.Field(
        default=None,
        description=(
            "If set, insert a person_distinct_id_overrides row pointing historical events "
            "at this person UUID. If not set, a random dummy UUID is generated so events "
            "become orphaned. The scheduled squash job will later rewrite the embedded "
            "person_id on events and delete the override."
        ),
    )
    dry_run: bool = pydantic.Field(
        default=True,
        description="If true, log what would happen without making changes",
    )


def _lookup_distinct_id(
    cursor: psycopg2.extensions.cursor,
    team_id: int,
    distinct_id: str,
) -> dict | None:
    """Return the posthog_persondistinctid row + person uuid, or None."""
    cursor.execute(
        """
        SELECT pdi.id, pdi.version, pdi.person_id, p.uuid
        FROM posthog_persondistinctid pdi
        JOIN posthog_person p ON p.id = pdi.person_id AND p.team_id = pdi.team_id
        WHERE pdi.team_id = %s AND pdi.distinct_id = %s
        """,
        [team_id, distinct_id],
    )
    row = cursor.fetchone()
    if row is None:
        return None
    return {
        "pdi_id": row[0],
        "version": row[1],
        "person_pk": row[2],
        "person_uuid": str(row[3]),
    }


def _count_other_distinct_ids(
    cursor: psycopg2.extensions.cursor,
    team_id: int,
    person_pk: int,
    exclude_pdi_id: int,
) -> int:
    """Count how many *other* distinct_ids the person has."""
    cursor.execute(
        """
        SELECT COUNT(*)
        FROM posthog_persondistinctid
        WHERE team_id = %s AND person_id = %s AND id != %s
        """,
        [team_id, person_pk, exclude_pdi_id],
    )
    return cursor.fetchone()[0]


def _delete_distinct_id_row(
    cursor: psycopg2.extensions.cursor,
    pdi_id: int,
) -> int:
    """Lock and delete the posthog_persondistinctid row. Returns version."""
    cursor.execute(
        "SELECT version FROM posthog_persondistinctid WHERE id = %s FOR UPDATE",
        [pdi_id],
    )
    row = cursor.fetchone()
    if row is None:
        raise RuntimeError(f"posthog_persondistinctid id={pdi_id} disappeared between lookup and delete")
    version = row[0]
    cursor.execute("DELETE FROM posthog_persondistinctid WHERE id = %s", [pdi_id])
    return version


def _publish_deletion_to_kafka(
    producer: _KafkaProducer,
    team_id: int,
    distinct_id: str,
    person_uuid: str,
    version: int,
) -> None:
    """Publish an is_deleted message so ClickHouse person_distinct_id2 drops the mapping.

    Uses version + 100, matching _delete_ch_distinct_id in posthog/models/person/util.py.
    """
    producer.produce(
        topic=KAFKA_PERSON_DISTINCT_ID,
        data={
            "distinct_id": distinct_id,
            "person_id": person_uuid,
            "team_id": team_id,
            "version": version + 100,
            "is_deleted": 1,
        },
    )
    producer.flush()


def _insert_ch_override(
    team_id: int,
    distinct_id: str,
    override_person_uuid: str,
    version: int,
) -> None:
    """Insert a person_distinct_id_overrides row so the squash job re-attributes historical events.

    Follows the same pattern as insert_override_batch in fix_person_id_overrides.py.
    """
    sync_execute(
        """
        INSERT INTO person_distinct_id_overrides
        (team_id, distinct_id, person_id, is_deleted, version, _timestamp, _offset, _partition)
        VALUES
        """,
        [(team_id, distinct_id, override_person_uuid, 0, version, datetime.now(), 0, 0)],
    )


@dagster.op
def detach_distinct_id_op(
    context: dagster.OpExecutionContext,
    config: DetachDistinctIdConfig,
    persons_database: dagster.ResourceParam[psycopg2.extensions.connection],
    kafka_producer: dagster.ResourceParam[_KafkaProducer],
) -> None:
    """Detach a distinct_id from its person in Postgres and ClickHouse."""
    log = context.log

    log.info(f"team_id={config.team_id} distinct_id={config.distinct_id!r}")
    log.info(f"expected_person_id={config.expected_person_id}")
    log.info(f"dry_run={config.dry_run}")

    # --- 1. Validate in Postgres ---
    with persons_database.cursor() as cursor:
        cursor.execute("SET application_name = 'detach_distinct_id'")
        cursor.execute("SET lock_timeout = '5s'")
        cursor.execute("SET statement_timeout = '30s'")

        info = _lookup_distinct_id(cursor, config.team_id, config.distinct_id)
        if info is None:
            raise dagster.Failure(f"distinct_id={config.distinct_id!r} not found for team_id={config.team_id}")

        log.info(
            f"Found: pdi_id={info['pdi_id']} version={info['version']} "
            f"person_uuid={info['person_uuid']} person_pk={info['person_pk']}"
        )

        if info["person_uuid"] != config.expected_person_id:
            raise dagster.Failure(
                f"Person mismatch: distinct_id belongs to {info['person_uuid']}, expected {config.expected_person_id}"
            )

        other_count = _count_other_distinct_ids(cursor, config.team_id, info["person_pk"], info["pdi_id"])
        if other_count == 0:
            raise dagster.Failure(
                f"Cannot detach: this is the person's only distinct_id. "
                f"Detaching would orphan person {info['person_uuid']}"
            )
        log.info(f"Person has {other_count} other distinct_id(s) — safe to detach")

        # --- 2. Resolve override target ---
        override_target = config.override_person_id or str(uuid.uuid4())
        log.info(f"Override target person_id={override_target}")

        # --- 3. Delete in Postgres ---
        if config.dry_run:
            log.info("[DRY RUN] Would delete posthog_persondistinctid row")
            log.info("[DRY RUN] Would publish Kafka deletion to person_distinct_id2")
            log.info(f"[DRY RUN] Would insert person_distinct_id_overrides -> {override_target}")
            persons_database.rollback()
            return

        version = _delete_distinct_id_row(cursor, info["pdi_id"])
        persons_database.commit()
        log.info(f"Deleted posthog_persondistinctid id={info['pdi_id']} (version={version})")

    # --- 4. Sync deletion to ClickHouse via Kafka ---
    _publish_deletion_to_kafka(
        kafka_producer,
        team_id=config.team_id,
        distinct_id=config.distinct_id,
        person_uuid=info["person_uuid"],
        version=version,
    )
    log.info(f"Published deletion to {KAFKA_PERSON_DISTINCT_ID} (version={version + 100}, is_deleted=1)")

    # --- 5. Insert override so squash job fixes historical events ---
    _insert_ch_override(
        team_id=config.team_id,
        distinct_id=config.distinct_id,
        override_person_uuid=override_target,
        version=version + 100,
    )
    log.info(f"Inserted person_distinct_id_overrides: {config.distinct_id!r} -> {override_target}")

    # --- 6. Verification hints ---
    log.info("--- Verification queries (run manually) ---")
    log.info(
        f"Postgres: SELECT * FROM posthog_persondistinctid "
        f"WHERE team_id = {config.team_id} AND distinct_id = '{config.distinct_id}'"
    )
    escaped_did = json.dumps(config.distinct_id)
    log.info(
        f"ClickHouse (pdi2): SELECT distinct_id, argMax(person_id, version), "
        f"argMax(is_deleted, version), max(version) "
        f"FROM person_distinct_id2 "
        f"WHERE team_id = {config.team_id} AND distinct_id = {escaped_did} "
        f"GROUP BY distinct_id"
    )
    log.info(
        f"ClickHouse (overrides): SELECT distinct_id, argMax(person_id, version), max(version) "
        f"FROM person_distinct_id_overrides "
        f"WHERE team_id = {config.team_id} AND distinct_id = {escaped_did} "
        f"GROUP BY distinct_id"
    )


@dagster.job(tags={"owner": JobOwners.TEAM_INGESTION.value})
def detach_distinct_id_job():
    """Job to detach a distinct_id from its person in Postgres and ClickHouse."""
    detach_distinct_id_op()
