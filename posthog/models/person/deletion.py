from typing import Optional

from django.db import router, transaction

import structlog
from rest_framework.exceptions import NotFound

from posthog.clickhouse.client import sync_execute
from posthog.models.person import Person, PersonDistinctId
from posthog.models.person.util import create_person, create_person_distinct_id

logger = structlog.get_logger(__name__)


def reset_all_deleted_person_distinct_ids(team_id: int, version: int = 2500):
    # NOTE: Version is arbitrary, we just need to make sure it's higher than any existing version
    distinct_ids = _get_distinct_ids_tied_to_deleted_persons(team_id)
    distinct_ids_and_versions: list[tuple[str, int]] = [(distinct_id, version) for distinct_id in distinct_ids]
    _updated_distinct_ids(team_id, distinct_ids_and_versions)


def reset_deleted_person_distinct_ids(team_id: int, distinct_id: str):
    existing_version = _get_version_for_distinct_id(team_id, distinct_id)
    distinct_ids_and_versions = [(distinct_id, existing_version + 100)]

    logger.info(f"Resetting distinct id {distinct_id} to version {existing_version + 100}")
    _updated_distinct_ids(team_id, distinct_ids_and_versions)


def _get_distinct_ids_tied_to_deleted_persons(team_id: int) -> list[str]:
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


def _get_version_for_distinct_id(team_id: int, distinct_id: str) -> int:
    rows = sync_execute(
        """
            SELECT max(version) as version FROM person_distinct_id2 WHERE team_id = %(team)s AND distinct_id = %(distinct_id)s
        """,
        {
            "team": team_id,
            "distinct_id": distinct_id,
        },
    )

    if len(rows) == 0:
        raise NotFound(f"Distinct id {distinct_id} not found")
    return rows[0][0]


def _updated_distinct_ids(team_id: int, distinct_id_versions: list[tuple[str, int]]):
    # DB alias for the ORM-fallback person-version write below (handles persons_db_writer routing in production)
    db_alias = router.db_for_write(PersonDistinctId) or "default"
    reset_person_uuids: set[str] = set()

    for distinct_id, version in distinct_id_versions:
        # this can throw but this script can safely be re-run as
        # updated distinct_ids won't show up in the search anymore
        # since they no longer belong to deleted persons
        # it's safer to throw and exit if anything went wrong

        # No transaction here: the write goes through personhog (an external RPC that
        # can't join a Postgres transaction) or, on fallback, an ORM write that scopes
        # its own atomic block. See _set_distinct_id_version_floor_via_orm.
        person = _update_distinct_id_in_postgres(distinct_id, version, team_id)

        # Update ClickHouse via Kafka message
        if person:
            person_uuid = str(person.uuid)

            create_person_distinct_id(
                team_id=team_id,
                distinct_id=distinct_id,
                person_id=person_uuid,
                version=version,
                is_deleted=False,
            )

            # Also reset the person record in ClickHouse — the soft-deleted person row
            # has a high version that causes ReplacingMergeTree to keep the deleted state,
            # making the person invisible to analytics queries
            if person_uuid not in reset_person_uuids:
                reset_person_uuids.add(person_uuid)
                _reset_person_in_clickhouse(team_id, person, db_alias)


def _update_distinct_id_in_postgres(distinct_id: str, version: int, team_id: int) -> Optional[Person]:
    """Raise the distinct_id's version to at least `version` and return its person.

    Routes through SetPersonDistinctIdVersionFloor (guarded — never lowers the
    version), falling back to a direct ORM read+save. Returns None when the
    distinct_id doesn't exist (it hasn't been re-used yet).
    """
    from posthog.models.person.util import _personhog_routed

    return _personhog_routed(
        "set_person_distinct_id_version_floor",
        lambda: _set_distinct_id_version_floor_via_personhog(team_id, distinct_id, version),
        lambda: _set_distinct_id_version_floor_via_orm(team_id, distinct_id, version),
        team_id=team_id,
    )


def _set_distinct_id_version_floor_via_personhog(team_id: int, distinct_id: str, version: int) -> Optional[Person]:
    from posthog.personhog_client.client import get_personhog_client
    from posthog.personhog_client.converters import proto_person_to_model
    from posthog.personhog_client.proto import SetPersonDistinctIdVersionFloorRequest

    client = get_personhog_client()
    if client is None:
        raise RuntimeError("personhog client not configured")

    resp = client.set_person_distinct_id_version_floor(
        SetPersonDistinctIdVersionFloorRequest(team_id=team_id, distinct_id=distinct_id, min_version=version)
    )
    if not resp.HasField("person"):
        logger.info(f"Distinct id {distinct_id} hasn't been re-used yet and can cause problems in the future")
        return None
    return proto_person_to_model(resp.person, distinct_ids=[distinct_id])


def _set_distinct_id_version_floor_via_orm(team_id: int, distinct_id: str, version: int) -> Optional[Person]:
    # Scope the transaction to exactly this local read+write. The personhog path makes
    # no Postgres writes, so the caller must not wrap the routed call in an atomic block.
    db_alias = router.db_for_write(PersonDistinctId) or "default"
    with transaction.atomic(using=db_alias):
        person_distinct_id = (
            PersonDistinctId.objects.filter(  # nosemgrep: no-direct-persons-db-orm
                team_id=team_id, distinct_id=distinct_id
            )
            .select_related("person")
            .first()
        )
        if person_distinct_id is None:
            logger.info(f"Distinct id {distinct_id} hasn't been re-used yet and can cause problems in the future")
            return None
        # Guarded floor: never lower the stored version (matches the RPC semantics).
        if person_distinct_id.version is None or person_distinct_id.version < version:
            person_distinct_id.version = version
            person_distinct_id.save()
        return person_distinct_id.person


def _get_person_version_if_deleted(team_id: int, person_uuid: str) -> Optional[int]:
    """Returns the max version if the person is soft-deleted in ClickHouse, None otherwise."""
    rows = sync_execute(
        """
            SELECT max(version), argMax(is_deleted, version)
            FROM person
            WHERE team_id = %(team_id)s AND id = %(person_id)s
        """,
        {"team_id": team_id, "person_id": person_uuid},
    )
    if len(rows) == 0:
        return None
    max_version, is_deleted = rows[0]
    if not is_deleted:
        return None
    return max_version


def _reset_person_in_clickhouse(team_id: int, person: Person, db_alias: str) -> None:
    person_uuid = str(person.uuid)
    max_version = _get_person_version_if_deleted(team_id, person_uuid)
    if max_version is None:
        return

    new_version = max_version + 100
    logger.info(f"Resetting person {person_uuid} in ClickHouse to version {new_version}")

    # Raise the Postgres version so future updates from the plugin-server (which
    # reads version from Postgres) won't be ignored by ClickHouse.
    _set_person_version_floor(team_id, person.pk, new_version, db_alias)

    create_person(
        uuid=person_uuid,
        team_id=team_id,
        version=new_version,
        properties=person.properties,
        is_identified=person.is_identified,
        is_deleted=False,
        created_at=person.created_at,
    )


def _set_person_version_floor(team_id: int, person_id: int, new_version: int, db_alias: str) -> None:
    """Raise a person's version to at least `new_version` (guarded — never lowers).

    Routes through SetPersonVersionFloor, falling back to a guarded ORM update.
    """
    from posthog.models.person.util import _personhog_routed

    _personhog_routed(
        "set_person_version_floor",
        lambda: _set_person_version_floor_via_personhog(team_id, person_id, new_version),
        lambda: _set_person_version_floor_via_orm(person_id, new_version, db_alias),
        team_id=team_id,
    )


def _set_person_version_floor_via_personhog(team_id: int, person_id: int, new_version: int) -> None:
    from posthog.personhog_client.client import get_personhog_client
    from posthog.personhog_client.proto import SetPersonVersionFloorRequest

    client = get_personhog_client()
    if client is None:
        raise RuntimeError("personhog client not configured")

    client.set_person_version_floor(
        SetPersonVersionFloorRequest(team_id=team_id, person_id=person_id, min_version=new_version)
    )


def _set_person_version_floor_via_orm(person_id: int, new_version: int, db_alias: str) -> None:
    Person.objects.using(db_alias).filter(  # nosemgrep: no-direct-persons-db-orm
        pk=person_id, version__lt=new_version
    ).update(  # nosemgrep: no-direct-persons-db-orm
        version=new_version
    )
