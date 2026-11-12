import re
import json
from collections.abc import Callable, Iterator, Sequence
from contextlib import contextmanager, nullcontext
from hashlib import sha256
from threading import Event, Thread
from time import monotonic

from redis.lock import Lock

from posthog.clickhouse.client import sync_execute
from posthog.clickhouse.workload import Workload
from posthog.dataclasses import frozen
from posthog.models.person.util import get_distinct_id_rows
from posthog.personhog_client.client import personhog_call, require_personhog_client
from posthog.personhog_client.proto import CONSISTENCY_LEVEL_STRONG, GetGroupsRequest, GroupIdentifier, ReadOptions
from posthog.redis import get_client as get_redis_client
from posthog.settings import HOGQL_INCREASED_MAX_EXECUTION_TIME

from products.customer_analytics.backend.logic.membership_metrics import MembershipTimings

QUERY_TIMEOUT_SECONDS = HOGQL_INCREASED_MAX_EXECUTION_TIME
# Longer keys cannot exist in the primary group's varchar(400) column.
MAX_GROUP_KEY_LENGTH = 400
MEMBERSHIP_LEASE_SECONDS = 60 * 60
MEMBERSHIP_LEASE_RENEWAL_SECONDS = 5

# Partial results must fail the batch, never report a missing identity.
QUERY_SETTINGS = {
    "max_execution_time": str(QUERY_TIMEOUT_SECONDS),
    "result_overflow_mode": "throw",
    "skip_unavailable_shards": "0",
    "timeout_overflow_mode": "throw",
    "read_overflow_mode": "throw",
}


class MembershipCleanupBusy(Exception):
    pass


def get_membership_query_settings(deadline: float | None = None) -> dict[str, str]:
    if deadline is None:
        return QUERY_SETTINGS
    remaining = int(deadline - monotonic())
    if remaining <= 0:
        raise TimeoutError("The membership batch deadline has passed. Retry the batch.")
    return {**QUERY_SETTINGS, "max_execution_time": str(min(QUERY_TIMEOUT_SECONDS, remaining))}


def get_membership_cleanup_lease(team_id: int, *, timeout: float = MEMBERSHIP_LEASE_SECONDS) -> Lock:
    return get_redis_client(socket_timeout=2, socket_connect_timeout=2).lock(
        f"customer_analytics:membership_cleanup:{team_id}", timeout=timeout, blocking=False, thread_local=False
    )


@contextmanager
def renew_membership_cleanup_lease(
    lease: Lock, lease_seconds: float, deadline: float | None
) -> Iterator[Callable[[], None]]:
    stopped = Event()
    renewal_error: Exception | None = None

    def check_lease() -> None:
        if renewal_error is not None:
            raise renewal_error
        get_membership_query_settings(deadline)
        lease.extend(lease_seconds, replace_ttl=True)

    def renew() -> None:
        nonlocal renewal_error
        while not stopped.wait(MEMBERSHIP_LEASE_RENEWAL_SECONDS):
            try:
                check_lease()
            except Exception as error:
                renewal_error = error
                return

    thread = Thread(target=renew, daemon=True)
    thread.start()
    try:
        yield check_lease
    finally:
        stopped.set()
        thread.join()


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
        group_key = json.loads(f'"{group_key}"')
    except json.JSONDecodeError:
        pass
    return re.sub(r"[\ud800-\udfff\x00]", "\ufffd", group_key)


def _get_live_groups(
    team_id: int, keys: Sequence[MembershipKey], deadline: float | None = None, timings: MembershipTimings | None = None
) -> frozenset[tuple[int, str]]:
    # Membership keeps JSON escapes, but group identity storage uses decoded keys.
    lookup_keys: dict[tuple[int, str], tuple[int, str]] = {
        (key.group_type_index, key.group_key): (key.group_type_index, _parse_group_key(key.group_key)) for key in keys
    }
    lookup_keys = {stored: lookup for stored, lookup in lookup_keys.items() if len(lookup[1]) <= MAX_GROUP_KEY_LENGTH}
    if not lookup_keys:
        return frozenset()
    with timings.measure("read_groups") if timings else nullcontext():
        groups = sync_execute(
            """SELECT DISTINCT group_type_index, group_key FROM groups
        WHERE team_id = %(team_id)s AND (group_type_index, group_key) IN %(groups)s""",
            {"team_id": team_id, "groups": list(set(lookup_keys.values()))},
            settings=get_membership_query_settings(deadline),
            workload=Workload.OFFLINE,
        )
    live_groups = {(row[0], row[1]) for row in groups}
    missing_groups = set(lookup_keys.values()) - live_groups
    if missing_groups:
        with timings.measure("primary_groups") if timings else nullcontext():
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


def get_membership_existence(
    team_id: int, keys: Sequence[MembershipKey], deadline: float | None = None, timings: MembershipTimings | None = None
) -> MembershipExistence:
    if not keys:
        return MembershipExistence(persons=frozenset(), groups=frozenset())
    distinct_ids = {key.distinct_id for key in keys}
    parameters = {"team_id": team_id, "distinct_ids": list(distinct_ids)}
    with timings.measure("read_person_mappings") if timings else nullcontext():
        mappings = sync_execute(
            """SELECT distinct_id, argMax(tuple(person_id, is_deleted), version) AS mapping
        FROM person_distinct_id2
        WHERE team_id = %(team_id)s AND distinct_id IN %(distinct_ids)s
        GROUP BY distinct_id
        HAVING mapping.2 = 0""",
            parameters,
            settings=get_membership_query_settings(deadline),
            workload=Workload.OFFLINE,
        )
    person_ids = list({mapping[1][0] for mapping in mappings})
    with timings.measure("read_persons") if timings else nullcontext():
        persons = (
            sync_execute(
                """SELECT id FROM person WHERE team_id = %(team_id)s AND id IN %(person_ids)s
            GROUP BY id HAVING argMax(is_deleted, version) = 0""",
                {"team_id": team_id, "person_ids": person_ids},
                settings=get_membership_query_settings(deadline),
                workload=Workload.OFFLINE,
            )
            if person_ids
            else []
        )
    live_person_ids = {row[0] for row in persons}
    live_distinct_ids = {mapping[0] for mapping in mappings if mapping[1][0] in live_person_ids}
    missing_distinct_ids = distinct_ids - live_distinct_ids
    if missing_distinct_ids:
        with timings.measure("primary_persons") if timings else nullcontext():
            live_distinct_ids.update(
                row.distinct_id
                for row in get_distinct_id_rows(team_id, list(missing_distinct_ids), strong=True)
                if not row.is_deleted and row.HasField("person_is_deleted") and not row.person_is_deleted
            )
    return MembershipExistence(
        persons=frozenset(live_distinct_ids),
        groups=_get_live_groups(team_id, keys, deadline, timings),
    )
