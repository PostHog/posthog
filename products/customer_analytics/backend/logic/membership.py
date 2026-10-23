import json
from collections.abc import Sequence
from datetime import datetime
from hashlib import sha256

from posthog.clickhouse.client import sync_execute
from posthog.clickhouse.workload import Workload
from posthog.dataclasses import frozen
from posthog.models.person_group_membership.sql import PERSON_GROUP_MEMBERSHIP_MAX_GROUP_TYPE_INDEX

QUERY_TIMEOUT_SECONDS = 30
DEFAULT_MEMBERSHIP_PAGE_SIZE = 100
MAX_MEMBERSHIP_PAGE_SIZE = 500

# These budgets cap each lookup. Exceeding a budget must fail the batch, never report a missing identity.
QUERY_SETTINGS = {
    "max_execution_time": str(QUERY_TIMEOUT_SECONDS),
    "max_memory_usage": str(256 * 1024**2),
    "max_bytes_to_read": str(1024**3),
    "max_threads": "2",
    "max_result_bytes": str(4 * 1024**2),
    "result_overflow_mode": "throw",
    "skip_unavailable_shards": "0",
    "timeout_overflow_mode": "throw",
    "read_overflow_mode": "throw",
}


@frozen
class MembershipKey:
    group_type_index: int
    group_key: str
    distinct_id: str

    def get_hash(self) -> str:
        return sha256(json.dumps([self.group_type_index, self.group_key, self.distinct_id]).encode()).hexdigest()


@frozen
class MembershipExistence:
    persons: frozenset[str]
    groups: frozenset[tuple[int, str]]


@frozen
class MembershipPerson:
    person_id: str
    properties: dict[str, object]
    first_seen: datetime
    last_seen: datetime


CURRENT_MAPPINGS = """
    SELECT distinct_id, argMax(tuple(person_id, is_deleted), version) AS mapping
    FROM person_distinct_id2
    WHERE team_id = %(team_id)s AND distinct_id IN %(distinct_ids)s
    GROUP BY distinct_id
    HAVING mapping.2 = 0
"""


def get_membership_existence(team_id: int, keys: Sequence[MembershipKey]) -> MembershipExistence:
    if not keys:
        return MembershipExistence(persons=frozenset(), groups=frozenset())
    parameters = {"team_id": team_id, "distinct_ids": list({key.distinct_id for key in keys})}
    mappings = sync_execute(CURRENT_MAPPINGS, parameters, settings=QUERY_SETTINGS, workload=Workload.OFFLINE)
    person_ids = list({mapping[1][0] for mapping in mappings})
    persons = (
        sync_execute(
            """SELECT id FROM person WHERE team_id = %(team_id)s AND id IN %(person_ids)s
            GROUP BY id HAVING argMax(is_deleted, version) = 0""",
            {"team_id": team_id, "person_ids": person_ids},
            settings=QUERY_SETTINGS,
            workload=Workload.OFFLINE,
        )
        if person_ids
        else []
    )
    live_person_ids = {row[0] for row in persons}
    groups = sync_execute(
        """SELECT DISTINCT group_type_index, group_key FROM groups
        WHERE team_id = %(team_id)s AND (group_type_index, group_key) IN %(groups)s""",
        {"team_id": team_id, "groups": list({(key.group_type_index, key.group_key) for key in keys})},
        settings=QUERY_SETTINGS,
        workload=Workload.OFFLINE,
    )
    return MembershipExistence(
        persons=frozenset(mapping[0] for mapping in mappings if mapping[1][0] in live_person_ids),
        groups=frozenset((row[0], row[1]) for row in groups),
    )


def list_membership_persons(
    *,
    team_id: int,
    group_type_index: int,
    group_key: str,
    limit: int = DEFAULT_MEMBERSHIP_PAGE_SIZE,
    offset: int = 0,
) -> list[MembershipPerson]:
    """Callers must check account access, person access, and restricted properties before exposing these rows."""
    if (
        not 0 <= group_type_index <= PERSON_GROUP_MEMBERSHIP_MAX_GROUP_TYPE_INDEX
        or not 1 <= limit <= MAX_MEMBERSHIP_PAGE_SIZE
        or offset < 0
    ):
        raise ValueError(
            f"Use a group index from 0 to {PERSON_GROUP_MEMBERSHIP_MAX_GROUP_TYPE_INDEX}. "
            f"Use a limit from 1 to {MAX_MEMBERSHIP_PAGE_SIZE} and a nonnegative offset."
        )
    rows = sync_execute(
        """
        WITH membership AS (
            SELECT distinct_id, min(first_seen) AS first_seen, max(last_seen) AS last_seen
            FROM person_group_membership
            WHERE team_id = %(team_id)s AND group_type_index = %(index)s AND group_key = %(key)s
            GROUP BY distinct_id
        ), mappings AS (
            SELECT distinct_id, argMax(tuple(person_id, is_deleted), version) AS mapping
            FROM person_distinct_id2
            WHERE team_id = %(team_id)s AND distinct_id GLOBAL IN (SELECT distinct_id FROM membership)
            GROUP BY distinct_id HAVING mapping.2 = 0
        ), live_persons AS (
            SELECT id, argMax(tuple(properties, is_deleted), version) AS profile
            FROM person
            WHERE team_id = %(team_id)s AND id GLOBAL IN (SELECT mapping.1 FROM mappings)
            GROUP BY id HAVING profile.2 = 0
        )
        SELECT persons.id, persons.profile.1, min(membership.first_seen), max(membership.last_seen)
        FROM mappings
        INNER JOIN live_persons AS persons ON mappings.mapping.1 = persons.id
        GLOBAL INNER JOIN membership ON mappings.distinct_id = membership.distinct_id
        GROUP BY persons.id, persons.profile.1
        ORDER BY persons.id LIMIT %(limit)s OFFSET %(offset)s
        """,
        {"team_id": team_id, "index": group_type_index, "key": group_key, "limit": limit, "offset": offset},
        settings=QUERY_SETTINGS,
        workload=Workload.ONLINE,
    )
    return [
        MembershipPerson(person_id=str(row[0]), properties=json.loads(row[1]), first_seen=row[2], last_seen=row[3])
        for row in rows
    ]
