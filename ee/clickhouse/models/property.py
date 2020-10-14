from typing import Any, Dict, List, Optional, Tuple

from ee.clickhouse.client import sync_execute
from ee.clickhouse.models.cohort import format_filter_query
from ee.clickhouse.sql.events import EVENT_PROP_CLAUSE, SELECT_PROP_VALUES_SQL, SELECT_PROP_VALUES_SQL_WITH_FILTER
from ee.clickhouse.sql.person import GET_DISTINCT_IDS_BY_PROPERTY_SQL
from posthog.models.cohort import Cohort
from posthog.models.property import Property
from posthog.models.team import Team


def parse_prop_clauses(key: str, filters: List[Property], team: Team, prepend: str = "") -> Tuple[str, Dict]:
    final = ""
    params: Dict[str, Any] = {}
    for idx, prop in enumerate(filters):

        if prop.type == "cohort":
            cohort = Cohort.objects.get(pk=prop.value)
            person_id_query, cohort_filter_params = format_filter_query(cohort)
            params = {**params, **cohort_filter_params}
            final += "{cond} ({clause}) ".format(cond="AND distinct_id IN", clause=person_id_query)

        elif prop.type == "person":

            prepend = "person"

            arg = "v{}_{}".format(prepend, idx)
            operator_clause, value = get_operator(prop, arg)

            filter = "(ep.key = %(k{prepend}_{idx})s) AND {operator_clause}".format(
                idx=idx, operator_clause=operator_clause, prepend=prepend
            )
            clause = GET_DISTINCT_IDS_BY_PROPERTY_SQL.format(filters=filter)
            final += "{cond} ({clause}) ".format(cond="AND distinct_id IN", clause=clause)
            params.update({"k{}_{}".format(prepend, idx): prop.key, arg: prop.value})

        else:

            arg = "v{}_{}".format(prepend, idx)
            operator_clause, value = get_operator(prop, arg)

            filter = "(ep.key = %(k{prepend}_{idx})s) AND {operator_clause}".format(
                idx=idx, operator_clause=operator_clause, prepend=prepend
            )
            clause = EVENT_PROP_CLAUSE.format(team_id=team.pk, filters=filter)
            final += "{cond} ({clause}) ".format(cond="AND {key} IN".format(key=key), clause=clause)
            params.update({"k{}_{}".format(prepend, idx): prop.key, arg: value})

    return final, params


def get_operator(prop: Property, arg: str):
    operator = prop.operator

    if operator == "is_not":
        return "(trim(BOTH '\"' FROM ep.value) != %({})s)".format(arg), prop.value
    elif operator == "icontains":
        value = "%{}%".format(prop.value)
        return "(trim(BOTH '\"' FROM ep.value) LIKE %({})s)".format(arg), value
    elif operator == "not_icontains":
        value = "%{}%".format(prop.value)
        return "(trim(BOTH '\"' FROM ep.value) NOT LIKE %({})s)".format(arg), value
    elif operator == "regex":
        return "match(trim(BOTH '\"' FROM ep.value), %({})s)".format(arg), prop.value
    elif operator == "not_regex":
        return "NOT match(trim(BOTH '\"' FROM ep.value), %({})s)".format(arg), prop.value
    elif operator == "gt":
        return "(trim(BOTH '\"' FROM ep.value) >  %({})s)".format(arg), prop.value
    elif operator == "lt":
        return "(trim(BOTH '\"' FROM ep.value) <  %({})s)".format(arg), prop.value
    else:
        return "(trim(BOTH '\"' FROM ep.value) =  %({})s)".format(arg), prop.value


def get_property_values_for_key(key: str, team: Team, value: Optional[str] = None):
    if value:
        return sync_execute(
            SELECT_PROP_VALUES_SQL_WITH_FILTER, {"team_id": team.pk, "key": key, "value": "%{}%".format(value)}
        )
    return sync_execute(SELECT_PROP_VALUES_SQL, {"team_id": team.pk, "key": key})
