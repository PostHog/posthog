from typing import Dict, List

from ee.clickhouse.client import ch_client
from ee.clickhouse.sql.person import INSERT_PERSON_DISTINCT_ID, INSERT_PERSON_SQL, PERSON_DISTINCT_ID_EXISTS_SQL
from posthog.models.team import Team


def create_person(team_id: int, id: int) -> int:
    print(INSERT_PERSON_SQL, {"id": id, "team_id": team_id})
    ch_client.execute(INSERT_PERSON_SQL, {"id": id, "team_id": team_id})
    return id


def create_person_distinct_id(team_id: Team, distinct_id: str, person_id: int) -> None:
    ch_client.execute(
        INSERT_PERSON_DISTINCT_ID, {"distinct_id": distinct_id, "person_id": person_id, "team_id": team_id}
    )


def distinct_ids_exist(ids: List[str]) -> bool:
    return bool(ch_client.execute(PERSON_DISTINCT_ID_EXISTS_SQL.format(ids))[0][0])


def create_person_with_distinct_id(person_id: int, distinct_ids: List[str], team_id: int) -> None:
    create_person(id=person_id, team_id=team_id)
    attach_distinct_ids(person_id, distinct_ids, team_id)


def attach_distinct_ids(person_id: int, distinct_ids: List[str], team_id: int) -> None:
    for distinct_id in distinct_ids:
        ch_client.execute(
            INSERT_PERSON_DISTINCT_ID, {"person_id": person_id, "team_id": team_id, "distinct_id": str(distinct_id)}
        )
