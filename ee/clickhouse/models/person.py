import json
from typing import Dict, List, Optional

from rest_framework import serializers

from ee.clickhouse.client import async_execute, sync_execute
from ee.clickhouse.sql.person import (
    DELETE_PERSON_BY_ID,
    GET_DISTINCT_IDS_SQL,
    GET_DISTINCT_IDS_SQL_BY_ID,
    GET_PERSON_SQL,
    INSERT_PERSON_DISTINCT_ID,
    INSERT_PERSON_SQL,
    PERSON_DISTINCT_ID_EXISTS_SQL,
    PERSON_EXISTS_SQL,
    UPDATE_PERSON_ATTACHED_DISTINCT_ID,
    UPDATE_PERSON_PROPERTIES,
)
from posthog.models.person import Person
from posthog.models.team import Team


def create_person(team_id: int, id: int, properties: Optional[Dict] = {}) -> int:
    async_execute(INSERT_PERSON_SQL, {"id": id, "team_id": team_id, "properties": json.dumps(properties)})
    return id


def update_person_properties(id: int, properties: Dict) -> None:
    async_execute(UPDATE_PERSON_PROPERTIES, {"id": id, "properties": json.dumps(properties)})


def create_person_distinct_id(team_id: Team, distinct_id: str, person_id: int) -> None:
    async_execute(INSERT_PERSON_DISTINCT_ID, {"distinct_id": distinct_id, "person_id": person_id, "team_id": team_id})


def distinct_ids_exist(team_id: int, ids: List[str]) -> bool:
    return bool(sync_execute(PERSON_DISTINCT_ID_EXISTS_SQL.format([str(id) for id in ids]), {"team_id": team_id})[0][0])


def person_exists(id: int) -> bool:
    return bool(sync_execute(PERSON_EXISTS_SQL, {"id": id})[0][0])


def create_person_with_distinct_id(
    person_id: int, distinct_ids: List[str], team_id: int, properties: Optional[Dict] = {}
) -> None:
    if not person_exists(person_id):
        create_person(id=person_id, team_id=team_id, properties=properties)
    if not distinct_ids_exist(team_id, distinct_ids):
        attach_distinct_ids(person_id, distinct_ids, team_id)


def attach_distinct_ids(person_id: int, distinct_ids: List[str], team_id: int) -> None:
    for distinct_id in distinct_ids:
        async_execute(
            INSERT_PERSON_DISTINCT_ID, {"person_id": person_id, "team_id": team_id, "distinct_id": str(distinct_id)}
        )


def get_persons():
    result = sync_execute(GET_PERSON_SQL)
    return ClickhousePersonSerializer(result, many=True).data


def get_person_distinct_ids():
    result = sync_execute(GET_DISTINCT_IDS_SQL)
    return ClickhousePersonDistinctIdSerializer(result, many=True).data


def merge_people(target: Person, old_id: int, old_props: Dict) -> None:
    properties = {}
    # merge the properties
    properties = {**old_props, **target.properties}

    update_person_properties(target.pk, properties)

    other_person_distinct_ids = sync_execute(
        GET_DISTINCT_IDS_SQL_BY_ID, {"person_id": old_id, "team_id": target.team.pk}
    )

    parsed_other_person_distinct_ids = ClickhousePersonDistinctIdSerializer(other_person_distinct_ids, many=True).data

    for person_distinct_id in parsed_other_person_distinct_ids:
        async_execute(
            UPDATE_PERSON_ATTACHED_DISTINCT_ID,
            {"person_id": target.pk, "distinct_id": person_distinct_id["distinct_id"]},
        )

    async_execute(DELETE_PERSON_BY_ID, {"id": old_id,})


class ClickhousePersonSerializer(serializers.Serializer):
    id = serializers.SerializerMethodField()
    created_at = serializers.SerializerMethodField()
    team_id = serializers.SerializerMethodField()
    properties = serializers.SerializerMethodField()

    def get_id(self, person):
        return person[0]

    def get_created_at(self, person):
        return person[1]

    def get_team_id(self, person):
        return person[2]

    def get_properties(self, person):
        return person[3]


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
