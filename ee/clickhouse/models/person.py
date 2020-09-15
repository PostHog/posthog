import json
from typing import Dict, List, Optional

from rest_framework import serializers

from ee.clickhouse.client import async_execute, sync_execute
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
from posthog.models.person import Person
from posthog.models.team import Team


def create_person(
    team_id: int, distinct_ids: List[str], properties: Optional[Dict] = {}, sync: bool = False, **kwargs
) -> int:
    person_id = kwargs.get("person_id", None)  # type: Optional[str]
    if not person_id:
        person_id = generate_clickhouse_uuid()

    if sync:
        sync_execute(INSERT_PERSON_SQL, {"id": person_id, "team_id": team_id, "properties": json.dumps(properties)})
    else:
        async_execute(INSERT_PERSON_SQL, {"id": person_id, "team_id": team_id, "properties": json.dumps(properties)})

    for distinct_id in distinct_ids:
        if not distinct_ids_exist(team_id, [distinct_id]):
            create_person_distinct_id(team_id=team_id, distinct_id=distinct_id, person_id=person_id)

    return person_id


def update_person_properties(team_id: int, id: int, properties: Dict) -> None:
    async_execute(UPDATE_PERSON_PROPERTIES, {"team_id": team_id, "id": id, "properties": json.dumps(properties)})


def update_person_is_identified(team_id: int, id: int, is_identified: bool) -> None:
    async_execute(
        UPDATE_PERSON_IS_IDENTIFIED, {"team_id": team_id, "id": id, "is_identified": "1" if is_identified else "0"}
    )


def create_person_distinct_id(team_id: Team, distinct_id: str, person_id: str) -> None:
    async_execute(INSERT_PERSON_DISTINCT_ID, {"distinct_id": distinct_id, "person_id": person_id, "team_id": team_id})


def distinct_ids_exist(team_id: int, ids: List[str]) -> bool:
    return bool(sync_execute(PERSON_DISTINCT_ID_EXISTS_SQL.format([str(id) for id in ids]), {"team_id": team_id})[0][0])


def person_exists(id: int) -> bool:
    return bool(sync_execute(PERSON_EXISTS_SQL, {"id": id})[0][0])


def attach_distinct_ids(person_id: str, distinct_ids: List[str], team_id: int) -> None:
    for distinct_id in distinct_ids:
        async_execute(
            INSERT_PERSON_DISTINCT_ID, {"person_id": person_id, "team_id": team_id, "distinct_id": str(distinct_id)}
        )


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
    properties = {}
    # merge the properties
    properties = {**old_props, **target["properties"]}

    update_person_properties(team_id=team_id, id=target["id"], properties=properties)

    other_person_distinct_ids = sync_execute(
        GET_DISTINCT_IDS_SQL_BY_ID, {"person_id": old_id, "team_id": target["team_id"]}
    )

    parsed_other_person_distinct_ids = ClickhousePersonDistinctIdSerializer(other_person_distinct_ids, many=True).data

    for person_distinct_id in parsed_other_person_distinct_ids:
        async_execute(
            UPDATE_PERSON_ATTACHED_DISTINCT_ID,
            {"person_id": target["id"], "distinct_id": person_distinct_id["distinct_id"]},
        )

    async_execute(DELETE_PERSON_BY_ID, {"id": old_id,})


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
        return person[4]


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
