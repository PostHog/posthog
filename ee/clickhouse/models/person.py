import datetime
import json
from typing import Dict, List, Optional
from uuid import UUID

from django.db.models.query import QuerySet
from django.db.models.signals import post_delete, post_save
from django.dispatch import receiver
from django.utils.timezone import now
from rest_framework import serializers

from ee.clickhouse.client import sync_execute
from ee.clickhouse.sql.person import (
    DELETE_PERSON_BY_ID,
    DELETE_PERSON_DISTINCT_ID_BY_PERSON_ID,
    DELETE_PERSON_EVENTS_BY_ID,
    INSERT_PERSON_DISTINCT_ID,
    INSERT_PERSON_SQL,
)
from ee.kafka_client.client import ClickhouseProducer
from ee.kafka_client.topics import KAFKA_PERSON, KAFKA_PERSON_UNIQUE_ID
from posthog import settings
from posthog.ee import is_clickhouse_enabled
from posthog.models.person import Person, PersonDistinctId
from posthog.models.utils import UUIDT

if settings.EE_AVAILABLE and is_clickhouse_enabled():

    @receiver(post_save, sender=Person)
    def person_created(sender, instance: Person, created, **kwargs):
        create_person(
            team_id=instance.team.pk,
            properties=instance.properties,
            uuid=str(instance.uuid),
            is_identified=instance.is_identified,
        )

    @receiver(post_save, sender=PersonDistinctId)
    def person_distinct_id_created(sender, instance: PersonDistinctId, created, **kwargs):
        create_person_distinct_id(instance.pk, instance.team.pk, instance.distinct_id, str(instance.person.uuid))

    @receiver(post_delete, sender=Person)
    def person_deleted(sender, instance: Person, **kwargs):
        delete_person(instance.uuid, instance.properties, instance.is_identified, team_id=instance.team_id)


def create_person(
    team_id: int,
    uuid: Optional[str] = None,
    properties: Optional[Dict] = {},
    sync: bool = False,
    is_identified: bool = False,
    timestamp: Optional[datetime.datetime] = None,
) -> str:
    if uuid:
        uuid = str(uuid)
    else:
        uuid = str(UUIDT())
    if not timestamp:
        timestamp = now()

    data = {
        "id": str(uuid),
        "team_id": team_id,
        "properties": json.dumps(properties),
        "is_identified": int(is_identified),
        "created_at": timestamp.strftime("%Y-%m-%d %H:%M:%S.%f"),
        "_timestamp": timestamp.strftime("%Y-%m-%d %H:%M:%S"),
    }
    p = ClickhouseProducer()
    p.produce(topic=KAFKA_PERSON, sql=INSERT_PERSON_SQL, data=data, sync=sync)
    return uuid


def create_person_distinct_id(id: int, team_id: int, distinct_id: str, person_id: str) -> None:
    data = {"id": id, "distinct_id": distinct_id, "person_id": person_id, "team_id": team_id}
    p = ClickhouseProducer()
    p.produce(topic=KAFKA_PERSON_UNIQUE_ID, sql=INSERT_PERSON_DISTINCT_ID, data=data)


def get_persons_by_distinct_ids(team_id: int, distinct_ids: List[str]) -> QuerySet:
    return Person.objects.filter(
        team_id=team_id, persondistinctid__team_id=team_id, persondistinctid__distinct_id__in=distinct_ids
    )


def get_persons_by_uuids(team_id: int, uuids: List[str]) -> QuerySet:
    return Person.objects.filter(team_id=team_id, uuid__in=uuids)


def delete_person(
    person_id: UUID, properties: Dict, is_identified: bool, delete_events: bool = False, team_id: int = False
) -> None:
    timestamp = now()

    data = {
        "id": person_id,
        "team_id": team_id,
        "properties": json.dumps(properties),
        "is_identified": int(is_identified),
        "created_at": timestamp.strftime("%Y-%m-%d %H:%M:%S"),
        "_timestamp": timestamp.strftime("%Y-%m-%d %H:%M:%S"),
    }

    try:
        if delete_events:
            sync_execute(DELETE_PERSON_EVENTS_BY_ID, {"id": person_id, "team_id": team_id})
    except:
        pass  # cannot delete if the table is distributed

    sync_execute(DELETE_PERSON_BY_ID, data)
    sync_execute(DELETE_PERSON_DISTINCT_ID_BY_PERSON_ID, {"id": person_id,})


class ClickhousePersonSerializer(serializers.Serializer):
    id = serializers.SerializerMethodField()
    created_at = serializers.SerializerMethodField()
    team_id = serializers.SerializerMethodField()
    properties = serializers.SerializerMethodField()
    is_identified = serializers.SerializerMethodField()
    name = serializers.SerializerMethodField()
    distinct_ids = serializers.SerializerMethodField()

    def get_name(self, person):
        props = json.loads(person[3])
        email = props.get("email", None)
        return email or person[0]

    def get_id(self, person):
        return person[0]

    def get_created_at(self, person):
        return person[1]

    def get_team_id(self, person):
        return person[2]

    def get_properties(self, person):
        return json.loads(person[3])

    def get_is_identified(self, person):
        return person[4]

    # all queries might not retrieve distinct_ids
    def get_distinct_ids(self, person):
        return person[5] if len(person) > 5 else []
