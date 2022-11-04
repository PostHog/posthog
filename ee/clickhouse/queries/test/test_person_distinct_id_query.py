from posthog.queries import person_distinct_id_query


def test_person_distinct_id_query(db, snapshot):
    assert person_distinct_id_query.get_team_distinct_ids_query(2) == snapshot
