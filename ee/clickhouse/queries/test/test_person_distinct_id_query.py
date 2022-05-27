from posthog.queries import person_distinct_id_query


def test_person_distinct_id_query(db, snapshot):
    person_distinct_id_query.using_new_table = True
    assert person_distinct_id_query.get_team_distinct_ids_query(2) == snapshot

    person_distinct_id_query.using_new_table = False
    assert person_distinct_id_query.get_team_distinct_ids_query(2) == snapshot

    # Reset for other tests
    person_distinct_id_query.using_new_table = True
