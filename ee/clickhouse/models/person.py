import json
from typing import Dict, List
from uuid import UUID, uuid4

from ee.clickhouse.client import ch_client
from ee.clickhouse.sql.person import INSERT_PERSON_DISTINCT_ID, INSERT_PERSON_SQL, PERSON_DISTINCT_ID_EXISTS_SQL
from posthog.models.team import Team


def create_person(team: Team, id: UUID = uuid4(), properties: Dict = {}) -> UUID:
    ch_client.execute(INSERT_PERSON_SQL, {"id": id, "properties": json.dumps(properties), "team_id": team.pk})
    return id


def create_person_distinct_id(team: Team, distinct_id: str, person_id: UUID) -> None:
    ch_client.execute(
        INSERT_PERSON_DISTINCT_ID, {"distinct_id": distinct_id, "person_id": person_id, "team_id": team.pk}
    )


def distinct_ids_exist(ids: List[str]) -> bool:
    return bool(ch_client.execute(PERSON_DISTINCT_ID_EXISTS_SQL.format(ids))[0][0])


def check_and_create_person_distinct_ids(ids: List[str], team=Team) -> None:
    if not distinct_ids_exist(ids):
        person_id = create_person(team=team)
        for id in ids:
            create_person_distinct_id(distinct_id=id, person_id=person_id, team=team)
