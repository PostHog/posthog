from typing import Dict, List

from rest_framework import serializers

from ee.clickhouse.client import ch_client
from ee.clickhouse.sql.person import (
    GET_DISTINCT_IDS_SQL,
    GET_PERSON_SQL,
    INSERT_PERSON_DISTINCT_ID,
    INSERT_PERSON_SQL,
    PERSON_DISTINCT_ID_EXISTS_SQL,
    PERSON_EXISTS_SQL,
)
from posthog.models.team import Team


def create_person(team_id: int, id: int) -> int:
    print(INSERT_PERSON_SQL, {"id": id, "team_id": team_id})
    ch_client.execute(INSERT_PERSON_SQL, {"id": id, "team_id": team_id})
    return id


def create_person_distinct_id(team_id: Team, distinct_id: str, person_id: int) -> None:
    ch_client.execute(
        INSERT_PERSON_DISTINCT_ID, {"distinct_id": distinct_id, "person_id": person_id, "team_id": team_id}
    )


def distinct_ids_exist(team_id: int, ids: List[str]) -> bool:
    return bool(
        ch_client.execute(PERSON_DISTINCT_ID_EXISTS_SQL.format([str(id) for id in ids]), {"team_id": team_id})[0][0]
    )


def person_exists(id: int) -> bool:
    return bool(ch_client.execute(PERSON_EXISTS_SQL, {"id": id})[0][0])


def create_person_with_distinct_id(person_id: int, distinct_ids: List[str], team_id: int) -> None:
    if not person_exists(person_id):
        create_person(id=person_id, team_id=team_id)
    if not distinct_ids_exist(team_id, distinct_ids):
        attach_distinct_ids(person_id, distinct_ids, team_id)


def attach_distinct_ids(person_id: int, distinct_ids: List[str], team_id: int) -> None:
    for distinct_id in distinct_ids:
        ch_client.execute(
            INSERT_PERSON_DISTINCT_ID, {"person_id": person_id, "team_id": team_id, "distinct_id": str(distinct_id)}
        )


def get_persons():
    result = ch_client.execute(GET_PERSON_SQL)
    return ClickhousePersonSerializer(result, many=True).data


def get_person_distinct_ids():
    result = ch_client.execute(GET_DISTINCT_IDS_SQL)
    return ClickhousePersonDistinctIdSerializer(result, many=True).data


class ClickhousePersonSerializer(serializers.Serializer):
    id = serializers.SerializerMethodField()
    created_at = serializers.SerializerMethodField()
    team_id = serializers.SerializerMethodField()

    def get_id(self, person):
        return person[0]

    def get_created_at(self, person):
        return person[1]

    def get_team_id(self, person):
        return person[2]


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
