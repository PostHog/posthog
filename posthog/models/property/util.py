import re
from collections import (
    Counter,
    Counter as TCounter,
)
from collections.abc import Callable, Iterable
from typing import Any, Literal, Optional, Union, cast

from rest_framework import exceptions

from posthog.hogql import ast
from posthog.hogql.database.s3_table import S3Table
from posthog.hogql.escape_sql import escape_clickhouse_identifier
from posthog.hogql.hogql import HogQLContext
from posthog.hogql.parser import parse_expr
from posthog.hogql.visitor import TraversingVisitor

from posthog.clickhouse.kafka_engine import trim_quotes_expr
from posthog.clickhouse.materialized_columns import TableWithProperties, get_materialized_column_for_property
from posthog.constants import PropertyOperatorType
from posthog.models.event import Selector
from posthog.models.event.sql import EVENTS_PROPERTIES_JSON_SUBCOLUMNS, PERSON_PROPERTIES_JSON_SUBCOLUMNS
from posthog.models.group.sql import GET_GROUP_IDS_BY_PROPERTY_SQL
from posthog.models.person.sql import GET_DISTINCT_IDS_BY_PERSON_ID_FILTER, GET_DISTINCT_IDS_BY_PROPERTY_SQL
from posthog.models.property import (
    NEGATED_OPERATORS,
    OperatorType,
    Property,
    PropertyGroup,
    PropertyIdentifier,
    PropertyName,
)
from posthog.models.property.property import ValueT
from posthog.models.team import Team
from posthog.queries.person_distinct_id_query import get_team_distinct_ids_query
from posthog.queries.util import PersonPropertiesMode
from posthog.session_recordings.queries.session_query import SessionQuery
from posthog.utils import is_json, is_valid_regex

from products.actions.backend.models.action import Action
from products.actions.backend.models.util import get_action_tables_and_properties
from products.cohorts.backend.models.cohort import Cohort
from products.cohorts.backend.models.util import (
    format_cohort_subquery,
    format_filter_query,
    format_precalculated_cohort_query,
    format_static_cohort_query,
    get_count_operator,
)

StringMatching = Literal["selector", "tag_name", "href", "text"]

# Property Groups Example:
# {type: 'AND', groups: [
#     {type: 'OR', groups: [A, B, C]},
#     {type: 'OR', groups: [D, E, F]},
# ]}

# Example:
# {type: 'AND', groups: [
#     A, B, C, D
# ]}


# Property json is of the form:
# { type: 'AND | OR', groups: List[Property] }
# which is parsed and sent to this function ->
def parse_prop_grouped_clauses(
    team_id: int,
    property_group: Optional[PropertyGroup],
    *,
    hogql_context: HogQLContext,
    prepend: str = "global",
    table_name: str = "",
    allow_denormalized_props: bool = True,
    has_person_id_joined: bool = True,
    person_properties_mode: PersonPropertiesMode = PersonPropertiesMode.USING_SUBQUERY,
    person_id_joined_alias: str = "person_id",
    group_properties_joined: bool = True,
    _top_level: bool = True,
) -> tuple[str, dict]:
    """Translate the given property filter group into an SQL condition clause (+ SQL params)."""
    if not property_group or len(property_group.values) == 0:
        return "", {}

    if isinstance(property_group.values[0], PropertyGroup):
        group_clauses = []
        final_params = {}
        for idx, group in enumerate(property_group.values):
            if isinstance(group, PropertyGroup):
                clause, params = parse_prop_grouped_clauses(
                    team_id=team_id,
                    property_group=group,
                    prepend=f"{prepend}_{idx}",
                    table_name=table_name,
                    allow_denormalized_props=allow_denormalized_props,
                    has_person_id_joined=has_person_id_joined,
                    person_properties_mode=person_properties_mode,
                    person_id_joined_alias=person_id_joined_alias,
                    group_properties_joined=group_properties_joined,
                    hogql_context=hogql_context,
                    _top_level=False,
                )
                group_clauses.append(clause)
                final_params.update(params)

        # purge empty returns
        group_clauses = [clause for clause in group_clauses if clause]
        _final = f"{property_group.type} ".join(group_clauses)
    else:
        _final, final_params = parse_prop_clauses(
            filters=cast(list[Property], property_group.values),
            prepend=f"{prepend}",
            table_name=table_name,
            allow_denormalized_props=allow_denormalized_props,
            has_person_id_joined=has_person_id_joined,
            person_properties_mode=person_properties_mode,
            person_id_joined_alias=person_id_joined_alias,
            group_properties_joined=group_properties_joined,
            property_operator=property_group.type,
            team_id=team_id,
            hogql_context=hogql_context,
        )

    if not _final:
        final = ""
    elif _top_level:
        final = f"AND ({_final})"
    else:
        final = f"({_final})"

    return final, final_params


def parse_prop_clauses(
    team_id: int,
    filters: list[Property],
    *,
    hogql_context: Optional[HogQLContext],
    prepend: str = "global",
    table_name: str = "",
    allow_denormalized_props: bool = True,
    has_person_id_joined: bool = True,
    person_properties_mode: PersonPropertiesMode = PersonPropertiesMode.USING_SUBQUERY,
    person_id_joined_alias: str = "person_id",
    group_properties_joined: bool = True,
    property_operator: PropertyOperatorType = PropertyOperatorType.AND,
) -> tuple[str, dict]:
    """Translate the given property filter into an SQL condition clause (+ SQL params)."""
    final = []
    params: dict[str, Any] = {}

    table_formatted = table_name
    if table_formatted != "":
        table_formatted += "."

    # Resolved once per query via the context so property fragments and the FROM table can't disagree.
    use_new_events_schema = hogql_context.uses_new_events_schema() if hogql_context is not None else False

    _team = None

    def get_team():
        nonlocal _team
        if _team is None:
            _team = Team.objects.only("project_id").get(pk=team_id)
        return _team

    for idx, prop in enumerate(filters):
        if prop.type == "cohort":
            try:
                cohort = Cohort.objects.get(pk=cast(str | int, prop.value), team__project_id=get_team().project_id)
            except Cohort.DoesNotExist:
                final.append(
                    f"{property_operator} 0 = 13"
                )  # If cohort doesn't exist, nothing can match, unless an OR operator is used
            else:
                if person_properties_mode == PersonPropertiesMode.USING_SUBQUERY:
                    person_id_query, cohort_filter_params = format_filter_query(cohort, idx)
                    params = {**params, **cohort_filter_params}
                    final.append(f"{property_operator} {table_formatted}distinct_id IN ({person_id_query})")
                else:
                    person_id_query, cohort_filter_params = format_cohort_subquery(
                        cohort,
                        idx,
                        custom_match_field=person_id_joined_alias,
                    )
                    params = {**params, **cohort_filter_params}
                    final.append(f"{property_operator} {person_id_query}")
        elif prop.type == "person" and person_properties_mode == PersonPropertiesMode.DIRECT_ON_PERSONS:
            filter_query, filter_params = prop_filter_json_extract(
                prop,
                idx,
                prepend,
                prop_var="properties",
                allow_denormalized_props=allow_denormalized_props,
                property_operator=property_operator,
                table_name=table_name,
            )
            final.append(f" {filter_query}")
            params.update(filter_params)
        elif prop.type == "person" and person_properties_mode in [
            PersonPropertiesMode.DIRECT_ON_EVENTS,
            PersonPropertiesMode.DIRECT_ON_EVENTS_WITH_POE_V2,
        ]:
            filter_query, filter_params = prop_filter_json_extract(
                prop,
                idx,
                prepend,
                prop_var="{}person_properties".format(table_formatted),
                allow_denormalized_props=True,
                property_operator=property_operator,
                use_event_column="person_properties",
                use_new_events_schema=use_new_events_schema,
            )
            final.append(filter_query)
            params.update(filter_params)
        elif prop.type == "person" and person_properties_mode != PersonPropertiesMode.DIRECT:
            # :TODO: Clean this up by using PersonQuery over GET_DISTINCT_IDS_BY_PROPERTY_SQL to have access
            #   to materialized columns
            # :TODO: (performance) Avoid subqueries whenever possible, use joins instead
            is_direct_query = person_properties_mode == PersonPropertiesMode.USING_PERSON_PROPERTIES_COLUMN
            filter_query, filter_params = prop_filter_json_extract(
                prop,
                idx,
                "{}person".format(prepend),
                prop_var="person_props" if is_direct_query else "properties",
                allow_denormalized_props=allow_denormalized_props and is_direct_query,
                property_operator=property_operator,
            )
            if is_direct_query:
                final.append(filter_query)
                params.update(filter_params)
            else:
                # Subquery filter here always should be blank as it's the first
                filter_query = filter_query.replace(property_operator, "", 1)
                final.append(
                    " {property_operator} {table_name}distinct_id IN ({filter_query})".format(
                        filter_query=GET_DISTINCT_IDS_BY_PROPERTY_SQL.format(
                            filters=filter_query,
                            GET_TEAM_PERSON_DISTINCT_IDS=get_team_distinct_ids_query(team_id),
                        ),
                        table_name=table_formatted,
                        property_operator=property_operator,
                    )
                )
                params.update(filter_params)
        elif prop.type == "person" and person_properties_mode == PersonPropertiesMode.DIRECT:
            # this setting is used to generate the PersonQuery SQL.
            # When using direct mode, there should only be person properties in the entire
            # property group
            filter_query, filter_params = prop_filter_json_extract(
                prop,
                idx,
                prepend=f"personquery_{prepend}",
                allow_denormalized_props=True,
                transform_expression=lambda column_name: f"argMax(person.{column_name}, version)",
                property_operator=property_operator,
            )
            final.append(filter_query)
            params.update(filter_params)
        elif prop.type == "event":
            filter_query, filter_params = prop_filter_json_extract(
                prop,
                idx,
                prepend,
                prop_var="{}properties".format(table_formatted),
                allow_denormalized_props=allow_denormalized_props,
                property_operator=property_operator,
                use_new_events_schema=use_new_events_schema,
            )
            final.append(f" {filter_query}")
            params.update(filter_params)
        elif prop.type == "element":
            query, filter_params = filter_element(
                cast(StringMatching, prop.key),
                prop.value,
                operator=prop.operator,
                prepend="{}_".format(prepend),
            )
            if query:
                final.append(f"{property_operator} {query}")
                params.update(filter_params)
        elif prop.type == "group":
            if group_properties_joined:
                # Special case: $group_key refers to the actual group_key column, not a JSON property
                if prop.key == "$group_key":
                    filter_query, filter_params = _build_group_key_filter(prop, idx, prepend, property_operator)
                    final.append(filter_query)
                    params.update(filter_params)
                else:
                    filter_query, filter_params = prop_filter_json_extract(
                        prop,
                        idx,
                        prepend,
                        prop_var=f"group_properties_{prop.group_type_index}",
                        allow_denormalized_props=False,
                        property_operator=property_operator,
                    )
                    final.append(filter_query)
                    params.update(filter_params)
            else:
                # :TRICKY: offer groups support for queries which don't support automatically joining with groups table yet (e.g. lifecycle)
                filter_query, filter_params = prop_filter_json_extract(
                    prop,
                    idx,
                    prepend,
                    prop_var=f"group_properties",
                    allow_denormalized_props=False,
                )
                group_type_index_var = f"{prepend}_group_type_index_{idx}"
                groups_subquery = GET_GROUP_IDS_BY_PROPERTY_SQL.format(
                    filters=filter_query, group_type_index_var=group_type_index_var
                )
                final.append(
                    f"{property_operator} {table_formatted}$group_{prop.group_type_index} IN ({groups_subquery})"
                )
                params.update(filter_params)
                params[group_type_index_var] = prop.group_type_index
        elif prop.type in ("static-cohort", "precalculated-cohort"):
            cohort_id = cast(int, prop.value)
            cohort = Cohort.objects.get(pk=cohort_id, team__project_id=get_team().project_id)

            method = format_static_cohort_query if prop.type == "static-cohort" else format_precalculated_cohort_query
            filter_query, filter_params = method(cohort, idx, prepend=prepend)
            filter_query = f"""{person_id_joined_alias if not person_properties_mode == PersonPropertiesMode.DIRECT_ON_EVENTS else "person_id"} IN ({filter_query})"""

            if has_person_id_joined or person_properties_mode in [
                PersonPropertiesMode.DIRECT_ON_EVENTS,
                PersonPropertiesMode.DIRECT_ON_EVENTS_WITH_POE_V2,
            ]:
                final.append(f"{property_operator} {filter_query}")
            else:
                # :TODO: (performance) Avoid subqueries whenever possible, use joins instead
                subquery = GET_DISTINCT_IDS_BY_PERSON_ID_FILTER.format(
                    filters=filter_query,
                    GET_TEAM_PERSON_DISTINCT_IDS=get_team_distinct_ids_query(team_id),
                )
                final.append(f"{property_operator} {table_formatted}distinct_id IN ({subquery})")
            params.update(filter_params)
        elif prop.type == "session":
            filter_query, filter_params = get_session_property_filter_statement(prop, idx, prepend)
            final.append(f"{property_operator} {filter_query}")
            params.update(filter_params)
        elif prop.type == "hogql":
            if hogql_context is None:
                raise ValueError("HogQL is not supported here")
            from posthog.hogql.hogql import translate_hogql

            filter_query = translate_hogql(prop.key, hogql_context)
            final.append(f"{property_operator} {filter_query}")

    if final:
        # remove the first operator
        return " ".join(final).replace(property_operator, "", 1), params

    return "", params


def negate_operator(operator: OperatorType) -> OperatorType:
    return cast(
        OperatorType,
        {
            "is_not": "exact",
            "exact": "is_not",
            "icontains": "not_icontains",
            "not_icontains": "icontains",
            "regex": "not_regex",
            "not_regex": "regex",
            "gt": "lte",
            "lt": "gte",
            "gte": "lt",
            "lte": "gt",
            "is_set": "is_not_set",
            "is_not_set": "is_set",
            "is_date_before": "is_date_after",
            "is_date_after": "is_date_before",
            # is_date_exact not yet supported
        }.get(operator, operator),
    )


def prop_filter_json_extract(
    prop: Property,
    idx: int,
    prepend: str = "",
    prop_var: str = "properties",
    allow_denormalized_props: bool = True,
    transform_expression: Optional[Callable[[str], str]] = None,
    property_operator: str = PropertyOperatorType.AND,
    table_name: Optional[str] = None,
    use_event_column: Optional[str] = None,
    use_new_events_schema: bool = False,
) -> tuple[str, dict[str, Any]]:
    # TODO: Once all queries are migrated over we can get rid of allow_denormalized_props
    if transform_expression is not None:
        prop_var = transform_expression(prop_var)

    target_table = "events" if use_event_column else property_table(prop)
    is_events_json = use_new_events_schema and target_table == "events"

    property_expr, is_denormalized = get_property_string_expr(
        target_table,
        prop.key,
        f"%(k{prepend}_{idx})s",
        prop_var,
        allow_denormalized_props,
        table_name,
        materialised_table_column=use_event_column if use_event_column else "properties",
        use_new_events_schema=is_events_json,
    )
    events_json_property_exists_expr: str | None = None
    events_json_column = use_event_column or "properties"
    if is_events_json and events_json_column in ("properties", "person_properties"):
        table_prefix = f"{table_name}." if table_name else ""
        events_json_property_exists_expr = _json_events_property_exists_expr(
            prop.key,
            f"%(k{prepend}_{idx})s",
            f"{table_prefix}{prop_var}",
            events_json_column,
        )

    if is_denormalized and transform_expression:
        property_expr = transform_expression(property_expr)

    operator = prop.operator
    if prop.negation:
        operator = negate_operator(operator or "exact")

    params: dict[str, Any] = {}

    if operator == "is_not":
        params = {
            "k{}_{}".format(prepend, idx): prop.key,
            "v{}_{}".format(prepend, idx): box_value(prop.value),
        }
        return (
            " {property_operator} NOT has(%(v{prepend}_{idx})s, {left})".format(
                idx=idx,
                prepend=prepend,
                left=property_expr,
                property_operator=property_operator,
            ),
            params,
        )
    elif operator == "icontains":
        value = "%{}%".format(prop.value)
        params = {
            "k{}_{}".format(prepend, idx): prop.key,
            "v{}_{}".format(prepend, idx): value,
        }
        return (
            " {property_operator} {left} ILIKE %(v{prepend}_{idx})s".format(
                idx=idx,
                prepend=prepend,
                left=property_expr,
                property_operator=property_operator,
            ),
            params,
        )
    elif operator == "not_icontains":
        value = "%{}%".format(prop.value)
        params = {
            "k{}_{}".format(prepend, idx): prop.key,
            "v{}_{}".format(prepend, idx): value,
        }
        return (
            " {property_operator} NOT ({left} ILIKE %(v{prepend}_{idx})s)".format(
                idx=idx,
                prepend=prepend,
                left=property_expr,
                property_operator=property_operator,
            ),
            params,
        )
    elif operator in ("regex", "not_regex"):
        if not is_valid_regex(str(prop.value)):
            # If OR'ing, shouldn't be a problem since nothing will match this specific clause
            return f"{property_operator} 1 = 2", {}

        params = {
            "k{}_{}".format(prepend, idx): prop.key,
            "v{}_{}".format(prepend, idx): prop.value,
        }

        return (
            " {property_operator} {regex_function}({left}, %(v{prepend}_{idx})s)".format(
                regex_function="match" if operator == "regex" else "NOT match",
                idx=idx,
                prepend=prepend,
                left=property_expr,
                property_operator=property_operator,
            ),
            params,
        )
    elif operator == "is_set":
        params = {
            "k{}_{}".format(prepend, idx): prop.key,
            "v{}_{}".format(prepend, idx): prop.value,
        }
        if events_json_property_exists_expr is not None:
            return (
                f" {property_operator} {events_json_property_exists_expr}",
                params,
            )
        if is_denormalized:
            return (
                " {property_operator} {left} != ''".format(left=property_expr, property_operator=property_operator),
                params,
            )
        return (
            " {property_operator} JSONHas({prop_var}, %(k{prepend}_{idx})s)".format(
                idx=idx,
                prepend=prepend,
                prop_var=prop_var,
                property_operator=property_operator,
            ),
            params,
        )
    elif operator == "is_not_set":
        params = {
            "k{}_{}".format(prepend, idx): prop.key,
            "v{}_{}".format(prepend, idx): prop.value,
        }
        if events_json_property_exists_expr is not None:
            return (
                f" {property_operator} NOT ({events_json_property_exists_expr})",
                params,
            )
        if is_denormalized:
            return (
                " {property_operator} {left} = ''".format(left=property_expr, property_operator=property_operator),
                params,
            )
        return (
            " {property_operator} (isNull({left}) OR NOT JSONHas({prop_var}, %(k{prepend}_{idx})s))".format(
                idx=idx,
                prepend=prepend,
                prop_var=prop_var,
                left=property_expr,
                property_operator=property_operator,
            ),
            params,
        )
    elif operator == "is_date_exact":
        # TODO introducing duplication in these branches now rather than refactor too early
        assert isinstance(prop.value, str)
        prop_value_param_key = "v{}_{}".format(prepend, idx)

        # if we're comparing against a date with no time,
        # truncate the values in the DB which may have times
        granularity = "day" if re.match(r"^\d{4}-\d{2}-\d{2}$", prop.value) else "second"
        query = f"""AND date_trunc('{granularity}', coalesce(
            parseDateTimeBestEffortOrNull({property_expr}),
            parseDateTimeBestEffortOrNull(substring({property_expr}, 1, 10))
        )) = %({prop_value_param_key})s"""

        return (
            query,
            {"k{}_{}".format(prepend, idx): prop.key, prop_value_param_key: prop.value},
        )
    elif operator == "is_date_after":
        # TODO introducing duplication in these branches now rather than refactor too early
        assert isinstance(prop.value, str)
        prop_value_param_key = "v{}_{}".format(prepend, idx)

        # if we're comparing against a date with no time,
        # then instead of 2019-01-01 (implied 00:00:00)
        # use 2019-01-01 23:59:59
        is_date_only = re.match(r"^\d{4}-\d{2}-\d{2}$", prop.value)

        try_parse_as_date = f"parseDateTimeBestEffortOrNull({property_expr})"
        try_parse_as_timestamp = f"parseDateTimeBestEffortOrNull(substring({property_expr}, 1, 10))"
        first_of_date_or_timestamp = f"coalesce({try_parse_as_date},{try_parse_as_timestamp})"

        if is_date_only:
            adjusted_value = f"subtractSeconds(addDays(toDate(%({prop_value_param_key})s), 1), 1)"
        else:
            adjusted_value = f"%({prop_value_param_key})s"

        query = f"""{property_operator} {first_of_date_or_timestamp} > {adjusted_value}"""

        return (
            query,
            {"k{}_{}".format(prepend, idx): prop.key, prop_value_param_key: prop.value},
        )
    elif operator == "is_date_before":
        # TODO introducing duplication in these branches now rather than refactor too early
        assert isinstance(prop.value, str)
        prop_value_param_key = "v{}_{}".format(prepend, idx)
        try_parse_as_date = f"parseDateTimeBestEffortOrNull({property_expr})"
        try_parse_as_timestamp = f"parseDateTimeBestEffortOrNull(substring({property_expr}, 1, 10))"
        first_of_date_or_timestamp = f"coalesce({try_parse_as_date},{try_parse_as_timestamp})"
        query = f"""{property_operator} {first_of_date_or_timestamp} < %({prop_value_param_key})s"""

        return (
            query,
            {"k{}_{}".format(prepend, idx): prop.key, prop_value_param_key: prop.value},
        )
    elif operator in ["gt", "lt", "gte", "lte"]:
        count_operator = get_count_operator(operator)

        params = {
            "k{}_{}".format(prepend, idx): prop.key,
            "v{}_{}".format(prepend, idx): prop.value,
        }
        extract_property_expr = trim_quotes_expr(f"replaceRegexpAll({property_expr}, ' ', '')")
        return (
            f" {property_operator} toFloat64OrNull({extract_property_expr}) {count_operator} %(v{prepend}_{idx})s",
            params,
        )
    else:
        if is_json(prop.value) and not is_denormalized:
            if is_events_json:
                clause = " {property_operator} has(arrayMap(value -> toJSONString(JSONExtract(value, 'Dynamic')), %(v{prepend}_{idx})s), {left})"
                values = box_value(prop.value)
            else:
                clause = " {property_operator} has(%(v{prepend}_{idx})s, replaceRegexpAll(visitParamExtractRaw({prop_var}, %(k{prepend}_{idx})s),' ', ''))"
                values = box_value(prop.value, remove_spaces=True)
            params = {
                "k{}_{}".format(prepend, idx): prop.key,
                "v{}_{}".format(prepend, idx): values,
            }
        else:
            clause = " {property_operator} has(%(v{prepend}_{idx})s, {left})"
            params = {
                "k{}_{}".format(prepend, idx): prop.key,
                "v{}_{}".format(prepend, idx): box_value(prop.value),
            }
        return (
            clause.format(
                left=property_expr,
                idx=idx,
                prepend=prepend,
                prop_var=prop_var,
                property_operator=property_operator,
            ),
            params,
        )


def property_table(property: Property) -> TableWithProperties:
    if property.type == "event":
        return "events"
    elif property.type == "person":
        return "person"
    elif property.type == "group":
        return "groups"
    else:
        raise ValueError(f"Property type does not have a table: {property.type}")


def get_property_string_expr(
    table: TableWithProperties,
    property_name: PropertyName,
    var: str,
    column: str,
    allow_denormalized_props: bool = True,
    table_alias: Optional[str] = None,
    materialised_table_column: str = "properties",
    use_new_events_schema: bool = False,
) -> tuple[str, bool]:
    """

    :param table:
        the full name of the table in the database. used to look up which properties have been materialized
    :param property_name:
    :param var:
        the value to template in from the data structure for the query e.g. %(key)s or a flat value e.g. ["Safari"].
        If a flat value it should be escaped before being passed to this function
    :param column:
        the table column where JSON is stored or the name of a materialized column
    :param allow_denormalized_props:
    :param table_alias:
        (optional) alias of the table being queried
    :param use_new_events_schema:
        read events properties as native-JSON subcolumns (events_json) instead of mat_* columns /
        the String blob. Must match the table the surrounding query actually selects from.
    :return:
    """
    table_string = f"{table_alias}." if table_alias is not None and table_alias != "" else ""

    if use_new_events_schema and table == "events":
        if materialised_table_column in ("properties", "person_properties"):
            return _json_events_property_expr(property_name, var, f"{table_string}{column}", materialised_table_column)
        # The JSON events table has no mat_* columns at all; group columns there stay String blobs.
        allow_denormalized_props = False

    if (
        allow_denormalized_props
        and (
            materialized_column := get_materialized_column_for_property(
                table,
                cast(Literal["properties", "group_properties", "person_properties"], materialised_table_column),
                property_name,
            )
        )
        and not materialized_column.is_nullable
        and "group" not in materialised_table_column
    ):
        return (
            f'{table_string}"{materialized_column.name}"',
            True,
        )

    return trim_quotes_expr(f"JSONExtractRaw({table_string}{column}, {var})"), False


def _json_events_property_expr(
    property_name: PropertyName, var: str, column_ref: str, materialised_table_column: str
) -> tuple[str, bool]:
    """Property value read against the native-JSON events schema.

    Typed subcolumns read like non-nullable materialized columns (missing reads ''), so callers'
    denormalized-column handling applies unchanged. Dynamic properties combine the scalar path and
    sub-object path for that key, preserving the logical JSON string without rebuilding the document.
    """
    subcolumns = (
        EVENTS_PROPERTIES_JSON_SUBCOLUMNS
        if materialised_table_column == "properties"
        else PERSON_PROPERTIES_JSON_SUBCOLUMNS
    )
    scalar_value = _json_events_subcolumn_expr(property_name, var, column_ref)
    if property_name in subcolumns:
        if subcolumns[property_name].startswith(("Array(", "Map(")):
            return f"if(empty({scalar_value}), '', toJSONString({scalar_value}))", True
        return f"ifNull({scalar_value}, '')", True

    object_value = f"toJSONString({_json_events_subcolumn_expr(property_name, var, column_ref, sub_object=True)})"
    # dynamicType only chooses scalar versus container formatting; both branches cast the
    # whole Dynamic value rather than selecting one physical variant.
    dynamic_type = f"dynamicType({scalar_value})"
    is_container = " OR ".join(f"startsWith({dynamic_type}, '{family}')" for family in ("Array", "Map", "Tuple"))
    scalar_string = f"toString({scalar_value})"
    formatted_scalar = (
        f"if(startsWith({dynamic_type}, 'DateTime'), replaceOne({scalar_string}, ' ', 'T'), {scalar_string})"
    )
    raw_value = (
        f"if({object_value} != '{{}}', {object_value}, "
        f"if({is_container}, toJSONString({scalar_value}), {formatted_scalar}))"
    )
    return trim_quotes_expr(f"ifNull({raw_value}, '')"), False


def _json_events_property_exists_expr(
    property_name: PropertyName, var: str, column_ref: str, materialised_table_column: str
) -> str:
    subcolumns = (
        EVENTS_PROPERTIES_JSON_SUBCOLUMNS
        if materialised_table_column == "properties"
        else PERSON_PROPERTIES_JSON_SUBCOLUMNS
    )
    scalar_value = _json_events_subcolumn_expr(property_name, var, column_ref)
    if property_name in subcolumns:
        if subcolumns[property_name].startswith(("Array(", "Map(")):
            return f"notEmpty({scalar_value})"
        return f"isNotNull({scalar_value})"

    object_value = f"toJSONString({_json_events_subcolumn_expr(property_name, var, column_ref, sub_object=True)})"
    return f"(isNotNull({scalar_value}) OR {object_value} != '{{}}')"


def _json_events_subcolumn_expr(
    property_name: PropertyName, var: str, column_ref: str, *, sub_object: bool = False
) -> str:
    if "%" not in property_name:
        separator = ".^" if sub_object else "."
        return f"{column_ref}{separator}{escape_clickhouse_identifier(property_name)}"

    escaped_backticks = f"replaceAll({var}, char(96), concat(char(96), char(96)))"
    quoted_subcolumn = f"concat(char(96), {escaped_backticks}, char(96))"
    subcolumn = f"concat('^', {quoted_subcolumn})" if sub_object else var
    return f"getSubcolumn({column_ref}, {subcolumn})"


def box_value(value: Any, remove_spaces=False) -> list[Any]:
    if not isinstance(value, list):
        value = [value]
    return [str(value).replace(" ", "") if remove_spaces else str(value) for value in value]


def filter_element(
    key: StringMatching,
    value: ValueT,
    *,
    operator: Optional[OperatorType] = None,
    prepend: str = "",
) -> tuple[str, dict]:
    if operator is None:
        operator = "exact"

    params = {}
    combination_conditions: list[str] = []

    if key == "selector":
        if operator not in ("exact", "is_not"):
            raise exceptions.ValidationError(
                'Filtering by element selector only supports operators "equals" and "doesn\'t equal" currently.'
            )
        selectors = cast(list[str | int], value) if isinstance(value, list) else [value]
        for idx, query in enumerate(selectors):
            if not query:  # Skip empty selectors
                continue
            if not isinstance(query, str):
                raise exceptions.ValidationError("Selector must be a string")
            selector = Selector(query, escape_slashes=False)
            param_key = f"{prepend}_{idx}_selector_regex"
            params[param_key] = build_selector_regex(selector)
            combination_conditions.append(f"match(elements_chain, %({param_key})s)")

    elif key == "tag_name":
        if operator not in ("exact", "is_not"):
            raise exceptions.ValidationError(
                'Filtering by element tag only supports operators "equals" and "doesn\'t equal" currently.'
            )
        tag_names = cast(list[str | int], value) if isinstance(value, list) else [value]
        for idx, tag_name in enumerate(tag_names):
            if not tag_name:  # Skip empty tags
                continue
            if not isinstance(tag_name, str):
                raise exceptions.ValidationError("Tag name must be a string")
            param_key = f"{prepend}_{idx}_tag_name_regex"
            params[param_key] = rf"(^|;){tag_name}(\.|$|;|:)"
            combination_conditions.append(f"match(elements_chain, %({param_key})s)")

    elif key in ["href", "text"]:
        ok_values = process_ok_values(value, operator)
        for idx, value in enumerate(ok_values):
            optional_flag = "(?i)" if operator.endswith("icontains") else ""
            param_key = f"{prepend}_{key}_{idx}_attributes_regex"
            params[param_key] = f'{optional_flag}({key}="{value}")'
            combination_conditions.append(f"match(elements_chain, %({param_key})s)")

    else:
        raise ValueError(f'Invalid element filtering key "{key}"')

    if combination_conditions:
        return (
            f"{'NOT ' if operator in NEGATED_OPERATORS else ''}({' OR '.join(combination_conditions)})",
            params,
        )
    else:
        # If there are no values to filter by, this either matches nothing (for non-negated operators like "equals"),
        # or everything (for negated operators like "doesn't equal")
        return "0 = 191" if operator not in NEGATED_OPERATORS else "", {}


def _build_group_key_filter(
    prop: Property, idx: int, prepend: str, property_operator: str
) -> tuple[str, dict[str, Any]]:
    """
    Build SQL filter for $group_key property targeting the group_key column directly.

    Args:
        prop: Property object with $group_key
        idx: Index for parameter naming
        prepend: Prefix for parameter keys
        property_operator: SQL operator (AND/OR)

    Returns:
        Tuple of (filter_query, filter_params)
    """
    operator = prop.operator or "exact"
    if prop.negation:
        operator = negate_operator(operator)

    param_key = f"{prepend}_group_key_{idx}"
    param_value = prop.value

    if operator == "exact":
        filter_query = f"{property_operator} group_key = %({param_key})s"
    elif operator == "is_not":
        filter_query = f"{property_operator} group_key != %({param_key})s"
    elif operator == "icontains":
        filter_query = f"{property_operator} group_key ILIKE %({param_key})s"
        param_value = f"%{prop.value}%"
    elif operator == "not_icontains":
        filter_query = f"{property_operator} NOT (group_key ILIKE %({param_key})s)"
        param_value = f"%{prop.value}%"
    elif operator in ("regex", "not_regex"):
        regex_func = "match" if operator == "regex" else "NOT match"
        filter_query = f"{property_operator} {regex_func}(group_key, %({param_key})s)"
    else:
        # Default to exact match for unsupported operators
        filter_query = f"{property_operator} group_key = %({param_key})s"

    filter_params = {param_key: param_value}
    return filter_query, filter_params


def process_ok_values(ok_values: Any, operator: OperatorType) -> list[str]:
    if operator.endswith("_set"):
        return [r'[^"]+']
    else:
        # Make sure ok_values is a list
        ok_values = cast(list[str], [str(val) for val in ok_values]) if isinstance(ok_values, list) else [ok_values]
        # Escape double quote characters, since e.g. text 'foo="bar"' is represented as text="foo=\"bar\""
        # in the elements chain
        ok_values = [text.replace('"', r"\"") for text in ok_values]
        if operator.endswith("icontains"):
            # Process values for case-insensitive-contains matching by way of regex,
            # making sure matching scope is limited to between double quotes
            return [rf'[^"]*{re.escape(text)}[^"]*' for text in ok_values]
        if operator.endswith("regex"):
            # Use values as-is in case of regex matching
            return ok_values
        # For all other operators escape regex-meaningful sequences
        return [re.escape(text) for text in ok_values]


def build_selector_regex(selector: Selector) -> str:
    regex = r""
    for tag in selector.parts:
        if tag.data.get("tag_name") and isinstance(tag.data["tag_name"], str) and tag.data["tag_name"] != "*":
            # The elements in the elements_chain are separated by the semicolon
            regex += re.escape(tag.data["tag_name"])
        if tag.data.get("attr_class__contains"):
            regex += r".*?\." + r"\..*?".join([re.escape(s) for s in sorted(tag.data["attr_class__contains"])])
        if tag.ch_attributes:
            regex += r".*?"
            for key, value in sorted(tag.ch_attributes.items()):
                regex += rf'{re.escape(key)}="{re.escape(str(value))}".*?'
        regex += r'([-_a-zA-Z0-9\.:"= \[\]\(\),]*?)?($|;|:([^;^\s]*(;|$|\s)))'
        if tag.direct_descendant:
            regex += r".*"
    if regex:
        # Always start matching at the beginning of an element in the chain string
        # This is to avoid issues like matching elements with class "foo" when looking for elements with tag name "foo"
        return r"(^|;)" + regex
    else:
        return r""


class HogQLPropertyChecker(TraversingVisitor):
    def __init__(self):
        self.event_properties: list[str] = []
        self.person_properties: list[str] = []

    def visit_field(self, node: ast.Field):
        if len(node.chain) > 1 and node.chain[0] == "properties":
            self.event_properties.append(str(node.chain[1]))

        if len(node.chain) > 2 and node.chain[0] == "person" and node.chain[1] == "properties":
            self.person_properties.append(str(node.chain[2]))

        if (
            len(node.chain) > 3
            and node.chain[0] == "pdi"
            and node.chain[1] == "person"
            and node.chain[2] == "properties"
        ):
            self.person_properties.append(str(node.chain[3]))


def extract_tables_and_properties(props: list[Property], team_id: int) -> TCounter[PropertyIdentifier]:
    counters: list[tuple] = []
    for prop in props:
        if prop.type == "hogql":
            counters.extend(count_hogql_properties(prop.key))
        elif prop.type == "behavioral" and prop.event_type == "actions":
            action = Action.objects.get(pk=prop.key, team_id=team_id)
            action_counter = get_action_tables_and_properties(action)
            counters.extend(action_counter)
        else:
            counters.append((prop.key, prop.type, prop.group_type_index))
    return Counter(cast(Iterable, counters))


def count_hogql_properties(
    expr: str, counter: Optional[TCounter[PropertyIdentifier]] = None
) -> TCounter[PropertyIdentifier]:
    if not counter:
        counter = Counter()
    node = parse_expr(expr)
    property_checker = HogQLPropertyChecker()
    property_checker.visit(node)
    for field in property_checker.event_properties:
        counter[(field, "event", None)] += 1
    for field in property_checker.person_properties:
        counter[(field, "person", None)] += 1
    return counter


def get_session_property_filter_statement(prop: Property, idx: int, prepend: str = "") -> tuple[str, dict[str, Any]]:
    if prop.key == "$session_duration":
        try:
            duration = float(cast(str | int, prop.value))
        except ValueError:
            raise (exceptions.ValidationError(f"$session_duration value must be a number. Received '{prop.value}'"))
        value = f"session_duration_value{prepend}_{idx}"

        operator = get_count_operator(prop.operator)
        return (
            f"{SessionQuery.SESSION_TABLE_ALIAS}.session_duration {operator} %({value})s",
            {value: duration},
        )

    else:
        raise exceptions.ValidationError(f"Session property '{prop.key}' is only valid in HogQL queries.")


def clear_excess_levels(prop: Union["PropertyGroup", "Property"], skip=False):
    if isinstance(prop, PropertyGroup):
        if len(prop.values) == 1:
            if skip:
                prop.values = [clear_excess_levels(p) for p in prop.values]
            else:
                return clear_excess_levels(prop.values[0])
        else:
            prop.values = [clear_excess_levels(p, skip=True) for p in prop.values]

    return prop


class S3TableVisitor(TraversingVisitor):
    def __init__(self):
        super().__init__()
        self.tables = set()

    def visit_table_type(self, node):
        if isinstance(node.table, S3Table):
            self.tables.add(node.table.name)
        super().visit_table_type(node)
