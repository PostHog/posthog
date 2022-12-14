from posthog.models.person.sql import GET_TEAM_PERSON_DISTINCT_IDS


def get_team_distinct_ids_query(team_id: int) -> str:
    from posthog.client import substitute_params

    return substitute_params(GET_TEAM_PERSON_DISTINCT_IDS, {"team_id": team_id})
