import json
import datetime
from contextlib import ExitStack
from typing import Optional, Union
from uuid import UUID
from zoneinfo import ZoneInfo

from django.db.models.query import QuerySet
from django.db.models.signals import post_delete, post_save
from django.dispatch import receiver
from django.utils.timezone import now

from dateutil.parser import isoparse

from posthog.clickhouse.client import sync_execute
from posthog.kafka_client.client import ClickhouseProducer
from posthog.kafka_client.topics import KAFKA_PERSON, KAFKA_PERSON_DISTINCT_ID
from posthog.models.person import Person, PersonDistinctId
from posthog.models.person.person import READ_DB_FOR_PERSONS, PersonNew, PersonOld
from posthog.models.person.sql import (
    BULK_INSERT_PERSON_DISTINCT_ID2,
    INSERT_PERSON_BULK_SQL,
    INSERT_PERSON_DISTINCT_ID2,
    INSERT_PERSON_SQL,
)
from posthog.models.signals import mutable_receiver
from posthog.models.team import Team
from posthog.models.utils import UUIDT
from posthog.settings import TEST

if TEST:
    # :KLUDGE: Hooks are kept around for tests. All other code goes through plugin-server or the other methods explicitly

    @mutable_receiver(post_save, sender=Person)
    def person_created(sender, instance: Person, created, **kwargs):
        create_person(
            team_id=instance.team.pk,
            properties=instance.properties,
            uuid=str(instance.uuid),
            is_identified=instance.is_identified,
            version=instance.version or 0,
            sync=True,
        )

    @mutable_receiver(post_save, sender=PersonDistinctId)
    def person_distinct_id_created(sender, instance: PersonDistinctId, created, **kwargs):
        create_person_distinct_id(
            instance.team.pk,
            instance.distinct_id,
            str(instance.person.uuid),
            version=instance.version or 0,
            sync=True,
        )

    @receiver(post_delete, sender=Person)
    def person_deleted(sender, instance: Person, **kwargs):
        _delete_person(
            instance.team.id,
            instance.uuid,
            int(instance.version or 0),
            instance.created_at,
            sync=True,
        )

    @receiver(post_delete, sender=PersonDistinctId)
    def person_distinct_id_deleted(sender, instance: PersonDistinctId, **kwargs):
        _delete_ch_distinct_id(
            instance.team.pk,
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

            created_at = now().strftime("%Y-%m-%d %H:%M:%S.%f")
            timestamp = now().strftime("%Y-%m-%d %H:%M:%S")
            person_inserts.append(
                f"('{person.uuid}', '{created_at}', {person.team_id}, '{json.dumps(person.properties)}', {'1' if person.is_identified else '0'}, '{timestamp}', 0, 0, 0)"
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

    data = {
        "id": str(uuid),
        "team_id": team_id,
        "properties": json.dumps(properties),
        "is_identified": int(is_identified),
        "is_deleted": int(is_deleted),
        "created_at": created_at.strftime("%Y-%m-%d %H:%M:%S.%f"),
        "version": version,
        "_timestamp": timestamp.strftime("%Y-%m-%d %H:%M:%S"),
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


def get_persons_by_distinct_ids(team_id: int, distinct_ids: list[str]) -> list[Person]:
    """Get persons by distinct IDs during dual-table migration period.

    Queries both posthog_person (old) and posthog_person_new tables, combining results.
    Results have persondistinctid_set prefetched for efficient distinct_ids access.

    TODO(migration-cleanup): After migration completes (~2 weeks), remove dual-table logic:
      1. Delete: PersonOld query and old loop
      2. Keep: Only PersonNew query
      3. Or revert to: Person.objects.filter(persondistinctid__distinct_id__in=distinct_ids)
    """
    # Step 1: Get person_ids from PersonDistinctId
    # (FK constraints dropped, so person_id works for both tables)
    person_ids = list(
        PersonDistinctId.objects.db_manager(READ_DB_FOR_PERSONS)
        .filter(team_id=team_id, distinct_id__in=distinct_ids)
        .values_list("person_id", flat=True)
        .distinct()
    )

    if not person_ids:
        return []

    # Step 2: Query both tables
    old_persons = list(PersonOld.objects.db_manager(READ_DB_FOR_PERSONS).filter(id__in=person_ids, team_id=team_id))
    new_persons = list(PersonNew.objects.db_manager(READ_DB_FOR_PERSONS).filter(id__in=person_ids, team_id=team_id))

    # Step 3: Manually prefetch PersonDistinctId for all persons
    # (PersonOld/PersonNew don't have persondistinctid_set relation, so we manually attach it)
    all_person_ids = [p.id for p in old_persons] + [p.id for p in new_persons]
    if all_person_ids:
        distinct_id_objects = list(
            PersonDistinctId.objects.db_manager(READ_DB_FOR_PERSONS).filter(
                person_id__in=all_person_ids, team_id=team_id
            )
        )

        # Group by person_id
        person_to_distinct_ids: dict[int, list] = {}
        for did in distinct_id_objects:
            person_to_distinct_ids.setdefault(did.person_id, []).append(did)

        # Attach to persons as distinct_ids_cache
        for person in old_persons + new_persons:
            person.distinct_ids_cache = person_to_distinct_ids.get(person.id, [])

    # Step 4: Cast to Person type and return
    results = []
    for person in old_persons:
        person.__class__ = Person
        results.append(person)
    for person in new_persons:
        person.__class__ = Person
        results.append(person)

    return results


def get_persons_by_uuids(
    team_id: int,
    uuids: list[str],
    distinct_id_limit: int = 1000,
    order_by: Optional[list[str]] = None,
    only_fields: Optional[list[str]] = None,
) -> list[Person]:
    """Get persons by UUIDs during dual-table migration period.

    Queries both posthog_person (old) and posthog_person_new tables, combining results.
    Manually implements prefetching, ordering, and field limiting.

    Args:
        team_id: Team ID to filter by
        uuids: List of person UUIDs to fetch
        distinct_id_limit: Max PersonDistinctId objects to fetch per person
        order_by: List of fields to order by (e.g., ["-created_at", "uuid"])
        only_fields: List of fields to load (defers all others)

    Returns:
        List of Person instances with distinct_ids_cache prefetched
    """
    if not uuids:
        return []

    # Query both tables
    old_qs = PersonOld.objects.db_manager(READ_DB_FOR_PERSONS).filter(uuid__in=uuids, team_id=team_id)
    new_qs = PersonNew.objects.db_manager(READ_DB_FOR_PERSONS).filter(uuid__in=uuids, team_id=team_id)

    # Apply field limiting if requested
    if only_fields:
        old_qs = old_qs.only(*only_fields)
        new_qs = new_qs.only(*only_fields)

    # Fetch results
    old_persons = list(old_qs)
    new_persons = list(new_qs)

    # Manually prefetch PersonDistinctId for all persons
    all_person_ids = [p.id for p in old_persons] + [p.id for p in new_persons]
    if all_person_ids:
        # Fetch PersonDistinctId objects with limit per person
        distinct_id_objects = list(
            PersonDistinctId.objects.db_manager(READ_DB_FOR_PERSONS).filter(
                person_id__in=all_person_ids, team_id=team_id
            )[: distinct_id_limit * len(all_person_ids)]
        )

        # Group by person_id and apply limit
        person_to_distinct_ids: dict[int, list] = {}
        for did in distinct_id_objects:
            if did.person_id not in person_to_distinct_ids:
                person_to_distinct_ids[did.person_id] = []
            if len(person_to_distinct_ids[did.person_id]) < distinct_id_limit:
                person_to_distinct_ids[did.person_id].append(did)

        # Attach to persons as distinct_ids_cache
        for person in old_persons + new_persons:
            person.distinct_ids_cache = person_to_distinct_ids.get(person.id, [])

    # Cast to Person type
    results = []
    for person in old_persons:
        person.__class__ = Person
        results.append(person)
    for person in new_persons:
        person.__class__ = Person
        results.append(person)

    # Apply ordering if requested
    if order_by:
        for field in reversed(order_by):
            reverse = field.startswith("-")
            field_name = field.lstrip("-")
            results.sort(key=lambda x: getattr(x, field_name, None) or "", reverse=reverse)

    return results


def get_persons_by_uuids_legacy(team: Team, uuids: list[str]) -> QuerySet:
    """Legacy helper - use get_persons_by_uuids() for dual-table support."""
    return Person.objects.db_manager(READ_DB_FOR_PERSONS).filter(team_id=team.pk, uuid__in=uuids)


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
