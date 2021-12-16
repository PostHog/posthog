from django.conf import settings

from ee.clickhouse.sql.person import GET_TEAM_PERSON_DISTINCT_IDS, GET_TEAM_PERSON_DISTINCT_IDS_NEW_TABLE


def get_team_distinct_ids_query(team_id: int) -> str:
    from ee.clickhouse.client import render_query

    if str(team_id) in settings.PERSON_DISTINCT_ID_OPTIMIZATION_TEAM_IDS:
        return render_query(GET_TEAM_PERSON_DISTINCT_IDS_NEW_TABLE, params={"team_id": team_id})
    else:
        return render_query(GET_TEAM_PERSON_DISTINCT_IDS, params={"team_id": team_id})
