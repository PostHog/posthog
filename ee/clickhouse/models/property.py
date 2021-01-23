from typing import Any, Dict, List, Optional, Tuple

from django.conf import settings
from django.utils import timezone

from ee.clickhouse.client import sync_execute
from ee.clickhouse.models.cohort import format_filter_query
from ee.clickhouse.models.util import is_int, is_json
from ee.clickhouse.sql.events import SELECT_PROP_VALUES_SQL, SELECT_PROP_VALUES_SQL_WITH_FILTER
from ee.clickhouse.sql.person import GET_DISTINCT_IDS_BY_PROPERTY_SQL
from posthog.models.cohort import Cohort
from posthog.models.property import Property
from posthog.models.team import Team
from posthog.utils import relative_date_parse


def parse_prop_clauses(
    filters: List[Property],
    team_id: Optional[int],
    prepend: str = "global",
    table_name: str = "",
    allow_denormalized_props: bool = False,
) -> Tuple[str, Dict]:
    final = []
    params: Dict[str, Any] = {}
    if team_id is not None:
        params["team_id"] = team_id
    if table_name != "":
        table_name += "."

    for idx, prop in enumerate(filters):
        if prop.type == "cohort":
            cohort = Cohort.objects.get(pk=prop.value)
            person_id_query, cohort_filter_params = format_filter_query(cohort)
            params = {**params, **cohort_filter_params}
            final.append(
                "AND {table_name}distinct_id IN ({clause})".format(table_name=table_name, clause=person_id_query)
            )
        elif prop.type == "person":
            filter_query, filter_params = prop_filter_json_extract(
                prop, idx, "{}person".format(prepend), allow_denormalized_props=allow_denormalized_props
            )
            final.append(
                "AND {table_name}distinct_id IN ({filter_query})".format(
                    filter_query=GET_DISTINCT_IDS_BY_PROPERTY_SQL.format(filters=filter_query), table_name=table_name
                )
            )
            params.update(filter_params)
        else:
            filter_query, filter_params = prop_filter_json_extract(
                prop,
                idx,
                prepend,
                prop_var="{}properties".format(table_name),
                allow_denormalized_props=allow_denormalized_props,
            )

            final.append(f"{filter_query} AND {table_name}team_id = %(team_id)s" if team_id else filter_query)
            params.update(filter_params)
    return " ".join(final), params


def prop_filter_json_extract(
    prop: Property, idx: int, prepend: str = "", prop_var: str = "properties", allow_denormalized_props: bool = False
) -> Tuple[str, Dict[str, Any]]:
    # Once all queries are migrated over we can get rid of allow_denormalized_props
    is_denormalized = prop.key.lower() in settings.CLICKHOUSE_DENORMALIZED_PROPERTIES and allow_denormalized_props
    json_extract = "trim(BOTH '\"' FROM JSONExtractRaw({prop_var}, %(k{prepend}_{idx})s))".format(
        idx=idx, prepend=prepend, prop_var=prop_var
    )
    denormalized = "properties_{}".format(prop.key.lower())
    operator = prop.operator
    if operator == "is_not":
        params = {"k{}_{}".format(prepend, idx): prop.key, "v{}_{}".format(prepend, idx): prop.value}
        return (
            "AND NOT ({left} = %(v{prepend}_{idx})s)".format(
                idx=idx, prepend=prepend, left=denormalized if is_denormalized else json_extract
            ),
            params,
        )
    elif operator == "icontains":
        value = "%{}%".format(prop.value)
        params = {"k{}_{}".format(prepend, idx): prop.key, "v{}_{}".format(prepend, idx): value}
        return (
            "AND {left} LIKE %(v{prepend}_{idx})s".format(
                idx=idx, prepend=prepend, left=denormalized if is_denormalized else json_extract
            ),
            params,
        )
    elif operator == "not_icontains":
        value = "%{}%".format(prop.value)
        params = {"k{}_{}".format(prepend, idx): prop.key, "v{}_{}".format(prepend, idx): value}
        return (
            "AND NOT ({left} LIKE %(v{prepend}_{idx})s)".format(
                idx=idx, prepend=prepend, left=denormalized if is_denormalized else json_extract
            ),
            params,
        )
    elif operator == "regex":
        params = {"k{}_{}".format(prepend, idx): prop.key, "v{}_{}".format(prepend, idx): prop.value}
        return (
            "AND match({left}, %(v{prepend}_{idx})s)".format(
                idx=idx, prepend=prepend, left=denormalized if is_denormalized else json_extract
            ),
            params,
        )
    elif operator == "not_regex":
        params = {"k{}_{}".format(prepend, idx): prop.key, "v{}_{}".format(prepend, idx): prop.value}
        return (
            "AND NOT match({left}, %(v{prepend}_{idx})s)".format(
                idx=idx, prepend=prepend, left=denormalized if is_denormalized else json_extract
            ),
            params,
        )
    elif operator == "is_set":
        params = {"k{}_{}".format(prepend, idx): prop.key, "v{}_{}".format(prepend, idx): prop.value}
        if is_denormalized:
            return (
                "AND NOT isNull({left})".format(left=denormalized),
                params,
            )
        return (
            "AND JSONHas({prop_var}, %(k{prepend}_{idx})s)".format(idx=idx, prepend=prepend, prop_var=prop_var),
            params,
        )
    elif operator == "is_not_set":
        params = {"k{}_{}".format(prepend, idx): prop.key, "v{}_{}".format(prepend, idx): prop.value}
        if is_denormalized:
            return (
                "AND isNull({left})".format(left=denormalized),
                params,
            )
        return (
            "AND (isNull({left}) OR NOT JSONHas({prop_var}, %(k{prepend}_{idx})s))".format(
                idx=idx, prepend=prepend, prop_var=prop_var, left=json_extract
            ),
            params,
        )
    elif operator == "gt":
        params = {"k{}_{}".format(prepend, idx): prop.key, "v{}_{}".format(prepend, idx): prop.value}
        return (
            "AND toInt64OrNull(replaceRegexpAll({left}, ' ', '')) > %(v{prepend}_{idx})s".format(
                idx=idx,
                prepend=prepend,
                left=denormalized
                if is_denormalized
                else "visitParamExtractRaw({prop_var}, %(k{prepend}_{idx})s)".format(
                    idx=idx, prepend=prepend, prop_var=prop_var,
                ),
            ),
            params,
        )
    elif operator == "lt":
        params = {"k{}_{}".format(prepend, idx): prop.key, "v{}_{}".format(prepend, idx): prop.value}
        return (
            "AND toInt64OrNull(replaceRegexpAll({left}, ' ', '')) < %(v{prepend}_{idx})s".format(
                idx=idx,
                prepend=prepend,
                left=denormalized
                if is_denormalized
                else "visitParamExtractRaw({prop_var}, %(k{prepend}_{idx})s)".format(
                    idx=idx, prepend=prepend, prop_var=prop_var,
                ),
            ),
            params,
        )
    else:
        if is_int(prop.value) and not is_denormalized:
            clause = "AND JSONExtractInt({prop_var}, %(k{prepend}_{idx})s) = %(v{prepend}_{idx})s"
        elif is_int(prop.value) and is_denormalized:
            clause = "AND toInt64OrNull({left}) = %(v{prepend}_{idx})s"
        elif is_json(prop.value) and not is_denormalized:
            clause = "AND replaceRegexpAll(visitParamExtractRaw({prop_var}, %(k{prepend}_{idx})s),' ', '') = replaceRegexpAll(toString(%(v{prepend}_{idx})s),' ', '')"
        else:
            clause = "AND {left} = %(v{prepend}_{idx})s"

        params = {"k{}_{}".format(prepend, idx): prop.key, "v{}_{}".format(prepend, idx): prop.value}
        return (
            clause.format(
                left=denormalized if is_denormalized else json_extract, idx=idx, prepend=prepend, prop_var=prop_var
            ),
            params,
        )


def get_property_values_for_key(key: str, team: Team, value: Optional[str] = None):

    parsed_date_from = "AND timestamp >= '{}'".format(relative_date_parse("-7d").strftime("%Y-%m-%d 00:00:00"))
    parsed_date_to = "AND timestamp <= '{}'".format(timezone.now().strftime("%Y-%m-%d 23:59:59"))

    if value:
        return sync_execute(
            SELECT_PROP_VALUES_SQL_WITH_FILTER.format(parsed_date_from=parsed_date_from, parsed_date_to=parsed_date_to),
            {"team_id": team.pk, "key": key, "value": "%{}%".format(value)},
        )
    return sync_execute(
        SELECT_PROP_VALUES_SQL.format(parsed_date_from=parsed_date_from, parsed_date_to=parsed_date_to),
        {"team_id": team.pk, "key": key},
    )
