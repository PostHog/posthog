from typing import Any, Dict, Tuple

from ee.clickhouse.models.action import format_action_filter
from ee.clickhouse.sql.cohort import CALCULATE_COHORT_PEOPLE_SQL, PERSON_PROPERTY_FILTER_SQL
from posthog.models import Action, Cohort, Filter


def format_filter_query(cohort: Cohort) -> Tuple[str, Dict]:
    filters = []
    params: Dict[str, Any] = {}
    for group in cohort.groups:
        if group.get("action_id"):
            action = Action.objects.get(pk=group["action_id"], team_id=cohort.team.pk)
            action_filter_query, action_params = format_action_filter(action)
            extract_person = "SELECT distinct_id FROM events WHERE uuid IN ({query})".format(query=action_filter_query)
            params = {**params, **action_params}
            filters.append("(" + extract_person + ")")
        elif group.get("properties"):
            filter = Filter(data=group)
            prop_filter = filter.format_ch(team_id=cohort.team.pk)
            extract_distinct_id = "SELECT distinct_id FROM person_distinct_id WHERE person_id IN ({query})".format(
                query=PERSON_PROPERTY_FILTER_SQL.format(filters=prop_filter)
            )
            filters.append("(" + extract_distinct_id + ")")

    separator = " OR distinct_id IN "
    joined_filter = separator.join(filters)
    person_id_query = CALCULATE_COHORT_PEOPLE_SQL.format(query=joined_filter)
    return person_id_query, params
