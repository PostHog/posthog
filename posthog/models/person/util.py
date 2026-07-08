from __future__ import annotations

import json
import datetime
from typing import TYPE_CHECKING, Optional, Union
from uuid import UUID
from zoneinfo import ZoneInfo

from django.conf import settings
from django.utils.timezone import now

import structlog
from dateutil.parser import isoparse

from posthog.clickhouse.client import sync_execute
from posthog.kafka_client.client import ClickhouseProducer
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
    DeletePersonsRequest,
    GetDistinctIdsForPersonRequest,
    GetDistinctIdsForPersonsRequest,
    GetPersonByDistinctIdRequest,
    GetPersonByUuidRequest,
    GetPersonRequest,
    GetPersonsByDistinctIdsInTeamRequest,
    GetPersonsByUuidsRequest,
    ReadOptions,
)
from posthog.settings import TEST

logger = structlog.get_logger(__name__)

PERSONHOG_BATCH_SIZE: int = settings.PERSONHOG_BATCH_SIZE


if TYPE_CHECKING:
    from posthog.personhog_client.client import PersonHogClient
    from posthog.personhog_client.proto.generated.personhog.types.v1 import person_pb2


_get_client = require_personhog_client


def _batched_get_persons_by_uuids(
    team_id: int,
    uuids: list[str],
    operation: str,
) -> list[person_pb2.Person]:
    client = _get_client()
    valid_persons: list[person_pb2.Person] = []
    for i in range(0, len(uuids), PERSONHOG_BATCH_SIZE):
        batch = uuids[i : i + PERSONHOG_BATCH_SIZE]
        resp = client.get_persons_by_uuids(GetPersonsByUuidsRequest(team_id=team_id, uuids=batch))

        present_persons = [p for p in resp.persons if p.id]
        batch_valid = [p for p in present_persons if p.team_id == team_id]

        mismatched = len(present_persons) - len(batch_valid)
        if mismatched:
            PERSONHOG_TEAM_MISMATCH_TOTAL.labels(operation=operation, client_name=get_client_name()).inc(mismatched)
            logger.warning("personhog_team_mismatch", operation=operation, team_id=team_id, dropped=mismatched)

        valid_persons.extend(batch_valid)

    return valid_persons


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


def _batched_get_distinct_ids_for_persons(
    team_id: int,
    person_ids: list[int],
    limit_per_person: int | None = None,
) -> dict[int, list[str]]:
    client = _get_client()
    distinct_ids_by_person: dict[int, list[str]] = {}
    for i in range(0, len(person_ids), PERSONHOG_BATCH_SIZE):
        batch_ids = person_ids[i : i + PERSONHOG_BATCH_SIZE]
        did_request = GetDistinctIdsForPersonsRequest(team_id=team_id, person_ids=batch_ids)
        if limit_per_person is not None:
            did_request.limit_per_person = limit_per_person
        did_resp = client.get_distinct_ids_for_persons(did_request)
        for pd in did_resp.person_distinct_ids:
            distinct_ids_by_person[pd.person_id] = [d.distinct_id for d in pd.distinct_ids]
    return distinct_ids_by_person


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
    p = ClickhouseProducer()
    p.produce(topic=KAFKA_PERSON, sql=INSERT_PERSON_SQL, data=data)
    return uuid


def create_person_distinct_id(
    team_id: int,
    distinct_id: str,
    person_id: str,
    version=0,
    is_deleted: bool = False,
) -> None:
    p = ClickhouseProducer()
    p.produce(
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
    valid_results = _batched_get_persons_by_distinct_ids(team_id, distinct_ids, "get_persons_by_distinct_ids")

    person_ids = [r.person.id for r in valid_results]
    if not person_ids:
        return []

    distinct_ids_by_person = _batched_get_distinct_ids_for_persons(
        team_id, person_ids, limit_per_person=distinct_id_limit
    )

    return [
        proto_person_to_model(r.person, distinct_ids=distinct_ids_by_person.get(r.person.id, [])) for r in valid_results
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

    return personhog_call(
        "get_distinct_ids_for_persons",
        lambda: _batched_get_distinct_ids_for_persons(team_id, person_ids, limit_per_person=limit_per_person),
    )


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

    return [proto_person_to_model(p, distinct_ids=distinct_ids_by_person.get(p.id, [])) for p in valid_persons]


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


def _validate_uuids_via_personhog(team_id: int, uuids: list[str]) -> list[str]:
    # _batched_get_persons_by_uuids also filters out persons with id == 0 (server "not found" sentinel),
    # which the previous single-RPC implementation did not do. This is intentionally more correct.
    valid_persons = _batched_get_persons_by_uuids(team_id, uuids, "validate_person_uuids_exist")
    return [p.uuid for p in valid_persons]


def validate_person_uuids_exist(team_id: int, uuids: list[str]) -> list[str]:
    return personhog_call(
        "validate_person_uuids_exist",
        lambda: _validate_uuids_via_personhog(team_id, uuids),
    )


_UUID_ONLY_READ_OPTIONS = ReadOptions(field_mask=["uuid", "id", "team_id"])


def get_person_uuids_by_distinct_ids(team_id: int, distinct_ids: list[str]) -> list[str]:
    """Return person UUIDs for the given distinct IDs.

    Lightweight UUID-only variant — uses field masking to skip fetching
    properties and other heavy fields from personhog.
    """
    if not distinct_ids:
        return []

    def personhog_fn() -> list[str]:
        results = _batched_get_persons_by_distinct_ids(
            team_id,
            distinct_ids,
            "get_person_uuids_by_distinct_ids",
            read_options=_UUID_ONLY_READ_OPTIONS,
        )
        return [r.person.uuid for r in results]

    return personhog_call(
        "get_person_uuids_by_distinct_ids",
        personhog_fn,
    )


def delete_persons_from_postgres(team_id: int, persons: list[Person]) -> None:
    """Delete Person rows (and associated PersonDistinctId rows) via the personhog RPC.

    Processes in batches of 1000 (the RPC maximum).
    """

    def personhog_fn() -> None:
        uuids = [str(p.uuid) for p in persons]
        for i in range(0, len(uuids), 1000):
            batch = uuids[i : i + 1000]
            _get_client().delete_persons(DeletePersonsRequest(team_id=team_id, person_uuids=batch))

    personhog_call("delete_persons", personhog_fn)


def delete_person(person: Person) -> None:
    # This is racy https://github.com/PostHog/posthog/issues/11590
    distinct_ids_to_version = _get_distinct_ids_with_version(person)
    _delete_person(person.team_id, person.uuid, int(person.version or 0), person.created_at)
    for distinct_id, version in distinct_ids_to_version.items():
        _delete_ch_distinct_id(person.team_id, person.uuid, distinct_id, version)


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


def _get_distinct_ids_with_version(person: Person) -> dict[str, int]:
    def personhog_fn() -> dict[str, int]:
        resp = _get_client().get_distinct_ids_for_person(
            GetDistinctIdsForPersonRequest(team_id=person.team_id, person_id=person.pk)
        )
        return {d.distinct_id: int(d.version or 0) for d in resp.distinct_ids}

    return personhog_call("get_distinct_ids_with_version", personhog_fn)


def _delete_ch_distinct_id(team_id: int, uuid: UUID, distinct_id: str, version: int) -> None:
    create_person_distinct_id(
        team_id=team_id,
        distinct_id=distinct_id,
        person_id=str(uuid),
        version=version + 100,
        is_deleted=True,
    )
