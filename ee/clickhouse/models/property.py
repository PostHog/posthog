import re
from typing import (
    Any,
    Callable,
    Counter,
    Dict,
    List,
    Literal,
    Optional,
    Tuple,
    Union,
    cast,
)

from clickhouse_driver.util.escape import escape_param
from rest_framework import exceptions

from ee.clickhouse.materialized_columns.columns import TableWithProperties, get_materialized_columns
from ee.clickhouse.models.cohort import (
    format_cohort_subquery,
    format_filter_query,
    format_precalculated_cohort_query,
    format_static_cohort_query,
)
from ee.clickhouse.models.util import is_json
from ee.clickhouse.sql.clickhouse import trim_quotes_expr
from ee.clickhouse.sql.groups import GET_GROUP_IDS_BY_PROPERTY_SQL
from ee.clickhouse.sql.person import GET_DISTINCT_IDS_BY_PERSON_ID_FILTER, GET_DISTINCT_IDS_BY_PROPERTY_SQL
from posthog.constants import PropertyOperatorType
from posthog.models.cohort import Cohort
from posthog.models.event import Selector
from posthog.models.property import (
    NEGATED_OPERATORS,
    OperatorType,
    Property,
    PropertyGroup,
    PropertyIdentifier,
    PropertyName,
)
from posthog.models.utils import PersonPropertiesMode
from posthog.queries.person_distinct_id_query import get_team_distinct_ids_query
from posthog.utils import is_valid_regex

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
    prepend: str = "global",
    table_name: str = "",
    allow_denormalized_props: bool = True,
    has_person_id_joined: bool = True,
    person_properties_mode: PersonPropertiesMode = PersonPropertiesMode.USING_SUBQUERY,
    person_id_joined_alias: str = "person_id",
    group_properties_joined: bool = True,
    _top_level: bool = True,
) -> Tuple[str, Dict]:

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
                    _top_level=False,
                )
                group_clauses.append(clause)
                final_params.update(params)

        # purge empty returns
        group_clauses = [clause for clause in group_clauses if clause]
        _final = f"{property_group.type} ".join(group_clauses)
    else:
        _final, final_params = parse_prop_clauses(
            filters=cast(List[Property], property_group.values),
            prepend=f"{prepend}",
            table_name=table_name,
            allow_denormalized_props=allow_denormalized_props,
            has_person_id_joined=has_person_id_joined,
            person_properties_mode=person_properties_mode,
            person_id_joined_alias=person_id_joined_alias,
            group_properties_joined=group_properties_joined,
            property_operator=property_group.type,
            team_id=team_id,
        )

    if not _final:
        final = ""
    elif _top_level:
        final = f"AND ({_final})"
    else:
        final = f"({_final})"

    return final, final_params


def is_property_group(group: Union[Property, "PropertyGroup"]):
    if isinstance(group, PropertyGroup):
        return True
    else:
        return False


def parse_prop_clauses(
    team_id: int,
    filters: List[Property],
    prepend: str = "global",
    table_name: str = "",
    allow_denormalized_props: bool = True,
    has_person_id_joined: bool = True,
    person_properties_mode: PersonPropertiesMode = PersonPropertiesMode.USING_SUBQUERY,
    person_id_joined_alias: str = "person_id",
    group_properties_joined: bool = True,
    property_operator: PropertyOperatorType = PropertyOperatorType.AND,
) -> Tuple[str, Dict]:
    final = []
    params: Dict[str, Any] = {}
    if table_name != "":
        table_name += "."

    for idx, prop in enumerate(filters):
        if prop.type == "cohort":
            try:
                cohort = Cohort.objects.get(pk=prop.value)
            except Cohort.DoesNotExist:
                final.append(
                    f"{property_operator} 0 = 13"
                )  # If cohort doesn't exist, nothing can match, unless an OR operator is used
            else:

                if person_properties_mode == PersonPropertiesMode.USING_SUBQUERY:
                    person_id_query, cohort_filter_params = format_filter_query(cohort, idx)
                    params = {**params, **cohort_filter_params}
                    final.append(f"{property_operator} {table_name}distinct_id IN ({person_id_query})")
                else:
                    person_id_query, cohort_filter_params = format_cohort_subquery(
                        cohort, idx, custom_match_field=f"{person_id_joined_alias}"
                    )
                    params = {**params, **cohort_filter_params}
                    final.append(f"{property_operator} {person_id_query}")
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
                            filters=filter_query, GET_TEAM_PERSON_DISTINCT_IDS=get_team_distinct_ids_query(team_id),
                        ),
                        table_name=table_name,
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
                transform_expression=lambda column_name: f"argMax(person.{column_name}, _timestamp)",
                property_operator=property_operator,
            )
            final.append(filter_query)
            params.update(filter_params)
        elif prop.type == "element":
            query, filter_params = filter_element(
                {prop.key: prop.value}, operator=prop.operator, prepend="{}_".format(prepend)
            )
            if query:
                final.append(f"{property_operator} {query}")
                params.update(filter_params)
        elif prop.type == "event":
            filter_query, filter_params = prop_filter_json_extract(
                prop,
                idx,
                prepend,
                prop_var="{}properties".format(table_name),
                allow_denormalized_props=allow_denormalized_props,
                property_operator=property_operator,
            )
            final.append(f" {filter_query}")
            params.update(filter_params)
        elif prop.type == "group":
            if group_properties_joined:
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
                    prop, idx, prepend, prop_var=f"group_properties", allow_denormalized_props=False
                )
                group_type_index_var = f"{prepend}_group_type_index_{idx}"
                groups_subquery = GET_GROUP_IDS_BY_PROPERTY_SQL.format(
                    filters=filter_query, group_type_index_var=group_type_index_var
                )
                final.append(f"{property_operator} {table_name}$group_{prop.group_type_index} IN ({groups_subquery})")
                params.update(filter_params)
                params[group_type_index_var] = prop.group_type_index
        elif prop.type in ("static-cohort", "precalculated-cohort"):
            cohort_id = cast(int, prop.value)

            method = format_static_cohort_query if prop.type == "static-cohort" else format_precalculated_cohort_query
            filter_query, filter_params = method(
                cohort_id, idx, prepend=prepend, custom_match_field=person_id_joined_alias
            )  # type: ignore
            if has_person_id_joined:
                final.append(f"{property_operator} {filter_query}")
            else:
                # :TODO: (performance) Avoid subqueries whenever possible, use joins instead
                subquery = GET_DISTINCT_IDS_BY_PERSON_ID_FILTER.format(
                    filters=filter_query, GET_TEAM_PERSON_DISTINCT_IDS=get_team_distinct_ids_query(team_id),
                )
                final.append(f"{property_operator} {table_name}distinct_id IN ({subquery})")
            params.update(filter_params)

    if final:
        # remove the first operator
        return " ".join(final).replace(property_operator, "", 1), params

    return "", params


def prop_filter_json_extract(
    prop: Property,
    idx: int,
    prepend: str = "",
    prop_var: str = "properties",
    allow_denormalized_props: bool = True,
    transform_expression: Optional[Callable[[str], str]] = None,
    property_operator: str = PropertyOperatorType.AND,
) -> Tuple[str, Dict[str, Any]]:
    # TODO: Once all queries are migrated over we can get rid of allow_denormalized_props
    if transform_expression is not None:
        prop_var = transform_expression(prop_var)

    property_expr, is_denormalized = get_property_string_expr(
        property_table(prop), prop.key, f"%(k{prepend}_{idx})s", prop_var, allow_denormalized_props
    )

    if is_denormalized and transform_expression:
        property_expr = transform_expression(property_expr)

    operator = prop.operator
    params: Dict[str, Any] = {}

    if operator == "is_not":
        params = {"k{}_{}".format(prepend, idx): prop.key, "v{}_{}".format(prepend, idx): box_value(prop.value)}
        return (
            " {property_operator} NOT has(%(v{prepend}_{idx})s, {left})".format(
                idx=idx, prepend=prepend, left=property_expr, property_operator=property_operator
            ),
            params,
        )
    elif operator == "icontains":
        value = "%{}%".format(prop.value)
        params = {"k{}_{}".format(prepend, idx): prop.key, "v{}_{}".format(prepend, idx): value}
        return (
            " {property_operator} {left} ILIKE %(v{prepend}_{idx})s".format(
                idx=idx, prepend=prepend, left=property_expr, property_operator=property_operator
            ),
            params,
        )
    elif operator == "not_icontains":
        value = "%{}%".format(prop.value)
        params = {"k{}_{}".format(prepend, idx): prop.key, "v{}_{}".format(prepend, idx): value}
        return (
            " {property_operator} NOT ({left} ILIKE %(v{prepend}_{idx})s)".format(
                idx=idx, prepend=prepend, left=property_expr, property_operator=property_operator
            ),
            params,
        )
    elif operator in ("regex", "not_regex"):
        if not is_valid_regex(prop.value):
            # If OR'ing, shouldn't be a problem since nothing will match this specific clause
            return f"{property_operator} 1 = 2", {}

        params = {"k{}_{}".format(prepend, idx): prop.key, "v{}_{}".format(prepend, idx): prop.value}

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
        params = {"k{}_{}".format(prepend, idx): prop.key, "v{}_{}".format(prepend, idx): prop.value}
        if is_denormalized:
            return (
                " {property_operator} notEmpty({left})".format(left=property_expr, property_operator=property_operator),
                params,
            )
        return (
            " {property_operator} JSONHas({prop_var}, %(k{prepend}_{idx})s)".format(
                idx=idx, prepend=prepend, prop_var=prop_var, property_operator=property_operator
            ),
            params,
        )
    elif operator == "is_not_set":
        params = {"k{}_{}".format(prepend, idx): prop.key, "v{}_{}".format(prepend, idx): prop.value}
        if is_denormalized:
            return (
                " {property_operator} empty({left})".format(left=property_expr, property_operator=property_operator),
                params,
            )
        return (
            " {property_operator} (isNull({left}) OR NOT JSONHas({prop_var}, %(k{prepend}_{idx})s))".format(
                idx=idx, prepend=prepend, prop_var=prop_var, left=property_expr, property_operator=property_operator,
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
            {"k{}_{}".format(prepend, idx): prop.key, prop_value_param_key: prop.value,},
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
            {"k{}_{}".format(prepend, idx): prop.key, prop_value_param_key: prop.value,},
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
            {"k{}_{}".format(prepend, idx): prop.key, prop_value_param_key: prop.value,},
        )
    elif operator == "gt":
        params = {"k{}_{}".format(prepend, idx): prop.key, "v{}_{}".format(prepend, idx): prop.value}
        extract_property_expr = trim_quotes_expr(f"replaceRegexpAll({property_expr}, ' ', '')")
        return (
            f" {property_operator} toFloat64OrNull({extract_property_expr}) > %(v{prepend}_{idx})s",
            params,
        )
    elif operator == "lt":
        params = {"k{}_{}".format(prepend, idx): prop.key, "v{}_{}".format(prepend, idx): prop.value}
        extract_property_expr = trim_quotes_expr(f"replaceRegexpAll({property_expr}, ' ', '')")
        return (
            f" {property_operator} toFloat64OrNull({extract_property_expr}) < %(v{prepend}_{idx})s",
            params,
        )
    else:
        if is_json(prop.value) and not is_denormalized:
            clause = " {property_operator} has(%(v{prepend}_{idx})s, replaceRegexpAll(visitParamExtractRaw({prop_var}, %(k{prepend}_{idx})s),' ', ''))"
            params = {
                "k{}_{}".format(prepend, idx): prop.key,
                "v{}_{}".format(prepend, idx): box_value(prop.value, remove_spaces=True),
            }
        else:
            clause = " {property_operator} has(%(v{prepend}_{idx})s, {left})"
            params = {"k{}_{}".format(prepend, idx): prop.key, "v{}_{}".format(prepend, idx): box_value(prop.value)}
        return (
            clause.format(
                left=property_expr, idx=idx, prepend=prepend, prop_var=prop_var, property_operator=property_operator
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


def get_single_or_multi_property_string_expr(
    breakdown, table: TableWithProperties, query_alias: Literal["prop", "value", None]
):
    """
    When querying for breakdown properties:
     * If the breakdown provided is a string, we extract the JSON from the properties object stored in the DB
     * If it is an array of strings, we extract each of those properties and concatenate them into a single value
    clickhouse parameterizes into a query template from a flat list using % string formatting
    values are escaped and inserted in the query here instead of adding new items to the flat list of values

    :param query_alias:

        Specifies the SQL query alias to add to the expression e.g. `AS prop`. If this is specified as None, then
        no alias will be appended.

    """

    column = "properties" if table == "events" else "person_props"

    if isinstance(breakdown, str) or isinstance(breakdown, int):
        expression, _ = get_property_string_expr(table, str(breakdown), escape_param(breakdown), column)
    else:
        expressions = []
        for b in breakdown:
            expr, _ = get_property_string_expr(table, b, escape_param(b), column)
            expressions.append(expr)

        expression = f"array({','.join(expressions)})"

    if query_alias is None:
        return expression

    return f"{expression} AS {query_alias}"


def get_property_string_expr(
    table: TableWithProperties,
    property_name: PropertyName,
    var: str,
    column: str,
    allow_denormalized_props: bool = True,
    table_alias: Optional[str] = None,
) -> Tuple[str, bool]:
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
    :return:
    """
    materialized_columns = get_materialized_columns(table) if allow_denormalized_props else {}

    table_string = f"{table_alias}." if table_alias is not None else ""

    if allow_denormalized_props and property_name in materialized_columns:
        return f'{table_string}"{materialized_columns[property_name]}"', True

    return trim_quotes_expr(f"JSONExtractRaw({table_string}{column}, {var})"), False


def box_value(value: Any, remove_spaces=False) -> List[Any]:
    if not isinstance(value, List):
        value = [value]
    return [str(value).replace(" ", "") if remove_spaces else str(value) for value in value]


def filter_element(filters: Dict, *, operator: Optional[OperatorType] = None, prepend: str = "") -> Tuple[str, Dict]:
    if not operator:
        operator = "exact"

    params = {}
    final_conditions = []

    if filters.get("selector") is not None:
        if operator not in ("exact", "is_not"):
            raise exceptions.ValidationError(
                'Filtering by element selector only supports operators "equals" and "doesn\'t equal" currently.'
            )
        selectors = filters["selector"] if isinstance(filters["selector"], list) else [filters["selector"]]
        if selectors:
            combination_conditions = []
            for idx, query in enumerate(selectors):
                if not query:  # Skip empty selectors
                    continue
                selector = Selector(query, escape_slashes=False)
                key = f"{prepend}_{idx}_selector_regex"
                params[key] = build_selector_regex(selector)
                combination_conditions.append(f"match(elements_chain, %({key})s)")
            if combination_conditions:
                final_conditions.append(f"({' OR '.join(combination_conditions)})")
        elif operator not in NEGATED_OPERATORS:
            # If a non-negated filter has an empty selector list provided, it can't match anything
            return "0 = 191", {}

    if filters.get("tag_name") is not None:
        if operator not in ("exact", "is_not"):
            raise exceptions.ValidationError(
                'Filtering by element tag only supports operators "equals" and "doesn\'t equal" currently.'
            )
        tag_names = filters["tag_name"] if isinstance(filters["tag_name"], list) else [filters["tag_name"]]
        if tag_names:
            combination_conditions = []
            for idx, tag_name in enumerate(tag_names):
                key = f"{prepend}_{idx}_tag_name_regex"
                params[key] = rf"(^|;){tag_name}(\.|$|;|:)"
                combination_conditions.append(f"match(elements_chain, %({key})s)")
            final_conditions.append(f"({' OR '.join(combination_conditions)})")
        elif operator not in NEGATED_OPERATORS:
            # If a non-negated filter has an empty tag_name list provided, it can't match anything
            return "0 = 192", {}

    attributes: Dict[str, List] = {}
    for key in ["href", "text"]:
        if filters.get(key) is not None:
            attributes[key] = process_ok_values(filters[key], operator)
    if attributes:
        for key, ok_values in attributes.items():
            if ok_values:
                combination_conditions = []
                for idx, value in enumerate(ok_values):
                    optional_flag = "(?i)" if operator.endswith("icontains") else ""
                    params[f"{prepend}_{key}_{idx}_attributes_regex"] = f'{optional_flag}({key}="{value}")'
                    combination_conditions.append(f"match(elements_chain, %({prepend}_{key}_{idx}_attributes_regex)s)")
                final_conditions.append(f"({' OR '.join(combination_conditions)})")
            elif operator not in NEGATED_OPERATORS:
                # If a non-negated filter has an empty href or text list provided, it can't match anything
                return "0 = 193", {}

    if final_conditions:
        return f"{'NOT ' if operator in NEGATED_OPERATORS else ''}({' AND '.join(final_conditions)})", params
    else:
        return "", {}


def process_ok_values(ok_values: Any, operator: OperatorType) -> List[str]:
    if operator.endswith("_set"):
        return [r'[^"]+']
    else:
        # Make sure ok_values is a list
        ok_values = cast(List[str], [str(val) for val in ok_values]) if isinstance(ok_values, list) else [ok_values]
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
        if tag.data.get("tag_name") and isinstance(tag.data["tag_name"], str):
            if tag.data["tag_name"] == "*":
                regex += ".+"
            else:
                regex += tag.data["tag_name"]
        if tag.data.get("attr_class__contains"):
            regex += r".*?\.{}".format(r"\..*?".join(sorted(tag.data["attr_class__contains"])))
        if tag.ch_attributes:
            regex += ".*?"
            for key, value in sorted(tag.ch_attributes.items()):
                regex += '{}="{}".*?'.format(key, value)
        regex += r'([-_a-zA-Z0-9\.:"= ]*?)?($|;|:([^;^\s]*(;|$|\s)))'
        if tag.direct_descendant:
            regex += ".*"
    return regex


def extract_tables_and_properties(props: List[Property]) -> Counter[PropertyIdentifier]:
    return Counter((prop.key, prop.type, prop.group_type_index) for prop in props)
