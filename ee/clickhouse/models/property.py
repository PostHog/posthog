from typing import Any, Dict, List, Optional, Tuple

from ee.clickhouse.client import sync_execute
from ee.clickhouse.models.cohort import format_filter_query
from ee.clickhouse.models.util import is_int, is_json
from ee.clickhouse.sql.events import SELECT_PROP_VALUES_SQL, SELECT_PROP_VALUES_SQL_WITH_FILTER
from ee.clickhouse.sql.person import GET_DISTINCT_IDS_BY_PROPERTY_SQL
from posthog.models.cohort import Cohort
from posthog.models.property import Property
from posthog.models.team import Team


def parse_prop_clauses(
    filters: List[Property], team: Team, prepend: str = "", table_name: str = ""
) -> Tuple[str, Dict]:
    final = ""
    params: Dict[str, Any] = {"team_id": team.pk}
    if table_name != "":
        table_name += "."

    for idx, prop in enumerate(filters):
        if prop.type == "cohort":
            cohort = Cohort.objects.get(pk=prop.value)
            person_id_query, cohort_filter_params = format_filter_query(cohort)
            params = {**params, **cohort_filter_params}
            final += "AND {table_name}distinct_id IN ({clause}) ".format(table_name=table_name, clause=person_id_query)
        elif prop.type == "person":
            filter_query, filter_params = prop_filter_json_extract(prop, idx, "{}person".format(prepend))
            final += " AND {table_name}distinct_id IN ({filter_query})".format(
                filter_query=GET_DISTINCT_IDS_BY_PROPERTY_SQL.format(filters=filter_query), table_name=table_name
            )
            params.update(filter_params)
        else:
            filter_query, filter_params = prop_filter_json_extract(
                prop, idx, prepend, prop_var="{}properties".format(table_name)
            )
            final += " {filter_query} AND {table_name}team_id = %(team_id)s".format(
                table_name=table_name, filter_query=filter_query
            )
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
            "AND JSONHas({prop_var}, %(k{prepend}_{idx})s)".format(idx=idx, prepend=prepend, prop_var=prop_var),
            params,
        )
    elif operator == "is_not_set":
        params = {"k{}_{}".format(prepend, idx): prop.key, "v{}_{}".format(prepend, idx): prop.value}
        return (
            "AND (isNull(JSONExtractString({prop_var}, %(k{prepend}_{idx})s)) OR NOT JSONHas({prop_var}, %(k{prepend}_{idx})s))".format(
                idx=idx, prepend=prepend, prop_var=prop_var
            ),
            params,
        )
    elif operator == "gt":
        params = {"k{}_{}".format(prepend, idx): prop.key, "v{}_{}".format(prepend, idx): prop.value}
        return (
            "AND toInt64OrNull(replaceRegexpAll(visitParamExtractRaw({prop_var}, %(k{prepend}_{idx})s), ' ', '')) > %(v{prepend}_{idx})s".format(
                idx=idx, prepend=prepend, prop_var=prop_var
            ),
            params,
        )
    elif operator == "lt":
        params = {"k{}_{}".format(prepend, idx): prop.key, "v{}_{}".format(prepend, idx): prop.value}
        return (
            "AND toInt64OrNull(replaceRegexpAll(visitParamExtractRaw({prop_var}, %(k{prepend}_{idx})s), ' ', '')) < %(v{prepend}_{idx})s".format(
                idx=idx, prepend=prepend, prop_var=prop_var
            ),
            params,
        )
    else:
        if is_int(prop.value):
            clause = "AND JSONExtractInt({prop_var}, %(k{prepend}_{idx})s) = %(v{prepend}_{idx})s"
        elif is_json(prop.value):
            clause = "AND replaceRegexpAll(visitParamExtractRaw({prop_var}, %(k{prepend}_{idx})s),' ', '') = replaceRegexpAll(toString(%(v{prepend}_{idx})s),' ', '')"
        else:
            clause = "AND JSONExtractString({prop_var}, %(k{prepend}_{idx})s) = %(v{prepend}_{idx})s"

        params = {"k{}_{}".format(prepend, idx): prop.key, "v{}_{}".format(prepend, idx): prop.value}
        return (
            clause.format(idx=idx, prepend=prepend, prop_var=prop_var),
            params,
        )


def get_property_values_for_key(key: str, team: Team, value: Optional[str] = None):
    if value:
        return sync_execute(
            SELECT_PROP_VALUES_SQL_WITH_FILTER, {"team_id": team.pk, "key": key, "value": "%{}%".format(value)},
        )
    return sync_execute(SELECT_PROP_VALUES_SQL, {"team_id": team.pk, "key": key})
