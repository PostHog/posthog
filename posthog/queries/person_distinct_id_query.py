from posthog.models.person.sql import GET_TEAM_PERSON_DISTINCT_IDS


def get_team_distinct_ids_query(team_id: int) -> str:
    # ensure team_id is actually an int so we can safely interpolate into the query
    assert isinstance(team_id, int)

    return GET_TEAM_PERSON_DISTINCT_IDS % {"team_id": team_id}
