import re
from collections import (
    Counter,
    Counter as TCounter,
)
from collections.abc import Iterable
from typing import Any, Literal, Optional, Union, cast

from posthog.hogql import ast
from posthog.hogql.database.s3_table import S3Table
from posthog.hogql.escape_sql import escape_clickhouse_identifier
from posthog.hogql.parser import parse_expr
from posthog.hogql.visitor import TraversingVisitor

from posthog.clickhouse.kafka_engine import trim_quotes_expr
from posthog.clickhouse.materialized_columns import TableWithProperties, get_materialized_column_for_property
from posthog.models.event import Selector
from posthog.models.event.sql import EVENTS_PROPERTIES_JSON_SUBCOLUMNS, PERSON_PROPERTIES_JSON_SUBCOLUMNS
from posthog.models.property import Property, PropertyGroup, PropertyIdentifier, PropertyName

from products.actions.backend.models.action import Action
from products.actions.backend.models.util import get_action_tables_and_properties


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


def _chain_escaped_value(value: str) -> str:
    # A quoted value in the chain escapes double quotes as \" (_escape in
    # posthog/models/element/element.py). A selector can write the quote either
    # pre-escaped ([title="say \"hi\""]) or bare inside single quotes
    # ([title='say "hi"']), so normalize to the chain's form to match both.
    return value.replace(r"\"", '"').replace('"', r"\"")


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
                regex += rf'{re.escape(key)}="{re.escape(_chain_escaped_value(str(value)))}".*?'
        # The rest of the element can carry characters an allowlist cannot
        # anticipate (classes like w-1/2 or !mt-0), so skip anything up to the
        # `;` element separator.
        regex += r"[^;]*?($|;|:([^;^\s]*(;|$|\s)))"
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
