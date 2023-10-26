import datetime
import json
from contextlib import ExitStack
from typing import Dict, List, Optional, Union
from uuid import UUID

from zoneinfo import ZoneInfo
from dateutil.parser import isoparse
from django.db.models.query import QuerySet
from django.db.models.signals import post_delete, post_save
from django.dispatch import receiver
from django.utils.timezone import now

from posthog.client import sync_execute
from posthog.kafka_client.client import ClickhouseProducer
from posthog.kafka_client.topics import (
    KAFKA_PERSON,
    KAFKA_PERSON_DISTINCT_ID,
    KAFKA_PERSON_OVERRIDES,
)
from posthog.models.person import Person, PersonDistinctId
from posthog.models.person.sql import (
    BULK_INSERT_PERSON_DISTINCT_ID2,
    INSERT_PERSON_BULK_SQL,
    INSERT_PERSON_DISTINCT_ID2,
    INSERT_PERSON_OVERRIDE,
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

    def bulk_create_persons(persons_list: List[Dict]):
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
    properties: Optional[Dict] = {},
    sync: bool = False,
    is_identified: bool = False,
    is_deleted: bool = False,
    timestamp: Optional[Union[datetime.datetime, str]] = None,
    created_at: Optional[datetime.datetime] = None,
) -> str:
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


def create_person_override(
    team_id: int,
    old_person_uuid: str,
    override_person_uuid: str,
    version: int,
    merged_at: datetime.datetime,
    oldest_event: datetime.datetime,
    sync: bool = False,
) -> None:
    p = ClickhouseProducer()
    p.produce(
        topic=KAFKA_PERSON_OVERRIDES,
        sql=INSERT_PERSON_OVERRIDE,
        data={
            "team_id": team_id,
            "old_person_id": old_person_uuid,
            "override_person_id": override_person_uuid,
            "version": version,
            "merged_at": merged_at.strftime("%Y-%m-%d %H:%M:%S.%f"),
            "oldest_event": oldest_event.strftime("%Y-%m-%d %H:%M:%S.%f"),
        },
        sync=sync,
    )


def get_persons_by_distinct_ids(team_id: int, distinct_ids: List[str]) -> QuerySet:
    return Person.objects.filter(
        team_id=team_id,
        persondistinctid__team_id=team_id,
        persondistinctid__distinct_id__in=distinct_ids,
    )


def get_persons_by_uuids(team: Team, uuids: List[str]) -> QuerySet:
    return Person.objects.filter(team_id=team.pk, uuid__in=uuids)


def delete_person(person: Person, sync: bool = False) -> None:
    # This is racy https://github.com/PostHog/posthog/issues/11590
    distinct_ids_to_version = _get_distinct_ids_with_version(person)
    _delete_person(person.team.id, person.uuid, int(person.version or 0), person.created_at, sync)
    for distinct_id, version in distinct_ids_to_version.items():
        _delete_ch_distinct_id(person.team.id, person.uuid, distinct_id, version, sync)


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
        version=version + 100,  # keep in sync with deletePerson in plugin-server/src/utils/db/db.ts
        created_at=created_at,
        is_deleted=True,
        sync=sync,
    )


def _get_distinct_ids_with_version(person: Person) -> Dict[str, int]:
    return {
        distinct_id: int(version or 0)
        for distinct_id, version in PersonDistinctId.objects.filter(person=person, team_id=person.team_id)
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
