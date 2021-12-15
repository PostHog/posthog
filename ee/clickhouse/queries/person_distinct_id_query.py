from django.conf import settings

from ee.clickhouse.sql.person import GET_TEAM_PERSON_DISTINCT_IDS, GET_TEAM_PERSON_DISTINCT_IDS_NEW_TABLE


def get_team_distinct_ids_query(team_id: int) -> str:
    from ee.clickhouse.client import substitute_params

    if str(team_id) in settings.PERSON_DISTINCT_ID_OPTIMIZATION_TEAM_IDS:
        return substitute_params(GET_TEAM_PERSON_DISTINCT_IDS_NEW_TABLE, {"team_id": team_id})
    else:
        return substitute_params(GET_TEAM_PERSON_DISTINCT_IDS, {"team_id": team_id})
