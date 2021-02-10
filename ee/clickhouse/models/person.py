import datetime
import json
from typing import Any, Dict, List, Optional
from uuid import UUID, uuid4

from django.db.models.query import QuerySet
from django.db.models.signals import post_delete, post_save
from django.dispatch import receiver
from django.utils.timezone import now
from rest_framework import serializers

from ee.clickhouse.client import sync_execute
from ee.clickhouse.models.property import parse_prop_clauses
from ee.clickhouse.sql.person import (
    DELETE_PERSON_BY_ID,
    DELETE_PERSON_DISTINCT_ID_BY_PERSON_ID,
    DELETE_PERSON_EVENTS_BY_ID,
    GET_DISTINCT_IDS_SQL,
    GET_DISTINCT_IDS_SQL_BY_ID,
    GET_PERSON_BY_DISTINCT_ID,
    GET_PERSON_IDS_BY_FILTER,
    GET_PERSON_SQL,
    INSERT_PERSON_DISTINCT_ID,
    INSERT_PERSON_SQL,
    PERSON_DISTINCT_ID_EXISTS_SQL,
    UPDATE_PERSON_ATTACHED_DISTINCT_ID,
    UPDATE_PERSON_IS_IDENTIFIED,
    UPDATE_PERSON_PROPERTIES,
)
from ee.kafka_client.client import ClickhouseProducer
from ee.kafka_client.topics import KAFKA_PERSON, KAFKA_PERSON_UNIQUE_ID
from posthog import settings
from posthog.ee import is_ee_enabled
from posthog.models.filters import Filter
from posthog.models.person import Person, PersonDistinctId
from posthog.models.team import Team
from posthog.models.utils import UUIDT

if settings.EE_AVAILABLE and is_ee_enabled():

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
        delete_person(instance.uuid)


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
    }
    p = ClickhouseProducer()
    p.produce(topic=KAFKA_PERSON, sql=INSERT_PERSON_SQL, data=data, sync=sync)
    return uuid


def update_person_properties(team_id: int, id: str, properties: Dict) -> None:
    sync_execute(UPDATE_PERSON_PROPERTIES, {"team_id": team_id, "id": id, "properties": json.dumps(properties)})


def update_person_is_identified(team_id: int, id: str, is_identified: bool) -> None:
    sync_execute(
        UPDATE_PERSON_IS_IDENTIFIED, {"team_id": team_id, "id": id, "is_identified": "1" if is_identified else "0"}
    )


def create_person_distinct_id(id: int, team_id: int, distinct_id: str, person_id: str) -> None:
    data = {"id": id, "distinct_id": distinct_id, "person_id": person_id, "team_id": team_id}
    p = ClickhouseProducer()
    p.produce(topic=KAFKA_PERSON_UNIQUE_ID, sql=INSERT_PERSON_DISTINCT_ID, data=data)


def distinct_ids_exist(team_id: int, ids: List[str]) -> bool:
    return bool(sync_execute(PERSON_DISTINCT_ID_EXISTS_SQL.format([str(id) for id in ids]), {"team_id": team_id})[0][0])


def get_persons(team_id: int):
    result = sync_execute(GET_PERSON_SQL, {"team_id": team_id})
    return ClickhousePersonSerializer(result, many=True).data


def get_person_distinct_ids(team_id: int):
    result = sync_execute(GET_DISTINCT_IDS_SQL, {"team_id": team_id})
    return ClickhousePersonDistinctIdSerializer(result, many=True).data


def get_person_by_distinct_id(team: Team, distinct_id: str, filter: Optional[Filter] = None) -> Dict[str, Any]:
    params = {"team_id": team.pk, "distinct_id": distinct_id.__str__()}
    filter_query = ""
    if filter:
        filter_query, filter_params = parse_prop_clauses(filter.properties, team.pk, table_name="pid")
        params = {**params, **filter_params}
    result = sync_execute(GET_PERSON_BY_DISTINCT_ID.format(distinct_query=filter_query, query=""), params)
    if len(result) > 0:
        return ClickhousePersonSerializer(result[0], many=False).data
    return {}


def get_persons_by_distinct_ids(team_id: int, distinct_ids: List[str]) -> QuerySet:
    return Person.objects.filter(
        team_id=team_id, persondistinctid__team_id=team_id, persondistinctid__distinct_id__in=distinct_ids
    )


def get_persons_by_uuids(team_id: int, uuids: List[str]) -> QuerySet:
    return Person.objects.filter(team_id=team_id, uuid__in=uuids)


def merge_people(team_id: int, target: Dict, old_id: UUID, old_props: Dict) -> None:
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


def delete_person(person_id: UUID, delete_events: bool = False, team_id: int = False) -> None:
    try:
        if delete_events:
            sync_execute(DELETE_PERSON_EVENTS_BY_ID, {"id": person_id, "team_id": team_id})
    except:
        pass  # cannot delete if the table is distributed

    sync_execute(DELETE_PERSON_BY_ID, {"id": person_id,})
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
