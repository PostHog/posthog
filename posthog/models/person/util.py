import json
import datetime
from collections.abc import Callable
from contextlib import ExitStack
from typing import Optional, TypeVar, Union, cast
from uuid import UUID
from zoneinfo import ZoneInfo

from django.db.models.query import Prefetch, QuerySet
from django.db.models.signals import post_delete, post_save
from django.dispatch import receiver
from django.utils.timezone import now

import structlog
from dateutil.parser import isoparse

from posthog.clickhouse.client import sync_execute
from posthog.kafka_client.client import ClickhouseProducer
from posthog.kafka_client.topics import KAFKA_PERSON, KAFKA_PERSON_DISTINCT_ID
from posthog.models.person import Person, PersonDistinctId
from posthog.models.person.person import READ_DB_FOR_PERSONS
from posthog.models.person.sql import (
    BULK_INSERT_PERSON_DISTINCT_ID2,
    INSERT_PERSON_BULK_SQL,
    INSERT_PERSON_DISTINCT_ID2,
    INSERT_PERSON_SQL,
)
from posthog.models.signals import mutable_receiver
from posthog.models.team import Team
from posthog.models.utils import UUIDT
from posthog.personhog_client.converters import proto_person_to_model
from posthog.personhog_client.metrics import (
    PERSONHOG_ROUTING_ERRORS_TOTAL,
    PERSONHOG_ROUTING_TOTAL,
    PERSONHOG_TEAM_MISMATCH_TOTAL,
    get_client_name,
)
from posthog.personhog_client.proto import (
    DeletePersonsRequest,
    GetDistinctIdsForPersonRequest,
    GetDistinctIdsForPersonsRequest,
    GetPersonByDistinctIdRequest,
    GetPersonByUuidRequest,
    GetPersonRequest,
    GetPersonsByDistinctIdsInTeamRequest,
    GetPersonsByUuidsRequest,
)
from posthog.settings import TEST

logger = structlog.get_logger(__name__)

if TEST:
    # :KLUDGE: Hooks are kept around for tests. All other code goes through plugin-server or the other methods explicitly

    @mutable_receiver(post_save, sender=Person)
    def person_created(sender, instance: Person, created, **kwargs):
        create_person(
            team_id=instance.team_id,
            properties=instance.properties,
            uuid=str(instance.uuid),
            is_identified=instance.is_identified,
            version=instance.version or 0,
            sync=True,
        )

    @mutable_receiver(post_save, sender=PersonDistinctId)
    def person_distinct_id_created(sender, instance: PersonDistinctId, created, **kwargs):
        create_person_distinct_id(
            instance.team_id,
            instance.distinct_id,
            str(instance.person.uuid),
            version=instance.version or 0,
            sync=True,
        )

    @receiver(post_delete, sender=Person)
    def person_deleted(sender, instance: Person, **kwargs):
        _delete_person(
            instance.team_id,
            instance.uuid,
            int(instance.version or 0),
            instance.created_at,
            sync=True,
        )

    @receiver(post_delete, sender=PersonDistinctId)
    def person_distinct_id_deleted(sender, instance: PersonDistinctId, **kwargs):
        _delete_ch_distinct_id(
            instance.team_id,
            instance.person.uuid,
            instance.distinct_id,
            instance.version or 0,
            sync=True,
        )

    try:
        from freezegun import freeze_time
    except:
        pass

    def bulk_create_persons(persons_list: list[dict]):
        persons = []
        person_mapping = {}
        for _person in persons_list:
            with ExitStack() as stack:
                if _person.get("created_at"):
                    stack.enter_context(freeze_time(_person["created_at"]))
                persons.append(Person(**{key: value for key, value in _person.items() if key != "distinct_ids"}))

        inserted = Person.objects.bulk_create(persons)

        person_inserts = []
        distinct_ids = []
        distinct_id_inserts = []
        for index, person in enumerate(inserted):
            for distinct_id in persons_list[index]["distinct_ids"]:
                distinct_ids.append(
                    PersonDistinctId(
                        person_id=person.pk,
                        distinct_id=distinct_id,
                        team_id=person.team_id,
                    )
                )
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

        PersonDistinctId.objects.bulk_create(distinct_ids)
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
    sync: bool = False,
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
    p.produce(topic=KAFKA_PERSON, sql=INSERT_PERSON_SQL, data=data, sync=sync)
    return uuid


def create_person_distinct_id(
    team_id: int,
    distinct_id: str,
    person_id: str,
    version=0,
    is_deleted: bool = False,
    sync: bool = False,
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
        sync=sync,
    )


def _fetch_persons_by_distinct_ids_via_personhog(
    team_id: int, distinct_ids: list[str], *, distinct_id_limit: int | None = None
) -> list[Person]:
    from posthog.personhog_client.client import get_personhog_client

    client = get_personhog_client()
    if client is None:
        raise RuntimeError("personhog client not configured")

    resp = client.get_persons_by_distinct_ids_in_team(
        GetPersonsByDistinctIdsInTeamRequest(team_id=team_id, distinct_ids=distinct_ids)
    )

    present_results = [r for r in resp.results if r.person and r.person.id]
    valid_results = [r for r in present_results if r.person.team_id == team_id]

    mismatched = len(present_results) - len(valid_results)
    if mismatched:
        PERSONHOG_TEAM_MISMATCH_TOTAL.labels(
            operation="get_persons_by_distinct_ids", client_name=get_client_name()
        ).inc(mismatched)
        logger.warning(
            "personhog_team_mismatch", operation="get_persons_by_distinct_ids", team_id=team_id, dropped=mismatched
        )

    # The RPC returns one result per distinct_id, so the same person can
    # appear multiple times.  Deduplicate by person_id to return unique persons.
    seen_person_ids: set[int] = set()
    unique_results = []
    for r in valid_results:
        if r.person.id not in seen_person_ids:
            seen_person_ids.add(r.person.id)
            unique_results.append(r)
    valid_results = unique_results

    person_ids = [r.person.id for r in valid_results]
    if not person_ids:
        return []

    did_request = GetDistinctIdsForPersonsRequest(team_id=team_id, person_ids=person_ids)
    if distinct_id_limit is not None:
        did_request.limit_per_person = distinct_id_limit
    distinct_ids_resp = client.get_distinct_ids_for_persons(did_request)

    distinct_ids_by_person: dict[int, list[str]] = {}
    for pd in distinct_ids_resp.person_distinct_ids:
        distinct_ids_by_person[pd.person_id] = [d.distinct_id for d in pd.distinct_ids]

    return [
        proto_person_to_model(r.person, distinct_ids=distinct_ids_by_person.get(r.person.id, [])) for r in valid_results
    ]


_T = TypeVar("_T")


def _personhog_routed(
    operation: str,
    personhog_fn: Callable[[], _T],
    orm_fn: Callable[[], _T],
    *,
    team_id: int,
) -> _T:
    """Try personhog first, fall back to ORM on failure or when disabled.

    Handles gate check, metrics, and error logging for all personhog routing.
    """
    from posthog.personhog_client.gate import use_personhog

    if use_personhog():
        try:
            result = personhog_fn()
            PERSONHOG_ROUTING_TOTAL.labels(operation=operation, source="personhog", client_name=get_client_name()).inc()
            return result
        except Exception:
            PERSONHOG_ROUTING_ERRORS_TOTAL.labels(
                operation=operation,
                source="personhog",
                error_type="grpc_error",
                client_name=get_client_name(),
            ).inc()
            logger.warning("personhog_%s_failure", operation, team_id=team_id, exc_info=True)

    PERSONHOG_ROUTING_TOTAL.labels(operation=operation, source="django_orm", client_name=get_client_name()).inc()
    return orm_fn()


def get_persons_by_distinct_ids(
    team_id: int,
    distinct_ids: list[str],
    *,
    operation: str = "get_persons_by_distinct_ids",
    distinct_id_limit: int | None = None,
) -> list[Person]:
    def orm_fn() -> list[Person]:
        did_queryset = PersonDistinctId.objects.db_manager(READ_DB_FOR_PERSONS).filter(team_id=team_id).order_by("id")

        persons = list(
            Person.objects.db_manager(READ_DB_FOR_PERSONS)
            .filter(
                team_id=team_id,
                persondistinctid__team_id=team_id,
                persondistinctid__distinct_id__in=distinct_ids,
            )
            .prefetch_related(
                Prefetch(
                    "persondistinctid_set",
                    queryset=did_queryset,
                    to_attr="distinct_ids_cache",
                )
            )
        )

        if distinct_id_limit is not None:
            for person in persons:
                person.distinct_ids_cache = person.distinct_ids_cache[:distinct_id_limit]

        return cast(list[Person], persons)

    return _personhog_routed(
        operation,
        lambda: _fetch_persons_by_distinct_ids_via_personhog(
            team_id, distinct_ids, distinct_id_limit=distinct_id_limit
        ),
        orm_fn,
        team_id=team_id,
    )


def get_persons_mapped_by_distinct_id(
    team_id: int,
    distinct_ids: list[str],
) -> dict[str, Person]:
    """Look up persons by distinct_ids and return a direct distinct_id → Person mapping.

    Optimized for callers that need a mapping keyed by distinct_id and only
    need the single matched distinct_id on each Person (e.g. session recordings).
    Unlike ``get_persons_by_distinct_ids``, this avoids fetching all distinct_ids
    for each person.

    ORM path: queries PersonDistinctId → Person (2 queries, no extra IDs loaded).
    Personhog path: single GetPersonsByDistinctIdsInTeam RPC (no follow-up
    GetDistinctIdsForPersons call needed — the response already carries the
    matched distinct_id).
    """

    def orm_fn() -> dict[str, Person]:
        person_distinct_ids = (
            PersonDistinctId.objects.db_manager(READ_DB_FOR_PERSONS)
            .filter(distinct_id__in=distinct_ids, team_id=team_id)
            .select_related("person")
        )
        result: dict[str, Person] = {}
        for pdi in person_distinct_ids:
            if pdi.person and pdi.person.team_id == team_id:
                pdi.person._distinct_ids = [pdi.distinct_id]
                result[pdi.distinct_id] = pdi.person
        return result

    def personhog_fn() -> dict[str, Person]:
        from posthog.personhog_client.client import get_personhog_client

        client = get_personhog_client()
        if client is None:
            raise RuntimeError("personhog client not configured")

        resp = client.get_persons_by_distinct_ids_in_team(
            GetPersonsByDistinctIdsInTeamRequest(team_id=team_id, distinct_ids=distinct_ids)
        )

        present_results = [r for r in resp.results if r.person and r.person.id]
        valid_results = [r for r in present_results if r.person.team_id == team_id]

        mismatched = len(present_results) - len(valid_results)
        if mismatched:
            PERSONHOG_TEAM_MISMATCH_TOTAL.labels(
                operation="get_persons_mapped_by_distinct_id", client_name=get_client_name()
            ).inc(mismatched)
            logger.warning(
                "personhog_team_mismatch",
                operation="get_persons_mapped_by_distinct_id",
                team_id=team_id,
                dropped=mismatched,
            )

        return {r.distinct_id: proto_person_to_model(r.person, distinct_ids=[r.distinct_id]) for r in valid_results}

    return _personhog_routed(
        "get_persons_mapped_by_distinct_id",
        personhog_fn,
        orm_fn,
        team_id=team_id,
    )


def _fetch_persons_by_uuids_via_personhog(team_id: int, uuids: list[str]) -> list[Person]:
    from posthog.personhog_client.client import get_personhog_client

    client = get_personhog_client()
    if client is None:
        raise RuntimeError("personhog client not configured")

    resp = client.get_persons_by_uuids(GetPersonsByUuidsRequest(team_id=team_id, uuids=uuids))

    present_persons = [p for p in resp.persons if p.id]
    valid_persons = [p for p in present_persons if p.team_id == team_id]

    mismatched = len(present_persons) - len(valid_persons)
    if mismatched:
        PERSONHOG_TEAM_MISMATCH_TOTAL.labels(operation="get_persons_by_uuids", client_name=get_client_name()).inc(
            mismatched
        )
        logger.warning("personhog_team_mismatch", operation="get_persons_by_uuids", team_id=team_id, dropped=mismatched)

    person_ids = [p.id for p in valid_persons]
    if not person_ids:
        return []

    distinct_ids_resp = client.get_distinct_ids_for_persons(
        GetDistinctIdsForPersonsRequest(team_id=team_id, person_ids=person_ids)
    )

    distinct_ids_by_person: dict[int, list[str]] = {}
    for pd in distinct_ids_resp.person_distinct_ids:
        distinct_ids_by_person[pd.person_id] = [d.distinct_id for d in pd.distinct_ids]

    return [proto_person_to_model(p, distinct_ids=distinct_ids_by_person.get(p.id, [])) for p in valid_persons]


def get_persons_by_uuids(team: Team, uuids: list[str]) -> QuerySet | list[Person]:
    personhog_fn: Callable[[], QuerySet | list[Person]] = lambda: _fetch_persons_by_uuids_via_personhog(team.pk, uuids)
    orm_fn: Callable[[], QuerySet | list[Person]] = lambda: Person.objects.db_manager(READ_DB_FOR_PERSONS).filter(
        team_id=team.pk, uuid__in=uuids
    )
    return _personhog_routed(
        "get_persons_by_uuids",
        personhog_fn,
        orm_fn,
        team_id=team.pk,
    )


def _fetch_person_by_id_via_personhog(team_id: int, person_id: int) -> Optional[Person]:
    from posthog.personhog_client.client import get_personhog_client

    client = get_personhog_client()
    if client is None:
        raise RuntimeError("personhog client not configured")

    resp = client.get_person(GetPersonRequest(team_id=team_id, person_id=person_id))

    if not resp.person or not resp.person.id:
        return None

    if resp.person.team_id != team_id:
        PERSONHOG_TEAM_MISMATCH_TOTAL.labels(operation="get_person_by_id", client_name=get_client_name()).inc()
        logger.warning("personhog_team_mismatch", operation="get_person_by_id", team_id=team_id)
        return None

    did_resp = client.get_distinct_ids_for_person(
        GetDistinctIdsForPersonRequest(team_id=team_id, person_id=resp.person.id)
    )

    return proto_person_to_model(resp.person, distinct_ids=[d.distinct_id for d in did_resp.distinct_ids])


def get_person_by_id(team_id: int, person_id: int) -> Optional[Person]:
    return _personhog_routed(
        "get_person_by_id",
        lambda: _fetch_person_by_id_via_personhog(team_id, person_id),
        lambda: Person.objects.db_manager(READ_DB_FOR_PERSONS).filter(team_id=team_id, pk=person_id).first(),
        team_id=team_id,
    )


def _fetch_person_by_uuid_via_personhog(team_id: int, uuid: str) -> Optional[Person]:
    from posthog.personhog_client.client import get_personhog_client

    client = get_personhog_client()
    if client is None:
        raise RuntimeError("personhog client not configured")

    resp = client.get_person_by_uuid(GetPersonByUuidRequest(team_id=team_id, uuid=uuid))

    if not resp.person or not resp.person.id:
        return None

    if resp.person.team_id != team_id:
        PERSONHOG_TEAM_MISMATCH_TOTAL.labels(operation="get_person_by_uuid", client_name=get_client_name()).inc()
        logger.warning("personhog_team_mismatch", operation="get_person_by_uuid", team_id=team_id)
        return None

    did_resp = client.get_distinct_ids_for_person(
        GetDistinctIdsForPersonRequest(team_id=team_id, person_id=resp.person.id)
    )

    return proto_person_to_model(resp.person, distinct_ids=[d.distinct_id for d in did_resp.distinct_ids])


def get_person_by_uuid(team_id: int, uuid: str) -> Optional[Person]:
    return _personhog_routed(
        "get_person_by_uuid",
        lambda: _fetch_person_by_uuid_via_personhog(team_id, uuid),
        lambda: Person.objects.db_manager(READ_DB_FOR_PERSONS).filter(team_id=team_id, uuid=uuid).first(),
        team_id=team_id,
    )


def _fetch_person_by_distinct_id_via_personhog(team_id: int, distinct_id: str) -> Optional[Person]:
    from posthog.personhog_client.client import get_personhog_client

    client = get_personhog_client()
    if client is None:
        raise RuntimeError("personhog client not configured")

    resp = client.get_person_by_distinct_id(GetPersonByDistinctIdRequest(team_id=team_id, distinct_id=distinct_id))

    if not resp.person or not resp.person.id:
        return None

    if resp.person.team_id != team_id:
        PERSONHOG_TEAM_MISMATCH_TOTAL.labels(operation="get_person_by_distinct_id", client_name=get_client_name()).inc()
        logger.warning("personhog_team_mismatch", operation="get_person_by_distinct_id", team_id=team_id)
        return None

    did_resp = client.get_distinct_ids_for_person(
        GetDistinctIdsForPersonRequest(team_id=team_id, person_id=resp.person.id)
    )

    return proto_person_to_model(resp.person, distinct_ids=[d.distinct_id for d in did_resp.distinct_ids])


def get_person_by_distinct_id(team_id: int, distinct_id: str) -> Optional[Person]:
    return _personhog_routed(
        "get_person_by_distinct_id",
        lambda: _fetch_person_by_distinct_id_via_personhog(team_id, distinct_id),
        lambda: Person.objects.db_manager(READ_DB_FOR_PERSONS)
        .filter(team_id=team_id, persondistinctid__distinct_id=distinct_id)
        .first(),
        team_id=team_id,
    )


def get_person_by_pk_or_uuid(team_id: int, key: str) -> Optional[Person]:
    """Look up a person by UUID or integer PK, routing through personhog when enabled."""
    try:
        UUID(key)
        return get_person_by_uuid(team_id, key)
    except ValueError:
        try:
            return get_person_by_id(team_id, int(key))
        except ValueError:
            return None


def _validate_uuids_via_personhog(team_id: int, uuids: list[str]) -> list[str]:
    from posthog.personhog_client.client import get_personhog_client

    client = get_personhog_client()
    if client is None:
        raise RuntimeError("personhog client not configured")

    resp = client.get_persons_by_uuids(GetPersonsByUuidsRequest(team_id=team_id, uuids=uuids))
    valid = [p for p in resp.persons if p.team_id == team_id]
    mismatched = len(resp.persons) - len(valid)
    if mismatched:
        PERSONHOG_TEAM_MISMATCH_TOTAL.labels(
            operation="validate_person_uuids_exist", client_name=get_client_name()
        ).inc(mismatched)
        logger.warning(
            "personhog_team_mismatch",
            operation="validate_person_uuids_exist",
            team_id=team_id,
            dropped=mismatched,
        )
    return [p.uuid for p in valid]


def validate_person_uuids_exist(team_id: int, uuids: list[str]) -> list[str]:
    return _personhog_routed(
        "validate_person_uuids_exist",
        lambda: _validate_uuids_via_personhog(team_id, uuids),
        lambda: [
            str(u)
            for u in Person.objects.db_manager(READ_DB_FOR_PERSONS)
            .filter(team_id=team_id, uuid__in=uuids)
            .values_list("uuid", flat=True)
        ],
        team_id=team_id,
    )


def delete_persons_from_postgres(team_id: int, persons: list[Person]) -> None:
    """Delete Person rows (and associated PersonDistinctId rows) from Postgres.

    Uses the personhog RPC when available, falling back to ORM-based deletion.
    Processes in batches of 1000 (the RPC maximum).
    """

    def personhog_fn() -> None:
        from posthog.personhog_client.client import get_personhog_client

        client = get_personhog_client()
        if client is None:
            raise RuntimeError("personhog client not configured")

        uuids = [str(p.uuid) for p in persons]
        for i in range(0, len(uuids), 1000):
            batch = uuids[i : i + 1000]
            client.delete_persons(DeletePersonsRequest(team_id=team_id, person_uuids=batch))

    def orm_fn() -> None:
        for person in persons:
            person.delete()

    _personhog_routed(
        "delete_persons",
        personhog_fn,
        orm_fn,
        team_id=team_id,
    )


def delete_person(person: Person, sync: bool = False) -> None:
    # This is racy https://github.com/PostHog/posthog/issues/11590
    distinct_ids_to_version = _get_distinct_ids_with_version(person)
    _delete_person(person.team_id, person.uuid, int(person.version or 0), person.created_at, sync)
    for distinct_id, version in distinct_ids_to_version.items():
        _delete_ch_distinct_id(person.team_id, person.uuid, distinct_id, version, sync)


def _delete_person(
    team_id: int,
    uuid: UUID,
    version: int,
    created_at: Optional[datetime.datetime] = None,
    sync: bool = False,
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
        sync=sync,
    )


def _get_distinct_ids_with_version(person: Person) -> dict[str, int]:
    return {
        distinct_id: int(version or 0)
        for distinct_id, version in PersonDistinctId.objects.db_manager(READ_DB_FOR_PERSONS)
        .filter(person=person, team_id=person.team_id)
        .order_by("id")
        .values_list("distinct_id", "version")
    }


def _delete_ch_distinct_id(team_id: int, uuid: UUID, distinct_id: str, version: int, sync: bool = False) -> None:
    create_person_distinct_id(
        team_id=team_id,
        distinct_id=distinct_id,
        person_id=str(uuid),
        version=version + 100,
        is_deleted=True,
        sync=sync,
    )
