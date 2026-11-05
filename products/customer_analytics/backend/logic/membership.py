import json
from collections.abc import Sequence
from hashlib import sha256

from posthog.clickhouse.client import sync_execute
from posthog.clickhouse.workload import Workload
from posthog.dataclasses import frozen
from posthog.models.person.util import get_distinct_id_rows
from posthog.personhog_client.client import personhog_call, require_personhog_client
from posthog.personhog_client.proto import CONSISTENCY_LEVEL_STRONG, GetGroupsRequest, GroupIdentifier, ReadOptions

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


def _parse_group_key(group_key: str) -> str:
    try:
        return json.loads(f'"{group_key}"')
    except json.JSONDecodeError:
        return group_key


def _get_live_groups(team_id: int, keys: Sequence[MembershipKey]) -> frozenset[tuple[int, str]]:
    # Membership keeps JSON escapes, but group identity storage uses decoded keys.
    lookup_keys: dict[tuple[int, str], tuple[int, str]] = {
        (key.group_type_index, key.group_key): (key.group_type_index, _parse_group_key(key.group_key)) for key in keys
    }
    groups = sync_execute(
        """SELECT DISTINCT group_type_index, group_key FROM groups
        WHERE team_id = %(team_id)s AND (group_type_index, group_key) IN %(groups)s""",
        {"team_id": team_id, "groups": list(set(lookup_keys.values()))},
        settings=QUERY_SETTINGS,
        workload=Workload.OFFLINE,
    )
    live_groups = {(row[0], row[1]) for row in groups}
    missing_groups = set(lookup_keys.values()) - live_groups
    if missing_groups:
        response = personhog_call(
            "membership_get_groups",
            lambda: require_personhog_client().get_groups(
                GetGroupsRequest(
                    team_id=team_id,
                    group_identifiers=[
                        GroupIdentifier(group_type_index=index, group_key=group_key)
                        for index, group_key in missing_groups
                    ],
                    read_options=ReadOptions(
                        consistency=CONSISTENCY_LEVEL_STRONG,
                        field_mask=["id", "team_id", "group_type_index", "group_key"],
                    ),
                )
            ),
        )
        live_groups.update((group.group_type_index, group.group_key) for group in response.groups if group.id)
    return frozenset(stored_key for stored_key, lookup_key in lookup_keys.items() if lookup_key in live_groups)


def get_membership_existence(team_id: int, keys: Sequence[MembershipKey]) -> MembershipExistence:
    if not keys:
        return MembershipExistence(persons=frozenset(), groups=frozenset())
    distinct_ids = {key.distinct_id for key in keys}
    parameters = {"team_id": team_id, "distinct_ids": list(distinct_ids)}
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
    live_distinct_ids = {mapping[0] for mapping in mappings if mapping[1][0] in live_person_ids}
    missing_distinct_ids = distinct_ids - live_distinct_ids
    if missing_distinct_ids:
        live_distinct_ids.update(
            row.distinct_id
            for row in get_distinct_id_rows(team_id, list(missing_distinct_ids), strong=True)
            if not row.is_deleted and row.HasField("person_is_deleted") and not row.person_is_deleted
        )
    return MembershipExistence(
        persons=frozenset(live_distinct_ids),
        groups=_get_live_groups(team_id, keys),
    )
