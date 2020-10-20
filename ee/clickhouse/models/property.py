from typing import Any, Dict, List, Optional, Tuple

from ee.clickhouse.client import sync_execute
from ee.clickhouse.models.cohort import format_filter_query
from ee.clickhouse.models.util import get_operator
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
            final += "AND distinct_id IN ({clause}) ".format(clause=person_id_query)

        elif prop.type == "person":

            prepend = "person"

            arg = "v{}_{}".format(prepend, idx)
            operator_clause, value = get_operator(prop, arg)

            filter = "(ep.key = %(k{prepend}_{idx})s) AND {operator_clause}".format(
                idx=idx, operator_clause=operator_clause, prepend=prepend
            )
            clause = GET_DISTINCT_IDS_BY_PROPERTY_SQL.format(
                filters=filter, negation="NOT " if prop.operator and "not" in prop.operator else ""
            )
            final += "AND distinct_id IN ({clause}) ".format(clause=clause)
            params.update({"k{}_{}".format(prepend, idx): prop.key, arg: value})
        else:

            arg = "v{}_{}".format(prepend, idx)
            operator_clause, value = get_operator(prop, arg)

            filter = "(ep.key = %(k{prepend}_{idx})s) {and_statement} {operator_clause}".format(
                idx=idx,
                and_statement="AND" if operator_clause else "",
                operator_clause=operator_clause,
                prepend=prepend,
            )
            clause = EVENT_PROP_CLAUSE.format(team_id=team.pk, filters=filter)
            final += "{cond} ({clause}) AND team_id = %(team_id)s ".format(
                cond="AND {key} {negation}IN".format(
                    key=key, negation="NOT " if prop.operator and "not" in prop.operator else "",
                ),
                clause=clause,
            )
            params.update({"k{}_{}".format(prepend, idx): prop.key, arg: value})

    return final, params


def get_property_values_for_key(key: str, team: Team, value: Optional[str] = None):
    if value:
        return sync_execute(
            SELECT_PROP_VALUES_SQL_WITH_FILTER, {"team_id": team.pk, "key": key, "value": "%{}%".format(value)},
        )
    return sync_execute(SELECT_PROP_VALUES_SQL, {"team_id": team.pk, "key": key})
