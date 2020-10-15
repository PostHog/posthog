from typing import Any, Dict, List, Optional, Tuple

from ee.clickhouse.client import sync_execute
from ee.clickhouse.models.cohort import format_filter_query
from ee.clickhouse.sql.cohort import COHORT_DISTINCT_ID_FILTER_SQL
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
            filter = "(ep.key = %(k{prepend}_{idx})s) AND (ep.value {operator} %(v{prepend}_{idx})s)".format(
                idx=idx, operator=get_operator(prop.operator), prepend=prepend
            )
            clause = GET_DISTINCT_IDS_BY_PROPERTY_SQL.format(filters=filter)
            final += "{cond} ({clause}) ".format(cond="AND distinct_id IN", clause=clause)
            params.update(
                {"k{}_{}".format(prepend, idx): prop.key, "v{}_{}".format(prepend, idx): _pad_value(prop.value)}
            )

        else:
            filter = "(ep.key = %(k{prepend}_{idx})s) AND (ep.value {operator} %(v{prepend}_{idx})s)".format(
                idx=idx, operator=get_operator(prop.operator), prepend=prepend
            )
            clause = EVENT_PROP_CLAUSE.format(team_id=team.pk, filters=filter)
            final += "{cond} ({clause}) ".format(cond="AND {key} IN".format(key=key), clause=clause)
            params.update(
                {"k{}_{}".format(prepend, idx): prop.key, "v{}_{}".format(prepend, idx): _pad_value(prop.value)}
            )

    return final, params


def _pad_value(val: str):

    if val == "true" or val == "false" or val.isdigit():
        return val

    if not val.startswith('"'):
        val = '"' + val

    if not val.endswith('"'):
        val = val + '"'

    return val


# TODO: handle all operators
def get_operator(operator: Optional[str]):
    if operator == "is_not":
        return "!="
    elif operator == "icontains":
        return "LIKE"
    elif operator == "not_icontains":
        return "NOT LIKE"
    elif operator == "regex":
        return "="
    elif operator == "not_regex":
        return "="
    elif operator == "gt":
        return ">"
    elif operator == "lt":
        return "<"
    else:
        return "="


def get_property_values_for_key(key: str, team: Team, value: Optional[str] = None):
    if value:
        return sync_execute(
            SELECT_PROP_VALUES_SQL_WITH_FILTER, {"team_id": team.pk, "key": key, "value": "%{}%".format(value)}
        )
    return sync_execute(SELECT_PROP_VALUES_SQL, {"team_id": team.pk, "key": key})
