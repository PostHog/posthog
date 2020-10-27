from typing import Any, Dict, List, Optional, Tuple

from ee.clickhouse.client import sync_execute
from ee.clickhouse.models.cohort import format_filter_query
from ee.clickhouse.models.util import get_operator, is_json
from ee.clickhouse.sql.events import EVENT_PROP_CLAUSE, SELECT_PROP_VALUES_SQL, SELECT_PROP_VALUES_SQL_WITH_FILTER
from ee.clickhouse.sql.person import GET_DISTINCT_IDS_BY_PROPERTY_SQL
from posthog.models.cohort import Cohort
from posthog.models.property import Property
from posthog.models.team import Team


def parse_prop_clauses(
    key: str, filters: List[Property], team: Team, prepend: str = "", json_extract: bool = False
) -> Tuple[str, Dict]:
    final = ""
    params: Dict[str, Any] = {}
    for idx, prop in enumerate(filters):

        if prop.type == "cohort":
            cohort = Cohort.objects.get(pk=prop.value)
            person_id_query, cohort_filter_params = format_filter_query(cohort)
            params = {**params, **cohort_filter_params}
            final += "AND distinct_id IN ({clause}) ".format(clause=person_id_query)

        elif prop.type == "person":

            if json_extract:
                filter_query, filter_params = prop_filter_json_extract(prop, idx, "person", "person_properties")
                final += " {filter_query} AND team_id = %(team_id)s".format(filter_query=filter_query)
                params.update(filter_params)
            else:
                filter_query, filter_params = person_prop_filter_kv(prop, idx)
                final += " {filter_query}".format(filter_query=filter_query)
                params.update(filter_params)
        else:

            if json_extract:
                filter_query, filter_params = prop_filter_json_extract(prop, idx, prepend)
                final += " {filter_query} AND team_id = %(team_id)s".format(filter_query=filter_query)
                params.update(filter_params)
            else:
                filter_query, filter_params = prop_filter_kv(key, prop, team, idx, prepend)
                final += " {filter_query}".format(filter_query=filter_query)
                params.update(filter_params)
    return final, params


def prop_filter_json_extract(
    prop: Property, idx: int, prepend: str = "", prop_var: str = "properties"
) -> Tuple[str, Dict[str, Any]]:
    operator = prop.operator

    if operator == "is_not":
        params = {"k{}_{}".format(prepend, idx): prop.key, "v{}_{}".format(prepend, idx): prop.value}
        return (
            "AND NOT (JSONExtractString({prop_var}, %(k{prepend}_{idx})s) = %(v{prepend}_{idx})s)".format(
                idx=idx, prepend=prepend, prop_var=prop_var
            ),
            params,
        )
    elif operator == "icontains":
        value = "%{}%".format(prop.value)
        params = {"k{}_{}".format(prepend, idx): prop.key, "v{}_{}".format(prepend, idx): value}
        return (
            "AND JSONExtractString({prop_var}, %(k{prepend}_{idx})s) LIKE %(v{prepend}_{idx})s".format(
                idx=idx, prepend=prepend, prop_var=prop_var
            ),
            params,
        )
    elif operator == "not_icontains":
        value = "%{}%".format(prop.value)
        params = {"k{}_{}".format(prepend, idx): prop.key, "v{}_{}".format(prepend, idx): value}
        return (
            "AND NOT (JSONExtractString({prop_var}, %(k{prepend}_{idx})s) LIKE %(v{prepend}_{idx})s)".format(
                idx=idx, prepend=prepend, prop_var=prop_var
            ),
            params,
        )
    elif operator == "regex":
        params = {"k{}_{}".format(prepend, idx): prop.key, "v{}_{}".format(prepend, idx): prop.value}
        return (
            "AND match(JSONExtractString({prop_var}, %(k{prepend}_{idx})s), %(v{prepend}_{idx})s)".format(
                idx=idx, prepend=prepend, prop_var=prop_var
            ),
            params,
        )
    elif operator == "not_regex":
        params = {"k{}_{}".format(prepend, idx): prop.key, "v{}_{}".format(prepend, idx): prop.value}
        return (
            "AND NOT match(JSONExtractString({prop_var}, %(k{prepend}_{idx})s), %(v{prepend}_{idx})s)".format(
                idx=idx, prepend=prepend, prop_var=prop_var
            ),
            params,
        )
    elif operator == "is_set":
        params = {"k{}_{}".format(prepend, idx): prop.key, "v{}_{}".format(prepend, idx): prop.value}
        return (
            "AND isNotNull(JSONExtractString({prop_var}, %(k{prepend}_{idx})s)".format(
                idx=idx, prepend=prepend, prop_var=prop_var
            ),
            params,
        )
    elif operator == "is_not_set":
        params = {"k{}_{}".format(prepend, idx): prop.key, "v{}_{}".format(prepend, idx): prop.value}
        return (
            "AND isNull(JSONExtractString({prop_var}, %(k{prepend}_{idx})s)".format(
                idx=idx, prepend=prepend, prop_var=prop_var
            ),
            params,
        )
    elif operator == "gt":
        params = {"k{}_{}".format(prepend, idx): prop.key, "v{}_{}".format(prepend, idx): prop.value}
        return (
            "AND toInt64(JSONExtractString({prop_var}, %(k{prepend}_{idx})s)) > %(v{prepend}_{idx})s".format(
                idx=idx, prepend=prepend, prop_var=prop_var
            ),
            params,
        )
    elif operator == "lt":
        params = {"k{}_{}".format(prepend, idx): prop.key, "v{}_{}".format(prepend, idx): prop.value}
        return (
            "AND toInt64(JSONExtractString({prop_var}, %(k{prepend}_{idx})s)) < %(v{prepend}_{idx})s".format(
                idx=idx, prepend=prepend, prop_var=prop_var
            ),
            params,
        )
    else:
        if is_json(prop.value):
            params = {"k{}_{}".format(prepend, idx): prop.key, "v{}_{}".format(prepend, idx): prop.value}
            return (
                "replaceRegexpAll(JSONExtractString({prop_var}, %(k{prepend}_{idx})s),' ', '') = replaceRegexpAll(toString(%(v{prepend}_{idx})s),' ', '')".format(
                    idx=idx, prepend=prepend, prop_var=prop_var
                ),
                params,
            )
        else:
            params = {"k{}_{}".format(prepend, idx): prop.key, "v{}_{}".format(prepend, idx): prop.value}
            return (
                "AND JSONExtractString({prop_var}, %(k{prepend}_{idx})s) = %(v{prepend}_{idx})s".format(
                    idx=idx, prepend=prepend, prop_var=prop_var
                ),
                params,
            )


def person_prop_filter_kv(prop: Property, idx: int, prepend: str = "person") -> Tuple[str, Dict[str, Any]]:

    arg = "v{}_{}".format(prepend, idx)
    operator_clause, value = get_operator(prop, arg)

    params = {"k{}_{}".format(prepend, idx): prop.key, arg: value}

    key_statement = "(ep.key = %(k{prepend}_{idx})s)".format(idx=idx, prepend=prepend)
    filter = "{key_statement} {and_statement} {operator_clause}".format(
        key_statement=key_statement, and_statement="AND" if operator_clause else "", operator_clause=operator_clause,
    )
    clause = GET_DISTINCT_IDS_BY_PROPERTY_SQL.format(
        key_statement=key_statement,
        filters=filter,
        negation="NOT " if prop.operator and "not" in prop.operator else "",
    )
    filter_query = "AND distinct_id IN ({clause}) ".format(clause=clause)

    return filter_query, params


def prop_filter_kv(key: str, prop: Property, team: Team, idx: int, prepend: str = "") -> Tuple[str, Dict[str, Any]]:
    arg = "v{}_{}".format(prepend, idx)
    operator_clause, value = get_operator(prop, arg)

    params = {"k{}_{}".format(prepend, idx): prop.key, arg: value}

    filter = "(ep.key = %(k{prepend}_{idx})s) {and_statement} {operator_clause}".format(
        idx=idx, and_statement="AND" if operator_clause else "", operator_clause=operator_clause, prepend=prepend,
    )
    clause = EVENT_PROP_CLAUSE.format(team_id=team.pk, filters=filter)
    filter_query = "{cond} ({clause}) AND team_id = %(team_id)s ".format(
        cond="AND {key} {negation}IN".format(
            key=key, negation="NOT " if prop.operator and "not" in prop.operator else "",
        ),
        clause=clause,
    )

    return filter_query, params


def get_property_values_for_key(key: str, team: Team, value: Optional[str] = None):
    if value:
        return sync_execute(
            SELECT_PROP_VALUES_SQL_WITH_FILTER, {"team_id": team.pk, "key": key, "value": "%{}%".format(value)},
        )
    return sync_execute(SELECT_PROP_VALUES_SQL, {"team_id": team.pk, "key": key})
