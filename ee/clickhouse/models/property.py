import re
from typing import (
    Any,
    Callable,
    Counter,
    Dict,
    List,
    Optional,
    Tuple,
    cast,
)

from django.utils import timezone
from rest_framework import exceptions

from ee.clickhouse.client import sync_execute
from ee.clickhouse.materialized_columns.columns import TableWithProperties, get_materialized_columns
from ee.clickhouse.models.cohort import (
    format_filter_query,
    format_precalculated_cohort_query,
    format_static_cohort_query,
)
from ee.clickhouse.models.util import PersonPropertiesMode, is_json
from ee.clickhouse.sql.events import SELECT_PROP_VALUES_SQL, SELECT_PROP_VALUES_SQL_WITH_FILTER
from ee.clickhouse.sql.person import GET_DISTINCT_IDS_BY_PERSON_ID_FILTER, GET_DISTINCT_IDS_BY_PROPERTY_SQL
from posthog.models.cohort import Cohort
from posthog.models.event import Selector
from posthog.models.property import (
    NEGATED_OPERATORS,
    OperatorType,
    Property,
    PropertyIdentifier,
    PropertyName,
    PropertyType,
)
from posthog.models.team import Team
from posthog.utils import is_valid_regex, relative_date_parse


def parse_prop_clauses(
    filters: List[Property],
    team_id: Optional[int],
    prepend: str = "global",
    table_name: str = "",
    allow_denormalized_props: bool = True,
    has_person_id_joined: bool = True,
    person_properties_mode: PersonPropertiesMode = PersonPropertiesMode.USING_SUBQUERY,
) -> Tuple[str, Dict]:
    final = []
    params: Dict[str, Any] = {}
    if team_id is not None:
        params["team_id"] = team_id
    if table_name != "":
        table_name += "."

    for idx, prop in enumerate(filters):
        if prop.type == "cohort":
            try:
                cohort = Cohort.objects.get(pk=prop.value, team_id=team_id)
            except Cohort.DoesNotExist:
                final.append("AND 0 = 13")  # If cohort doesn't exist, nothing can match
            else:
                person_id_query, cohort_filter_params = format_filter_query(cohort, idx)
                params = {**params, **cohort_filter_params}
                final.append(
                    "AND {table_name}distinct_id IN ({clause})".format(table_name=table_name, clause=person_id_query)
                )
        elif prop.type == "person" and person_properties_mode != PersonPropertiesMode.EXCLUDE:
            # :TODO: Clean this up by using ClickhousePersonQuery over GET_DISTINCT_IDS_BY_PROPERTY_SQL to have access
            #   to materialized columns
            # :TODO: (performance) Avoid subqueries whenever possible, use joins instead
            is_direct_query = person_properties_mode == PersonPropertiesMode.USING_PERSON_PROPERTIES_COLUMN
            filter_query, filter_params = prop_filter_json_extract(
                prop,
                idx,
                "{}person".format(prepend),
                prop_var="person_props" if is_direct_query else "properties",
                allow_denormalized_props=allow_denormalized_props and is_direct_query,
            )
            if is_direct_query:
                final.append(filter_query)
                params.update(filter_params)
            else:
                final.append(
                    "AND {table_name}distinct_id IN ({filter_query})".format(
                        filter_query=GET_DISTINCT_IDS_BY_PROPERTY_SQL.format(filters=filter_query),
                        table_name=table_name,
                    )
                )
                params.update(filter_params)
        elif prop.type == "element":
            query, filter_params = filter_element(
                {prop.key: prop.value}, operator=prop.operator, prepend="{}_".format(idx)
            )
            if query:
                final.append(f" AND {query}")
                params.update(filter_params)
        elif prop.type == "event":
            filter_query, filter_params = prop_filter_json_extract(
                prop,
                idx,
                prepend,
                prop_var="{}properties".format(table_name),
                allow_denormalized_props=allow_denormalized_props,
            )

            final.append(f"{filter_query} AND {table_name}team_id = %(team_id)s" if team_id else filter_query)
            params.update(filter_params)
        elif prop.type == "group":
            # :TRICKY: This assumes group properties have already been joined, as in trends query
            filter_query, filter_params = prop_filter_json_extract(
                prop, idx, prepend, prop_var=f"group_properties_{prop.group_type_index}", allow_denormalized_props=False
            )

            final.append(filter_query)
            params.update(filter_params)
        elif prop.type in ("static-cohort", "precalculated-cohort"):
            cohort_id = cast(int, prop.value)

            method = format_static_cohort_query if prop.type == "static-cohort" else format_precalculated_cohort_query
            filter_query, filter_params = method(cohort_id, idx, prepend=prepend, custom_match_field="person_id")  # type: ignore
            if has_person_id_joined:
                final.append(f" AND {filter_query}")
            else:
                # :TODO: (performance) Avoid subqueries whenever possible, use joins instead
                subquery = GET_DISTINCT_IDS_BY_PERSON_ID_FILTER.format(filters=filter_query)
                final.append(f"AND {table_name}distinct_id IN ({subquery})")
            params.update(filter_params)

    return " ".join(final), params


def prop_filter_json_extract(
    prop: Property,
    idx: int,
    prepend: str = "",
    prop_var: str = "properties",
    allow_denormalized_props: bool = True,
    transform_expression: Optional[Callable[[str], str]] = None,
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
            "AND NOT has(%(v{prepend}_{idx})s, {left})".format(idx=idx, prepend=prepend, left=property_expr),
            params,
        )
    elif operator == "icontains":
        value = "%{}%".format(prop.value)
        params = {"k{}_{}".format(prepend, idx): prop.key, "v{}_{}".format(prepend, idx): value}
        return (
            "AND {left} ILIKE %(v{prepend}_{idx})s".format(idx=idx, prepend=prepend, left=property_expr),
            params,
        )
    elif operator == "not_icontains":
        value = "%{}%".format(prop.value)
        params = {"k{}_{}".format(prepend, idx): prop.key, "v{}_{}".format(prepend, idx): value}
        return (
            "AND NOT ({left} ILIKE %(v{prepend}_{idx})s)".format(idx=idx, prepend=prepend, left=property_expr),
            params,
        )
    elif operator in ("regex", "not_regex"):
        if not is_valid_regex(prop.value):
            return "AND 1 = 2", {}

        params = {"k{}_{}".format(prepend, idx): prop.key, "v{}_{}".format(prepend, idx): prop.value}

        return (
            "AND {regex_function}({left}, %(v{prepend}_{idx})s)".format(
                regex_function="match" if operator == "regex" else "NOT match",
                idx=idx,
                prepend=prepend,
                left=property_expr,
            ),
            params,
        )
    elif operator == "is_set":
        params = {"k{}_{}".format(prepend, idx): prop.key, "v{}_{}".format(prepend, idx): prop.value}
        if is_denormalized:
            return (
                "AND notEmpty({left})".format(left=property_expr),
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
                "AND empty({left})".format(left=property_expr),
                params,
            )
        return (
            "AND (isNull({left}) OR NOT JSONHas({prop_var}, %(k{prepend}_{idx})s))".format(
                idx=idx, prepend=prepend, prop_var=prop_var, left=property_expr
            ),
            params,
        )
    elif operator == "gt":
        params = {"k{}_{}".format(prepend, idx): prop.key, "v{}_{}".format(prepend, idx): prop.value}
        return (
            "AND toFloat64OrNull(trim(BOTH '\"' FROM replaceRegexpAll({left}, ' ', ''))) > %(v{prepend}_{idx})s".format(
                idx=idx, prepend=prepend, left=property_expr,
            ),
            params,
        )
    elif operator == "lt":
        params = {"k{}_{}".format(prepend, idx): prop.key, "v{}_{}".format(prepend, idx): prop.value}
        return (
            "AND toFloat64OrNull(trim(BOTH '\"' FROM replaceRegexpAll({left}, ' ', ''))) < %(v{prepend}_{idx})s".format(
                idx=idx, prepend=prepend, left=property_expr,
            ),
            params,
        )
    else:
        if is_json(prop.value) and not is_denormalized:
            clause = "AND has(%(v{prepend}_{idx})s, replaceRegexpAll(visitParamExtractRaw({prop_var}, %(k{prepend}_{idx})s),' ', ''))"
            params = {
                "k{}_{}".format(prepend, idx): prop.key,
                "v{}_{}".format(prepend, idx): box_value(prop.value, remove_spaces=True),
            }
        else:
            clause = "AND has(%(v{prepend}_{idx})s, {left})"
            params = {"k{}_{}".format(prepend, idx): prop.key, "v{}_{}".format(prepend, idx): box_value(prop.value)}
        return (
            clause.format(left=property_expr, idx=idx, prepend=prepend, prop_var=prop_var),
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
    prop_var: str,
    allow_denormalized_props: bool = True,
) -> Tuple[str, bool]:
    materialized_columns = get_materialized_columns(table) if allow_denormalized_props else {}

    if allow_denormalized_props and property_name in materialized_columns:
        return materialized_columns[property_name], True

    return f"trim(BOTH '\"' FROM JSONExtractRaw({prop_var}, {var}))", False


def box_value(value: Any, remove_spaces=False) -> List[Any]:
    if not isinstance(value, List):
        value = [value]
    return [str(value).replace(" ", "") if remove_spaces else str(value) for value in value]


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
        regex += r"([-_a-zA-Z0-9\.]*?)?($|;|:([^;^\s]*(;|$|\s)))"
        if tag.direct_descendant:
            regex += ".*"
    return regex


def extract_tables_and_properties(props: List[Property]) -> Counter[PropertyIdentifier]:
    return Counter((prop.key, prop.type, prop.group_type_index) for prop in props)
