from typing import Any, Dict, Tuple

from ee.clickhouse.models.action import format_action_filter
from ee.clickhouse.models.util import get_operator
from ee.clickhouse.sql.cohort import CALCULATE_COHORT_PEOPLE_SQL
from ee.clickhouse.sql.person import GET_DISTINCT_IDS_BY_PROPERTY_SQL
from posthog.models import Action, Cohort, Filter


def format_filter_query(cohort: Cohort) -> Tuple[str, Dict[str, Any]]:
    filters = []
    params: Dict[str, Any] = {}
    for group_idx, group in enumerate(cohort.groups):
        if group.get("action_id"):
            action = Action.objects.get(pk=group["action_id"], team_id=cohort.team.pk)
            action_filter_query, action_params = format_action_filter(action)
            extract_person = "SELECT distinct_id FROM events WHERE uuid IN ({query})".format(query=action_filter_query)
            params = {**params, **action_params}
            filters.append("(" + extract_person + ")")

        elif group.get("properties"):
            filter = Filter(data=group)
            props = []

            for idx, prop in enumerate(filter.properties):
                prepend = "{}_cohort_group_{}".format(cohort.pk, group_idx)

                arg = "v{}_{}".format(prepend, idx)
                operator_clause, value = get_operator(prop, arg)

                key_statement = "(ep.key = %(k{prepend}_{idx})s)".format(idx=idx, prepend=prepend)
                prop_filters = "{key_statement} AND {operator_clause}".format(
                    key_statement=key_statement, operator_clause=operator_clause
                )
                clause = GET_DISTINCT_IDS_BY_PROPERTY_SQL.format(
                    key_statement=key_statement,
                    filters=prop_filters,
                    negation="NOT " if prop.operator and "not" in prop.operator else "",
                )

                props.append("(" + clause + ")")
                params.update({"k{}_{}".format(prepend, idx): prop.key, arg: value})

            prop_separator = " AND distinct_id IN "
            joined_prop_filter = prop_separator.join(props)
            final_prop_query = CALCULATE_COHORT_PEOPLE_SQL.format(query=joined_prop_filter)
            filters.append("(" + final_prop_query + ")")

    separator = " OR distinct_id IN "
    joined_filter = separator.join(filters)
    person_id_query = CALCULATE_COHORT_PEOPLE_SQL.format(query=joined_filter)
    return person_id_query, params
