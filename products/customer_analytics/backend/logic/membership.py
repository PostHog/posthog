import json
from collections.abc import Sequence
from hashlib import sha256

from posthog.clickhouse.client import sync_execute
from posthog.clickhouse.workload import Workload
from posthog.dataclasses import frozen

QUERY_TIMEOUT_SECONDS = 30

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


def get_membership_existence(team_id: int, keys: Sequence[MembershipKey]) -> MembershipExistence:
    if not keys:
        return MembershipExistence(persons=frozenset(), groups=frozenset())
    parameters = {"team_id": team_id, "distinct_ids": list({key.distinct_id for key in keys})}
    mappings = sync_execute(
        """SELECT distinct_id, argMax(tuple(person_id, is_deleted), version) AS mapping
        FROM person_distinct_id2
        WHERE team_id = %(team_id)s AND distinct_id IN %(distinct_ids)s
        GROUP BY distinct_id
        HAVING mapping.2 = 0""",
        parameters,
        settings=QUERY_SETTINGS,
        workload=Workload.OFFLINE,
    )
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
