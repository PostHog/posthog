from ee.clickhouse.queries.person_distinct_id_query import get_team_distinct_ids_query


def test_person_distinct_id_query(settings, snapshot):
    settings.PERSON_DISTINCT_ID_OPTIMIZATION_TEAM_IDS = ["220"]
    assert get_team_distinct_ids_query(2) == snapshot
    assert get_team_distinct_ids_query(220) == snapshot
