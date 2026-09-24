from __future__ import annotations

import json
import time
import datetime
import contextvars
from collections.abc import Sequence
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Optional, Union
from uuid import UUID
from zoneinfo import ZoneInfo

from django.conf import settings
from django.utils.timezone import now

import structlog
from dateutil.parser import isoparse

from posthog.clickhouse.client import sync_execute
from posthog.dataclasses import frozen
from posthog.kafka_client.client import ClickhouseProducer, ProduceResult
from posthog.kafka_client.routing import get_producer
from posthog.kafka_client.topics import KAFKA_PERSON, KAFKA_PERSON_DISTINCT_ID
from posthog.models.person import Person
from posthog.models.person.sql import (
    BULK_INSERT_PERSON_DISTINCT_ID2,
    INSERT_PERSON_BULK_SQL,
    INSERT_PERSON_DISTINCT_ID2,
    INSERT_PERSON_SQL,
)
from posthog.models.utils import UUIDT
from posthog.personhog_client.client import personhog_call, require_personhog_client
from posthog.personhog_client.converters import proto_person_to_model
from posthog.personhog_client.metrics import PERSONHOG_TEAM_MISMATCH_TOTAL, get_client_name
from posthog.personhog_client.proto import (
    AckedPersonTombstone,
    AckPersonTombstonesRequest,
    DeletePersonsMode,
    DeletePersonsRequest,
    GetDistinctIdsForPersonRequest,
    GetDistinctIdsForPersonsRequest,
    GetPersonByDistinctIdRequest,
    GetPersonByUuidRequest,
    GetPersonRequest,
    GetPersonsByDistinctIdsInTeamRequest,
    GetPersonsByUuidsRequest,
    GetPersonTombstonesRequest,
    ListPersonTombstoneQueueRequest,
    ReadOptions,
)
from posthog.settings import TEST

logger = structlog.get_logger(__name__)

PERSONHOG_BATCH_SIZE: int = settings.PERSONHOG_BATCH_SIZE


if TYPE_CHECKING:
    from personhog.types.v1 import person_pb2

    from posthog.personhog_client.client import PersonHogClient


_get_client = require_personhog_client


def _get_persons_for_uuid_batch(
    client: PersonHogClient,
    team_id: int,
    batch: list[str],
    operation: str,
    read_options: ReadOptions | None,
) -> list[person_pb2.Person]:
    resp = client.get_persons_by_uuids(
        GetPersonsByUuidsRequest(team_id=team_id, uuids=batch, read_options=read_options)
    )

    present_persons = [p for p in resp.persons if p.id]
    batch_valid = [p for p in present_persons if p.team_id == team_id]

    mismatched = len(present_persons) - len(batch_valid)
    if mismatched:
        PERSONHOG_TEAM_MISMATCH_TOTAL.labels(operation=operation, client_name=get_client_name()).inc(mismatched)
        logger.warning("personhog_team_mismatch", operation=operation, team_id=team_id, dropped=mismatched)

    return batch_valid


def _batched_get_persons_by_uuids(
    team_id: int,
    uuids: list[str],
    operation: str,
    read_options: ReadOptions | None = None,
    concurrency: int = 1,
) -> list[person_pb2.Person]:
    """Fetch persons for the given UUIDs, one RPC per PERSONHOG_BATCH_SIZE batch.

    Sequential by default. Callers with large, latency-sensitive lookups opt into a
    concurrent fan-out by passing ``concurrency`` — opt-in so the many small/background
    callers of this helper don't multiply their load on the personhog bulk pools. Keep
    opted-in values modest: each in-flight RPC can occupy up to 2 connections of a
    replica's 5-connection bulk Postgres pool.
    """
    client = _get_client()
    batches = [uuids[i : i + PERSONHOG_BATCH_SIZE] for i in range(0, len(uuids), PERSONHOG_BATCH_SIZE)]
    max_workers = min(len(batches), concurrency)

    if TEST or max_workers <= 1:
        batch_results = [
            _get_persons_for_uuid_batch(client, team_id, batch, operation, read_options) for batch in batches
        ]
    else:
        # Fan the batch RPCs out over the shared (HTTP/2-multiplexed) channel. ThreadPoolExecutor
        # doesn't inherit contextvars, so copy the current context per task to keep the personhog
        # caller tag and log/query context on each RPC. Results are collected in batch order, and
        # any batch failure propagates: callers (e.g. the freeze-exposure guard) rely on the result
        # covering every requested batch, never a silently partial set.
        with ThreadPoolExecutor(max_workers=max_workers, thread_name_prefix="personhog-uuid-batch") as executor:
            futures = [
                executor.submit(
                    contextvars.copy_context().run,
                    _get_persons_for_uuid_batch,
                    client,
                    team_id,
                    batch,
                    operation,
                    read_options,
                )
                for batch in batches
            ]
            batch_results = [future.result() for future in futures]

    return [person for batch_valid in batch_results for person in batch_valid]


def _batched_get_persons_by_distinct_ids(
    team_id: int,
    distinct_ids: list[str],
    operation: str,
    deduplicate_by_person: bool = True,
    read_options: ReadOptions | None = None,
) -> list[person_pb2.PersonWithDistinctIds]:
    client = _get_client()
    seen_person_ids: set[int] = set()
    valid_results: list[person_pb2.PersonWithDistinctIds] = []

    for i in range(0, len(distinct_ids), PERSONHOG_BATCH_SIZE):
        batch = distinct_ids[i : i + PERSONHOG_BATCH_SIZE]
        resp = client.get_persons_by_distinct_ids_in_team(
            GetPersonsByDistinctIdsInTeamRequest(team_id=team_id, distinct_ids=batch, read_options=read_options)
        )

        present_results = [r for r in resp.results if r.person and r.person.id]
        batch_valid = [r for r in present_results if r.person.team_id == team_id]

        mismatched = len(present_results) - len(batch_valid)
        if mismatched:
            PERSONHOG_TEAM_MISMATCH_TOTAL.labels(operation=operation, client_name=get_client_name()).inc(mismatched)
            logger.warning("personhog_team_mismatch", operation=operation, team_id=team_id, dropped=mismatched)

        if deduplicate_by_person:
            for r in batch_valid:
                if r.person.id not in seen_person_ids:
                    seen_person_ids.add(r.person.id)
                    valid_results.append(r)
        else:
            valid_results.extend(batch_valid)

    return valid_results


@dataclass
class DistinctIdForPerson:
    id: str
    version: int


def _batched_get_distinct_ids_for_persons(
    team_id: int,
    person_ids: list[int],
    limit_per_person: int | None = None,
) -> dict[int, list[DistinctIdForPerson]]:
    """Fetch each person's distinct_ids with their versions, one RPC per PERSONHOG_BATCH_SIZE batch."""
    client = _get_client()
    distinct_ids_by_person: dict[int, list[DistinctIdForPerson]] = {}
    for i in range(0, len(person_ids), PERSONHOG_BATCH_SIZE):
        batch_ids = person_ids[i : i + PERSONHOG_BATCH_SIZE]
        did_request = GetDistinctIdsForPersonsRequest(team_id=team_id, person_ids=batch_ids)
        if limit_per_person is not None:
            did_request.limit_per_person = limit_per_person
        did_resp = client.get_distinct_ids_for_persons(did_request)
        for pd in did_resp.person_distinct_ids:
            distinct_ids_by_person[pd.person_id] = [
                DistinctIdForPerson(id=d.distinct_id, version=int(d.version or 0)) for d in pd.distinct_ids
            ]
    return distinct_ids_by_person


def _paginated_get_distinct_ids_for_person(
    team_id: int,
    person_id: int,
    page_size: int = 5000,
) -> list[DistinctIdForPerson]:
    """Fetch all distinct IDs for a single person using keyset pagination."""
    client = _get_client()
    all_dids: list[DistinctIdForPerson] = []
    cursor_id: int = 0

    while True:
        request = GetDistinctIdsForPersonRequest(
            team_id=team_id,
            person_id=person_id,
            limit=page_size,
            cursor_id=cursor_id,
        )

        resp = client.get_distinct_ids_for_person(request)
        for d in resp.distinct_ids:
            all_dids.append(DistinctIdForPerson(id=d.distinct_id, version=int(d.version or 0)))

        if not resp.HasField("next_cursor_id"):
            break
        cursor_id = resp.next_cursor_id

    return all_dids


if TEST:

    def bulk_create_persons(persons_list: list[dict]):
        """Bulk-create persons in ClickHouse and return the distinct_id → Person mapping.

        Test-only.  Builds in-memory Person instances with synthetic primary keys
        and uuids (no persons DB write) and inserts the rows into ClickHouse.  The
        personhog fake is seeded by the caller (posthog.test.persons).
        """
        from posthog.test.persons import _next_synthetic_pk  # noqa: PLC0415

        person_mapping: dict[str, Person] = {}
        staged: list[tuple[Person, list]] = []
        for _person in persons_list:
            person = Person(**{key: value for key, value in _person.items() if key != "distinct_ids"})
            person.id = _next_synthetic_pk()
            if not person.uuid:
                person.uuid = UUIDT()
            person.created_at = person.created_at or now()
            person.version = person.version or 0
            person._state.adding = False
            staged.append((person, _person["distinct_ids"]))

        person_inserts = []
        distinct_id_inserts = []
        for person, person_distinct_ids in staged:
            for distinct_id in person_distinct_ids:
                distinct_id_inserts.append(f"('{distinct_id}', '{person.uuid}', {person.team_id}, 0, 0, now(), 0, 0)")
                person_mapping[distinct_id] = person

            dt = now()
            created_at = dt.strftime("%Y-%m-%d %H:%M:%S.%f")
            timestamp = dt.strftime("%Y-%m-%d %H:%M:%S")
            # Round to the hour for last_seen_at
            last_seen_at = dt.replace(minute=0, second=0, microsecond=0).strftime("%Y-%m-%d %H:%M:%S.%f")
            person_inserts.append(
                f"('{person.uuid}', '{created_at}', {person.team_id}, '{json.dumps(person.properties)}', {'1' if person.is_identified else '0'}, '{timestamp}', 0, 0, 0, '{last_seen_at}')"
            )

        sync_execute(INSERT_PERSON_BULK_SQL + ", ".join(person_inserts), flush=False)
        sync_execute(
            BULK_INSERT_PERSON_DISTINCT_ID2 + ", ".join(distinct_id_inserts),
            flush=False,
        )

        return person_mapping


def create_person(
    *,
    team_id: int,
    version: int,
    uuid: Optional[str] = None,
    properties: Optional[dict] = None,
    is_identified: bool = False,
    is_deleted: bool = False,
    timestamp: Optional[Union[datetime.datetime, str]] = None,
    created_at: Optional[datetime.datetime] = None,
    last_seen_at: Optional[datetime.datetime] = None,
) -> str:
    data = _person_row(
        team_id=team_id,
        version=version,
        uuid=uuid,
        properties=properties,
        is_identified=is_identified,
        is_deleted=is_deleted,
        timestamp=timestamp,
        created_at=created_at,
        last_seen_at=last_seen_at,
    )
    ClickhouseProducer().produce(topic=KAFKA_PERSON, sql=INSERT_PERSON_SQL, data=data)
    return data["id"]


def _person_row(
    *,
    team_id: int,
    version: int,
    uuid: Optional[str] = None,
    properties: Optional[dict] = None,
    is_identified: bool = False,
    is_deleted: bool = False,
    timestamp: Optional[Union[datetime.datetime, str]] = None,
    created_at: Optional[datetime.datetime] = None,
    last_seen_at: Optional[datetime.datetime] = None,
) -> dict[str, Any]:
    if properties is None:
        properties = {}
    if uuid:
        uuid = str(uuid)
    else:
        uuid = str(UUIDT())
    if not timestamp:
        timestamp = now()

    # clickhouse specific formatting
    if isinstance(timestamp, str):
        timestamp = isoparse(timestamp)
    else:
        timestamp = timestamp.astimezone(ZoneInfo("UTC"))

    if created_at is None:
        created_at = timestamp
    else:
        created_at = created_at.astimezone(ZoneInfo("UTC"))

    # Default last_seen_at to timestamp rounded down to the hour
    if last_seen_at is None:
        last_seen_at = timestamp.replace(minute=0, second=0, microsecond=0)
    else:
        last_seen_at = last_seen_at.astimezone(ZoneInfo("UTC"))
    last_seen_at_formatted = last_seen_at.strftime("%Y-%m-%d %H:%M:%S.%f")

    data = {
        "id": str(uuid),
        "team_id": team_id,
        "properties": json.dumps(properties),
        "is_identified": int(is_identified),
        "is_deleted": int(is_deleted),
        "created_at": created_at.strftime("%Y-%m-%d %H:%M:%S.%f"),
        "version": version,
        "_timestamp": timestamp.strftime("%Y-%m-%d %H:%M:%S"),
        "last_seen_at": last_seen_at_formatted,
    }
    return data


def create_person_distinct_id(
    team_id: int,
    distinct_id: str,
    person_id: str,
    version=0,
    is_deleted: bool = False,
) -> ProduceResult:
    return ClickhouseProducer().produce(
        topic=KAFKA_PERSON_DISTINCT_ID,
        sql=INSERT_PERSON_DISTINCT_ID2,
        data={
            "distinct_id": distinct_id,
            "person_id": person_id,
            "team_id": team_id,
            "version": version,
            "is_deleted": int(is_deleted),
        },
    )


def _fetch_persons_by_distinct_ids_via_personhog(
    team_id: int, distinct_ids: list[str], *, distinct_id_limit: int | None = None
) -> list[Person]:
    # distinct_id_limit=0 skips the per-person distinct-id fetch, like the UUID variant. Each person
    # then carries only the requested distinct IDs that resolved to it, which the lookup RPC already
    # returns, so a caller can tell which requested IDs matched no person at all.
    if distinct_id_limit == 0:
        matched_results = _batched_get_persons_by_distinct_ids(
            team_id, distinct_ids, "get_persons_by_distinct_ids", deduplicate_by_person=False
        )
        matched_by_person: dict[int, list[str]] = {}
        person_by_id: dict[int, person_pb2.Person] = {}
        for r in matched_results:
            person_by_id.setdefault(r.person.id, r.person)
            matched_by_person.setdefault(r.person.id, []).append(r.distinct_id)
        return [
            proto_person_to_model(person, distinct_ids=matched_by_person[person_id])
            for person_id, person in person_by_id.items()
        ]

    valid_results = _batched_get_persons_by_distinct_ids(team_id, distinct_ids, "get_persons_by_distinct_ids")

    person_ids = [r.person.id for r in valid_results]
    if not person_ids:
        return []

    distinct_ids_by_person = _batched_get_distinct_ids_for_persons(
        team_id, person_ids, limit_per_person=distinct_id_limit
    )

    return [
        proto_person_to_model(r.person, distinct_ids=[d.id for d in distinct_ids_by_person.get(r.person.id, [])])
        for r in valid_results
    ]


def get_persons_by_distinct_ids(
    team_id: int,
    distinct_ids: list[str],
    *,
    operation: str = "get_persons_by_distinct_ids",
    distinct_id_limit: int | None = None,
) -> list[Person]:
    return personhog_call(
        operation,
        lambda: _fetch_persons_by_distinct_ids_via_personhog(
            team_id, distinct_ids, distinct_id_limit=distinct_id_limit
        ),
    )


def get_persons_mapped_by_distinct_id(
    team_id: int,
    distinct_ids: list[str],
) -> dict[str, Person]:
    """Look up persons by distinct_ids and return a direct distinct_id → Person mapping.

    Optimized for callers that need a mapping keyed by distinct_id and only
    need the single matched distinct_id on each Person (e.g. session recordings).
    Unlike ``get_persons_by_distinct_ids``, this avoids fetching all distinct_ids
    for each person — a single GetPersonsByDistinctIdsInTeam RPC already carries
    the matched distinct_id.
    """

    def personhog_fn() -> dict[str, Person]:
        valid_results = _batched_get_persons_by_distinct_ids(
            team_id, distinct_ids, "get_persons_mapped_by_distinct_id", deduplicate_by_person=False
        )
        return {r.distinct_id: proto_person_to_model(r.person, distinct_ids=[r.distinct_id]) for r in valid_results}

    return personhog_call(
        "get_persons_mapped_by_distinct_id",
        personhog_fn,
    )


def get_distinct_ids_for_persons(
    team_id: int,
    person_ids: list[int],
    *,
    limit_per_person: int | None = None,
) -> dict[int, list[str]]:
    """Map each person_id to its distinct_ids via personhog.

    With ``limit_per_person`` set, at most that many distinct_ids are returned per
    person — bounding the fetch for merge-heavy persons whose full set can be huge.
    """
    if not person_ids:
        return {}

    distinct_ids_by_person = personhog_call(
        "get_distinct_ids_for_persons",
        lambda: _batched_get_distinct_ids_for_persons(team_id, person_ids, limit_per_person=limit_per_person),
    )
    return {person_id: [d.id for d in distinct_ids] for person_id, distinct_ids in distinct_ids_by_person.items()}


def _fetch_persons_by_uuids_via_personhog(
    team_id: int, uuids: list[str], *, distinct_id_limit: int | None = None
) -> list[Person]:
    valid_persons = _batched_get_persons_by_uuids(team_id, uuids, "get_persons_by_uuids")

    person_ids = [p.id for p in valid_persons]
    if not person_ids:
        return []

    # Callers needing only id/uuid (e.g. cohort membership) pass distinct_id_limit=0 to skip
    # the per-person distinct-id fetch, which is otherwise unbounded and pulls thousands of
    # rows for merge-heavy persons.
    if distinct_id_limit == 0:
        return [proto_person_to_model(p, distinct_ids=[]) for p in valid_persons]

    distinct_ids_by_person = _batched_get_distinct_ids_for_persons(
        team_id, person_ids, limit_per_person=distinct_id_limit
    )

    return [
        proto_person_to_model(p, distinct_ids=[d.id for d in distinct_ids_by_person.get(p.id, [])])
        for p in valid_persons
    ]


def get_persons_by_uuids(team_id: int, uuids: list[str], *, distinct_id_limit: int | None = None) -> list[Person]:
    return personhog_call(
        "get_persons_by_uuids",
        lambda: _fetch_persons_by_uuids_via_personhog(team_id, uuids, distinct_id_limit=distinct_id_limit),
    )


def _distinct_ids_for_person(client: PersonHogClient, team_id: int, person_id: int, limit: int | None) -> list[str]:
    # Callers needing only person fields (not distinct_ids) pass distinct_id_limit=0 to skip the
    # per-person distinct-id fetch, which is otherwise unbounded and pulls thousands of rows for
    # merge-heavy persons. A positive limit bounds the fetch; None leaves it unbounded.
    if limit == 0:
        return []
    request = GetDistinctIdsForPersonRequest(team_id=team_id, person_id=person_id)
    if limit is not None:
        request.limit = limit
    resp = client.get_distinct_ids_for_person(request)
    return [d.distinct_id for d in resp.distinct_ids]


def _fetch_person_by_id_via_personhog(
    team_id: int, person_id: int, *, distinct_id_limit: int | None = None
) -> Optional[Person]:
    client = _get_client()

    resp = client.get_person(GetPersonRequest(team_id=team_id, person_id=person_id))

    if not resp.person or not resp.person.id:
        return None

    if resp.person.team_id != team_id:
        PERSONHOG_TEAM_MISMATCH_TOTAL.labels(operation="get_person_by_id", client_name=get_client_name()).inc()
        logger.warning("personhog_team_mismatch", operation="get_person_by_id", team_id=team_id)
        return None

    distinct_ids = _distinct_ids_for_person(client, team_id, resp.person.id, distinct_id_limit)
    return proto_person_to_model(resp.person, distinct_ids=distinct_ids)


def get_person_by_id(team_id: int, person_id: int, *, distinct_id_limit: int | None = None) -> Optional[Person]:
    return personhog_call(
        "get_person_by_id",
        lambda: _fetch_person_by_id_via_personhog(team_id, person_id, distinct_id_limit=distinct_id_limit),
    )


def _fetch_person_by_uuid_via_personhog(
    team_id: int, uuid: str, *, distinct_id_limit: int | None = None
) -> Optional[Person]:
    client = _get_client()

    resp = client.get_person_by_uuid(GetPersonByUuidRequest(team_id=team_id, uuid=uuid))

    if not resp.person or not resp.person.id:
        return None

    if resp.person.team_id != team_id:
        PERSONHOG_TEAM_MISMATCH_TOTAL.labels(operation="get_person_by_uuid", client_name=get_client_name()).inc()
        logger.warning("personhog_team_mismatch", operation="get_person_by_uuid", team_id=team_id)
        return None

    distinct_ids = _distinct_ids_for_person(client, team_id, resp.person.id, distinct_id_limit)
    return proto_person_to_model(resp.person, distinct_ids=distinct_ids)


def get_person_by_uuid(team_id: int, uuid: str, *, distinct_id_limit: int | None = None) -> Optional[Person]:
    return personhog_call(
        "get_person_by_uuid",
        lambda: _fetch_person_by_uuid_via_personhog(team_id, uuid, distinct_id_limit=distinct_id_limit),
    )


def _fetch_person_by_distinct_id_via_personhog(
    team_id: int, distinct_id: str, *, distinct_id_limit: int | None = None
) -> Optional[Person]:
    client = _get_client()

    resp = client.get_person_by_distinct_id(GetPersonByDistinctIdRequest(team_id=team_id, distinct_id=distinct_id))

    if not resp.person or not resp.person.id:
        return None

    if resp.person.team_id != team_id:
        PERSONHOG_TEAM_MISMATCH_TOTAL.labels(operation="get_person_by_distinct_id", client_name=get_client_name()).inc()
        logger.warning("personhog_team_mismatch", operation="get_person_by_distinct_id", team_id=team_id)
        return None

    distinct_ids = _distinct_ids_for_person(client, team_id, resp.person.id, distinct_id_limit)
    return proto_person_to_model(resp.person, distinct_ids=distinct_ids)


def get_person_by_distinct_id(
    team_id: int, distinct_id: str, *, distinct_id_limit: int | None = None
) -> Optional[Person]:
    return personhog_call(
        "get_person_by_distinct_id",
        lambda: _fetch_person_by_distinct_id_via_personhog(team_id, distinct_id, distinct_id_limit=distinct_id_limit),
    )


def get_person_by_pk_or_uuid(team_id: int, key: str, *, distinct_id_limit: int | None = None) -> Optional[Person]:
    """Look up a person by UUID or integer PK, routing through personhog when enabled."""
    try:
        UUID(key)
        return get_person_by_uuid(team_id, key, distinct_id_limit=distinct_id_limit)
    except ValueError:
        try:
            return get_person_by_id(team_id, int(key), distinct_id_limit=distinct_id_limit)
        except ValueError:
            return None


_UUID_ONLY_READ_OPTIONS = ReadOptions(field_mask=["uuid", "id", "team_id"])


def _validate_uuids_via_personhog(team_id: int, uuids: list[str]) -> list[str]:
    # _batched_get_persons_by_uuids also filters out persons with id == 0 (server "not found" sentinel),
    # which the previous single-RPC implementation did not do. This is intentionally more correct.
    # Existence only needs uuid/id/team_id — the field mask keeps (potentially huge) person
    # properties out of the RPC payloads.
    valid_persons = _batched_get_persons_by_uuids(
        team_id, uuids, "validate_person_uuids_exist", read_options=_UUID_ONLY_READ_OPTIONS
    )
    return [p.uuid for p in valid_persons]


def validate_person_uuids_exist(team_id: int, uuids: list[str]) -> list[str]:
    return personhog_call(
        "validate_person_uuids_exist",
        lambda: _validate_uuids_via_personhog(team_id, uuids),
    )


def get_person_ids_and_uuids_by_uuids(team_id: int, uuids: list[str], *, concurrency: int = 1) -> list[tuple[int, str]]:
    """Return (person_id, person_uuid) pairs for the given person UUIDs; unknown UUIDs are omitted.

    Lightweight variant of ``get_persons_by_uuids`` — uses field masking to skip fetching
    properties and other heavy fields, and never fetches distinct IDs. For callers that only
    need to resolve UUIDs to person IDs (e.g. cohort membership writes). ``concurrency``
    opts into the concurrent batch fan-out — see ``_batched_get_persons_by_uuids``.
    """
    if not uuids:
        return []

    def personhog_fn() -> list[tuple[int, str]]:
        persons = _batched_get_persons_by_uuids(
            team_id,
            uuids,
            "get_person_ids_and_uuids_by_uuids",
            read_options=_UUID_ONLY_READ_OPTIONS,
            concurrency=concurrency,
        )
        return [(p.id, p.uuid) for p in persons]

    return personhog_call(
        "get_person_ids_and_uuids_by_uuids",
        personhog_fn,
    )


def get_person_uuids_by_distinct_ids(team_id: int, distinct_ids: list[str]) -> list[str]:
    """Return person UUIDs for the given distinct IDs.

    Lightweight UUID-only variant — uses field masking to skip fetching
    properties and other heavy fields from personhog.
    """
    uuids, _ = get_person_uuids_and_matched_distinct_ids(team_id, distinct_ids)
    return uuids


def get_person_uuids_and_matched_distinct_ids(team_id: int, distinct_ids: list[str]) -> tuple[list[str], set[str]]:
    """Return person UUIDs for the given distinct IDs, plus the distinct IDs that resolved.

    The second element lets callers tell "this distinct ID has no person row" apart from
    "several distinct IDs collapsed onto one person", which a bare UUID list can't express.

    Lightweight UUID-only variant — uses field masking to skip fetching
    properties and other heavy fields from personhog.
    """
    if not distinct_ids:
        return [], set()

    def personhog_fn() -> tuple[list[str], set[str]]:
        results = _batched_get_persons_by_distinct_ids(
            team_id,
            distinct_ids,
            "get_person_uuids_by_distinct_ids",
            # Keep every match so the caller sees which distinct IDs resolved; dedupe by person below.
            deduplicate_by_person=False,
            read_options=_UUID_ONLY_READ_OPTIONS,
        )
        matched: set[str] = set()
        seen_person_ids: set[int] = set()
        uuids: list[str] = []
        for r in results:
            matched.add(r.distinct_id)
            if r.person.id not in seen_person_ids:
                seen_person_ids.add(r.person.id)
                uuids.append(r.person.uuid)
        return uuids, matched

    return personhog_call(
        "get_person_uuids_by_distinct_ids",
        personhog_fn,
    )


def delete_persons_from_postgres(team_id: int, persons: list[Person]) -> None:
    """Remove Person rows (and associated PersonDistinctId rows) via the personhog RPC.

    Processes in batches of 1000 (the RPC maximum). Asks for a hard delete explicitly: the
    caller has already published ClickHouse tombstones at version + 100, so the replica's own
    default must not turn this into a tombstone.
    """

    def personhog_fn() -> None:
        uuids = [str(p.uuid) for p in persons]
        for i in range(0, len(uuids), 1000):
            batch = uuids[i : i + 1000]
            _get_client().delete_persons(
                DeletePersonsRequest(
                    team_id=team_id, person_uuids=batch, mode=DeletePersonsMode.DELETE_PERSONS_MODE_HARD
                )
            )

    personhog_call("delete_persons", personhog_fn)


@frozen
class PersonTombstone:
    """The versions the replica wrote when it tombstoned one person."""

    uuid: UUID
    version: int
    distinct_ids: list[DistinctIdForPerson]


def _to_tombstone(t: person_pb2.TombstonedPerson) -> PersonTombstone:
    return PersonTombstone(
        uuid=UUID(t.person_uuid),
        version=int(t.version),
        distinct_ids=[DistinctIdForPerson(id=d.distinct_id, version=int(d.version)) for d in t.distinct_ids],
    )


def tombstone_persons_in_postgres(team_id: int, person_uuids: list[UUID]) -> list[PersonTombstone]:
    """Tombstone Person rows via the personhog RPC and return the versions it wrote.

    Batches of 1000, the RPC maximum. An already tombstoned person comes back with the
    versions it holds; one that no longer exists comes back with nothing.
    """

    def personhog_fn() -> list[PersonTombstone]:
        tombstones: list[PersonTombstone] = []
        uuids = [str(u) for u in person_uuids]
        for i in range(0, len(uuids), 1000):
            batch = uuids[i : i + 1000]
            response = _get_client().delete_persons(
                DeletePersonsRequest(
                    team_id=team_id, person_uuids=batch, mode=DeletePersonsMode.DELETE_PERSONS_MODE_TOMBSTONE
                )
            )
            tombstones.extend(_to_tombstone(t) for t in response.tombstones)
        return tombstones

    return personhog_call("tombstone_persons", personhog_fn)


@frozen
class QueuedPersonTombstone:
    team_id: int
    person_uuid: UUID
    person_version: int
    tombstoned_at_ms: int


def get_person_tombstones(team_id: int, person_uuids: list[UUID]) -> list[PersonTombstone]:
    def personhog_fn() -> list[PersonTombstone]:
        tombstones: list[PersonTombstone] = []
        uuids = [str(u) for u in person_uuids]
        for i in range(0, len(uuids), 1000):
            response = _get_client().get_person_tombstones(
                GetPersonTombstonesRequest(team_id=team_id, person_uuids=uuids[i : i + 1000])
            )
            tombstones.extend(_to_tombstone(t) for t in response.tombstones)
        return tombstones

    return personhog_call("get_person_tombstones", personhog_fn)


def list_person_tombstone_queue(
    after: tuple[int, UUID] | None, limit: int, team_id: int | None = None
) -> list[QueuedPersonTombstone]:
    def personhog_fn() -> list[QueuedPersonTombstone]:
        request = ListPersonTombstoneQueueRequest(
            after_team_id=after[0] if after else 0,
            after_person_uuid=str(after[1]) if after else "",
            limit=limit,
        )
        if team_id is not None:
            request.team_id = team_id
        response = _get_client().list_person_tombstone_queue(request)
        return [
            QueuedPersonTombstone(
                team_id=int(e.team_id),
                person_uuid=UUID(e.person_uuid),
                person_version=int(e.person_version),
                tombstoned_at_ms=int(e.tombstoned_at),
            )
            for e in response.entries
        ]

    return personhog_call("list_person_tombstone_queue", personhog_fn)


def ack_person_tombstones(team_id: int, acked: list[tuple[UUID, int]]) -> int:
    def personhog_fn() -> int:
        cleared = 0
        for i in range(0, len(acked), 1000):
            response = _get_client().ack_person_tombstones(
                AckPersonTombstonesRequest(
                    team_id=team_id,
                    tombstones=[
                        AckedPersonTombstone(person_uuid=str(uuid), version=version)
                        for uuid, version in acked[i : i + 1000]
                    ],
                )
            )
            cleared += int(response.cleared_count)
        return cleared

    return personhog_call("ack_person_tombstones", personhog_fn)


def publish_person_tombstone(
    team_id: int, tombstone: PersonTombstone, created_at: Optional[datetime.datetime] = None
) -> list[ProduceResult]:
    """Produce ClickHouse deletion rows at exactly the versions the Postgres tombstone holds.

    The rows outrank every earlier update of the person, and a revival at the next version
    outranks them in turn, which is what makes the version + 100 offset unnecessary.
    """
    person_row = _person_row(
        team_id=team_id, version=tombstone.version, uuid=str(tombstone.uuid), created_at=created_at, is_deleted=True
    )
    results = [ClickhouseProducer().produce(topic=KAFKA_PERSON, sql=INSERT_PERSON_SQL, data=person_row)]
    for distinct_id in tombstone.distinct_ids:
        results.append(
            create_person_distinct_id(
                team_id=team_id,
                distinct_id=distinct_id.id,
                person_id=str(tombstone.uuid),
                version=distinct_id.version,
                is_deleted=True,
            )
        )
    return results


TOMBSTONE_DELIVERY_TIMEOUT_SECONDS = 10


@frozen
class PersonTombstonePublishFailure:
    person_uuid: UUID
    error: Exception


@frozen(frozen=False)
class PersonTombstonePublication:
    """ClickHouse tombstone rows produced for one team, waiting for delivery and the queue ack.

    ``publish`` produces the rows for a batch of tombstones and returns without waiting.
    ``await_and_ack`` waits once for Kafka to deliver everything produced so far, then acks
    the delivered persons off the tombstone queue. Publish every batch first and wait once,
    so a request pays the delivery timeout once instead of once per batch.

    A person that fails to produce or deliver is reported in ``failures`` and stays queued for
    the weekly sweep. A failed ack is only logged, because the sweep republishes those rows too.
    """

    team_id: int
    failures: list[PersonTombstonePublishFailure] = field(default_factory=list)
    _pending: list[tuple[PersonTombstone, list[ProduceResult]]] = field(default_factory=list, init=False, repr=False)

    def publish(self, tombstones: Sequence[tuple[PersonTombstone, Optional[datetime.datetime]]]) -> None:
        for tombstone, created_at in tombstones:
            try:
                results = publish_person_tombstone(self.team_id, tombstone, created_at=created_at)
            except Exception as exc:
                self.failures.append(PersonTombstonePublishFailure(person_uuid=tombstone.uuid, error=exc))
                continue
            self._pending.append((tombstone, results))

    def await_and_ack(self) -> None:
        pending, self._pending = self._pending, []
        if not pending:
            return

        if not all(result.done() for _, results in pending for result in results):
            _flush_person_producers(TOMBSTONE_DELIVERY_TIMEOUT_SECONDS)

        delivered: list[tuple[UUID, int]] = []
        for tombstone, results in pending:
            try:
                for result in results:
                    result.get(timeout=0)
            except Exception as exc:
                self.failures.append(PersonTombstonePublishFailure(person_uuid=tombstone.uuid, error=exc))
                continue
            delivered.append((tombstone.uuid, tombstone.version))
        if not delivered:
            return
        try:
            ack_person_tombstones(self.team_id, delivered)
        except Exception:
            logger.warning(
                "person_tombstones.ack_failed", team_id=self.team_id, person_count=len(delivered), exc_info=True
            )


def _flush_person_producers(timeout: float) -> None:
    """Flush each producer behind the person topics once, within one shared deadline.

    Both topics normally route to the same producer. Flushing it once per topic would wait
    for the full timeout twice while the brokers are unreachable.
    """
    deadline = time.monotonic() + timeout
    producers = {id(p): p for p in (get_producer(topic=KAFKA_PERSON), get_producer(topic=KAFKA_PERSON_DISTINCT_ID))}
    for producer in producers.values():
        producer.flush(max(0.0, deadline - time.monotonic()))


def delete_person(person: Person, distinct_ids: list[DistinctIdForPerson] | None = None) -> None:
    """Produce ClickHouse deletion tombstones for a person and its distinct_ids.

    ``distinct_ids`` can be prefetched in batch (see ``delete_persons_profile``) to
    avoid one RPC per person; when omitted it is fetched here.
    """
    # This is racy https://github.com/PostHog/posthog/issues/11590
    if distinct_ids is None:
        distinct_ids = _get_distinct_ids_with_version(person)
    _delete_person(person.team_id, person.uuid, int(person.version or 0), person.created_at)
    for distinct_id in distinct_ids:
        _delete_ch_distinct_id(person.team_id, person.uuid, distinct_id.id, distinct_id.version)


def _delete_person(
    team_id: int,
    uuid: UUID,
    version: int,
    created_at: Optional[datetime.datetime] = None,
) -> None:
    create_person(
        uuid=str(uuid),
        team_id=team_id,
        # Version + 100 ensures delete takes precedence over normal updates.
        # Keep in sync with:
        # - plugin-server/src/utils/db/utils.ts:152 (generateKafkaPersonUpdateMessage)
        # - posthog/models/person/person.py:112 (split_person uses version + 101 to override deletes)
        version=version + 100,
        created_at=created_at,
        is_deleted=True,
    )


def _get_distinct_ids_with_version(person: Person) -> list[DistinctIdForPerson]:
    def personhog_fn() -> list[DistinctIdForPerson]:
        resp = _get_client().get_distinct_ids_for_person(
            GetDistinctIdsForPersonRequest(team_id=person.team_id, person_id=person.pk)
        )
        return [DistinctIdForPerson(id=d.distinct_id, version=int(d.version or 0)) for d in resp.distinct_ids]

    return personhog_call("get_distinct_ids_with_version", personhog_fn)


def _delete_ch_distinct_id(team_id: int, uuid: UUID, distinct_id: str, version: int) -> None:
    create_person_distinct_id(
        team_id=team_id,
        distinct_id=distinct_id,
        person_id=str(uuid),
        version=version + 100,
        is_deleted=True,
    )
