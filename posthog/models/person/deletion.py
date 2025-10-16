from typing import Optional

from django.db import router, transaction

import structlog
from rest_framework.exceptions import NotFound

from posthog.clickhouse.client import sync_execute
from posthog.models.person import PersonDistinctId
from posthog.models.person.util import create_person_distinct_id

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
    # Determine the correct database for PersonDistinctId writes (handles persons_db_writer routing in production)
    db_alias = router.db_for_write(PersonDistinctId) or "default"

    for distinct_id, version in distinct_id_versions:
        # this can throw but this script can safely be re-run as
        # updated distinct_ids won't show up in the search anymore
        # since they no longer belong to deleted persons
        # it's safer to throw and exit if anything went wrong

        with transaction.atomic(using=db_alias):
            person_distinct_id = _update_distinct_id_in_postgres(distinct_id, version, team_id)

        # Update ClickHouse via Kafka message
        if person_distinct_id:
            create_person_distinct_id(
                team_id=team_id,
                distinct_id=distinct_id,
                person_id=str(person_distinct_id.person.uuid),
                version=version,
                is_deleted=False,
            )


def _update_distinct_id_in_postgres(distinct_id: str, version: int, team_id: int) -> Optional[PersonDistinctId]:
    person_distinct_id = PersonDistinctId.objects.filter(team_id=team_id, distinct_id=distinct_id).first()
    if person_distinct_id is None:
        logger.info(f"Distinct id {distinct_id} hasn't been re-used yet and can cause problems in the future")
        return None
    person_distinct_id.version = version
    person_distinct_id.save()
    return person_distinct_id
