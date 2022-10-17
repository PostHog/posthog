from posthog.models.person.sql import GET_TEAM_PERSON_DISTINCT_IDS_NEW_TABLE


def get_team_distinct_ids_query(team_id: int) -> str:
    from posthog.client import substitute_params

    return substitute_params(GET_TEAM_PERSON_DISTINCT_IDS_NEW_TABLE, {"team_id": team_id})
