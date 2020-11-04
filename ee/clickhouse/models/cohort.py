from typing import Any, Dict, Tuple

from ee.clickhouse.models.action import format_action_filter
from ee.clickhouse.models.util import get_operator
from ee.clickhouse.sql.cohort import CALCULATE_COHORT_PEOPLE_SQL
from ee.clickhouse.sql.person import GET_LATEST_PERSON_ID_SQL
from posthog.models import Action, Cohort, Filter


def format_person_query(cohort: Cohort) -> Tuple[str, Dict[str, Any]]:
    filters = []
    params: Dict[str, Any] = {}
    for group_idx, group in enumerate(cohort.groups):
        if group.get("action_id"):
            action = Action.objects.get(pk=group["action_id"], team_id=cohort.team.pk)
            action_filter_query, action_params = format_action_filter(action)
            extract_person = "SELECT distinct_id FROM events WHERE {query}".format(query=action_filter_query)
            params = {**params, **action_params}
            filters.append("(" + extract_person + ")")

        elif group.get("properties"):
            from ee.clickhouse.models.property import prop_filter_json_extract

            filter = Filter(data=group)
            query = ""
            for idx, prop in enumerate(filter.properties):
                filter_query, filter_params = prop_filter_json_extract(
                    prop=prop, idx=idx, prepend="{}_{}_{}_person".format(cohort.pk, group_idx, idx)
                )
                params = {**params, **filter_params}
                query += " {}".format(filter_query)
            filters.append(GET_LATEST_PERSON_ID_SQL.format(query=query))

    joined_filter = " OR person_id IN ".join(filters)
    return joined_filter, params


def format_filter_query(cohort: Cohort) -> Tuple[str, Dict[str, Any]]:
    person_query, params = format_person_query(cohort)
    person_id_query = CALCULATE_COHORT_PEOPLE_SQL.format(query=person_query)
    return person_id_query, params
