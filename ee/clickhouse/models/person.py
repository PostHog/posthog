import json
import uuid
from typing import Dict, List, Optional

from django.db.models.signals import post_delete, post_save
from django.dispatch import receiver
from rest_framework import serializers

from ee.clickhouse.client import sync_execute
from ee.clickhouse.models.clickhouse import generate_clickhouse_uuid
from ee.clickhouse.sql.person import (
    DELETE_PERSON_BY_ID,
    GET_DISTINCT_IDS_SQL,
    GET_DISTINCT_IDS_SQL_BY_ID,
    GET_PERSON_BY_DISTINCT_ID,
    GET_PERSON_SQL,
    INSERT_PERSON_DISTINCT_ID,
    INSERT_PERSON_SQL,
    PERSON_DISTINCT_ID_EXISTS_SQL,
    PERSON_EXISTS_SQL,
    UPDATE_PERSON_ATTACHED_DISTINCT_ID,
    UPDATE_PERSON_IS_IDENTIFIED,
    UPDATE_PERSON_PROPERTIES,
)
from ee.kafka.client import KafkaProducer
from ee.kafka.topics import KAFKA_PERSON, KAFKA_PERSON_UNIQUE_ID
from posthog import settings
from posthog.ee import check_ee_enabled
from posthog.models.person import Person, PersonDistinctId
from posthog.models.team import Team

if settings.EE_AVAILABLE and check_ee_enabled():

    @receiver(post_save, sender=Person)
    def person_created(sender, instance: Person, created, **kwargs):
        create_person(
            team_id=instance.team_id,
            distinct_ids=instance.distinct_ids,
            properties=instance.properties,
            uid=str(instance.uuid),
        )

    @receiver(post_save, sender=PersonDistinctId)
    def person_distinct_id_created(sender, instance: PersonDistinctId, created, **kwargs):
        create_person_distinct_id(instance.team_id, instance.distinct_id, instance.person_id)

    @receiver(post_delete, sender=Person)
    def person_deleted(sender, instance: Person, **kwargs):
        delete_person(instance.id)


def create_person(
    team_id: int,
    distinct_ids: List[str],
    uid: Optional[str] = None,
    properties: Optional[Dict] = {},
    sync: bool = False,
    **kwargs
) -> int:
    if not uid:
        uid = uuid.uuid4()
    p = KafkaProducer()
    data = {"id": uid, "team_id": team_id, "properties": json.dumps(properties)}
    p.produce(topic=KAFKA_PERSON, data=json.dumps(data))
    for distinct_id in distinct_ids:
        if not distinct_ids_exist(team_id, [distinct_id]):
            create_person_distinct_id(team_id=team_id, distinct_id=distinct_id, person_id=uid)
    return uuid


def update_person_properties(team_id: int, id: int, properties: Dict) -> None:
    sync_execute(UPDATE_PERSON_PROPERTIES, {"team_id": team_id, "id": id, "properties": json.dumps(properties)})


def update_person_is_identified(team_id: int, id: int, is_identified: bool) -> None:
    sync_execute(
        UPDATE_PERSON_IS_IDENTIFIED, {"team_id": team_id, "id": id, "is_identified": "1" if is_identified else "0"}
    )


def create_person_distinct_id(team_id: Team, distinct_id: str, person_id: int) -> None:
    p = KafkaProducer()
    data = {"distinct_id": distinct_id, "person_id": person_id, "team_id": team_id}
    p.produce(topic=KAFKA_PERSON_UNIQUE_ID, data=json.dumps(data))


def distinct_ids_exist(team_id: int, ids: List[str]) -> bool:
    return bool(sync_execute(PERSON_DISTINCT_ID_EXISTS_SQL.format([str(id) for id in ids]), {"team_id": team_id})[0][0])


def person_exists(id: int) -> bool:
    return bool(sync_execute(PERSON_EXISTS_SQL, {"id": id})[0][0])


def attach_distinct_ids(person_id: str, distinct_ids: List[str], team_id: int) -> None:
    for distinct_id in distinct_ids:
        create_person_distinct_id(team_id, distinct_id, person_id)


def get_persons(team_id: int):
    result = sync_execute(GET_PERSON_SQL, {"team_id": team_id})
    return ClickhousePersonSerializer(result, many=True).data


def get_person_distinct_ids(team_id: int):
    result = sync_execute(GET_DISTINCT_IDS_SQL, {"team_id": team_id})
    return ClickhousePersonDistinctIdSerializer(result, many=True).data


def get_person_by_distinct_id(team_id: int, distinct_id: str) -> int:
    result = sync_execute(GET_PERSON_BY_DISTINCT_ID, {"team_id": team_id, "distinct_id": distinct_id.__str__()})
    if len(result) > 0:
        return ClickhousePersonSerializer(result[0], many=False).data

    return None


def merge_people(team_id: int, target: Dict, old_id: int, old_props: Dict) -> None:
    # merge the properties
    properties = {**old_props, **target["properties"]}

    update_person_properties(team_id=team_id, id=target["id"], properties=properties)

    other_person_distinct_ids = sync_execute(
        GET_DISTINCT_IDS_SQL_BY_ID, {"person_id": old_id, "team_id": target["team_id"]}
    )

    parsed_other_person_distinct_ids = ClickhousePersonDistinctIdSerializer(other_person_distinct_ids, many=True).data

    for person_distinct_id in parsed_other_person_distinct_ids:
        sync_execute(
            UPDATE_PERSON_ATTACHED_DISTINCT_ID,
            {"person_id": target["id"], "distinct_id": person_distinct_id["distinct_id"]},
        )
    delete_person(old_id)


def delete_person(person_id):
    sync_execute(DELETE_PERSON_BY_ID, {"id": person_id,})


class ClickhousePersonSerializer(serializers.Serializer):
    id = serializers.SerializerMethodField()
    created_at = serializers.SerializerMethodField()
    team_id = serializers.SerializerMethodField()
    properties = serializers.SerializerMethodField()
    is_identified = serializers.SerializerMethodField()

    def get_id(self, person):
        return person[0]

    def get_created_at(self, person):
        return person[1]

    def get_team_id(self, person):
        return person[2]

    def get_properties(self, person):
        return json.loads(person[3])

    def get_is_identified(self, person):
        if person and len(person) >= 5:
            return person[4]
        return False


class ClickhousePersonDistinctIdSerializer(serializers.Serializer):
    id = serializers.SerializerMethodField()
    distinct_id = serializers.SerializerMethodField()
    person_id = serializers.SerializerMethodField()
    team_id = serializers.SerializerMethodField()

    def get_id(self, pid):
        return pid[0]

    def get_distinct_id(self, pid):
        return pid[1]

    def get_person_id(self, pid):
        return pid[2]

    def get_team_id(self, pid):
        return pid[3]
