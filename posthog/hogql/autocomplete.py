import json
from collections.abc import Callable
from copy import deepcopy
from dataclasses import dataclass
from enum import Enum, auto
from typing import Optional, cast

from django.db import models
from django.db.models.functions.comparison import Coalesce

from posthog.schema import (
    AutocompleteCompletionItem,
    AutocompleteCompletionItemKind,
    HogLanguage,
    HogQLAutocomplete,
    HogQLAutocompleteResponse,
)

from posthog.hogql import ast
from posthog.hogql.base import AST, CTE, ConstantType
from posthog.hogql.context import HogQLContext
from posthog.hogql.database.database import HOGQL_CHARACTERS_TO_BE_WRAPPED, Database
from posthog.hogql.database.models import (
    BooleanDatabaseField,
    DatabaseField,
    DateDatabaseField,
    DateTimeDatabaseField,
    FieldOrTable,
    FloatDatabaseField,
    IntegerDatabaseField,
    LazyJoin,
    LazyTable,
    StringDatabaseField,
    StringJSONDatabaseField,
    Table,
    UUIDDatabaseField,
    VirtualTable,
)
from posthog.hogql.database.schema.events import EventsGroupSubTable, EventsPersonSubTable, EventsTable
from posthog.hogql.database.schema.groups import GroupsTable
from posthog.hogql.database.schema.persons import PersonsTable
from posthog.hogql.filters import replace_filters
from posthog.hogql.functions.mapping import ALL_EXPOSED_FUNCTION_NAMES
from posthog.hogql.parser import parse_expr, parse_program, parse_select, parse_string_template
from posthog.hogql.resolver import resolve_types, resolve_types_from_table
from posthog.hogql.resolver_utils import extract_select_queries
from posthog.hogql.timings import HogQLTimings
from posthog.hogql.visitor import TraversingVisitor, clone_expr

from posthog.exceptions_capture import capture_exception
from posthog.hogql_queries.query_runner import get_query_runner
from posthog.models.team.team import Team
from posthog.models.user import User

from products.event_definitions.backend.models.property_definition import PropertyDefinition
from products.product_analytics.backend.models.insight_variable import InsightVariable

from common.hogvm.python.stl import STL
from common.hogvm.python.stl.bytecode import BYTECODE_STL

ALL_HOG_FUNCTIONS = sorted(list(STL.keys()) + list(BYTECODE_STL.keys()))
MATCH_ANY_CHARACTER = "$$_POSTHOG_ANY_$$"
PROPERTY_DEFINITION_LIMIT = 220


def _get_direct_connection_metadata(context: HogQLContext) -> Optional[dict]:
    metadata = context.direct_postgres_connection_metadata
    if metadata is None and context.database is not None:
        metadata = getattr(context.database, "_direct_connection_metadata", None)

    return metadata if isinstance(metadata, dict) else None


def get_connection_supported_functions(context: HogQLContext) -> list[str]:
    metadata = _get_direct_connection_metadata(context)
    if metadata is None:
        return []

    available_functions = metadata.get("available_functions")
    if not isinstance(available_functions, list):
        return []

    return [function_name for function_name in available_functions if isinstance(function_name, str)]


def get_available_functions(language: str, context: HogQLContext) -> list[str]:
    if language == HogLanguage.HOG_QL or language == HogLanguage.HOG_QL_EXPR:
        return sorted(set(ALL_EXPOSED_FUNCTION_NAMES) | set(get_connection_supported_functions(context)))

    return ALL_HOG_FUNCTIONS


def get_direct_table_function_names(context: HogQLContext) -> list[str]:
    metadata = _get_direct_connection_metadata(context)
    if metadata is None:
        return []

    available_table_functions = metadata.get("available_table_functions")
    if not isinstance(available_table_functions, list):
        return []

    return sorted({name for name in available_table_functions if isinstance(name, str)})


def append_function_suggestions(
    suggestions: list[AutocompleteCompletionItem], language: str, context: HogQLContext, prefix: str = ""
) -> None:
    available_functions = get_available_functions(language, context)
    if prefix:
        normalized_prefix = prefix.lower()
        available_functions = [
            function_name
            for function_name in available_functions
            if function_name.lower().startswith(normalized_prefix)
        ]

    extend_responses(
        available_functions,
        suggestions,
        AutocompleteCompletionItemKind.FUNCTION,
        insert_text=lambda key: f"{key}()",
    )


class GetNodeAtPositionTraverser(TraversingVisitor):
    start: int
    end: int
    selects: list[ast.SelectQuery]
    node: Optional[AST] = None
    parent_node: Optional[AST] = None
    nearest_select_query: Optional[ast.SelectQuery] = None
    stack: list[AST]

    def __init__(self, expr: ast.AST, start: int, end: int):
        super().__init__()
        self.selects = []
        self.stack = []
        self.start = start
        self.end = end
        self.visit(expr)

    def visit(self, node: AST | None):
        if node is not None and node.start is not None and node.end is not None:
            parent_node = self.stack[-1] if len(self.stack) > 0 else None
            if self.start >= node.start and self.end <= node.end:
                self.node = node
                self.parent_node = parent_node
                if len(self.selects) > 0:
                    self.nearest_select_query = self.selects[-1]
            elif isinstance(parent_node, ast.Program) or isinstance(parent_node, ast.Block):
                if (
                    self.node is None or isinstance(self.node, ast.Program) or isinstance(self.node, ast.Block)
                ) and node.start >= self.start:
                    self.node = node
                    self.parent_node = parent_node

        if node is not None:
            self.stack.append(node)
            super().visit(node)
            self.stack.pop()
        else:
            super().visit(node)

    def visit_select_query(self, node):
        self.selects.append(node)
        node = super().visit_select_query(node)
        self.selects.pop()


def constant_type_to_database_field(constant_type: ConstantType, name: str) -> DatabaseField:
    if isinstance(constant_type, ast.BooleanType):
        return BooleanDatabaseField(name=name)
    if isinstance(constant_type, ast.IntegerType):
        return IntegerDatabaseField(name=name)
    if isinstance(constant_type, ast.FloatType):
        return FloatDatabaseField(name=name)
    if isinstance(constant_type, ast.StringType):
        return StringDatabaseField(name=name)
    if isinstance(constant_type, ast.DateTimeType):
        return DateTimeDatabaseField(name=name)
    if isinstance(constant_type, ast.DateType):
        return DateDatabaseField(name=name)

    return DatabaseField(name=name)


def convert_field_or_table_to_type_string(
    field_or_table: FieldOrTable, parent_table: str, context: HogQLContext
) -> str | None:
    if isinstance(field_or_table, BooleanDatabaseField):
        return "Boolean"
    if isinstance(field_or_table, IntegerDatabaseField):
        return "Integer"
    if isinstance(field_or_table, FloatDatabaseField):
        return "Float"
    if isinstance(field_or_table, StringDatabaseField):
        return "String"
    if isinstance(field_or_table, UUIDDatabaseField):
        return "String"
    if isinstance(field_or_table, DateTimeDatabaseField):
        return "DateTime"
    if isinstance(field_or_table, DateDatabaseField):
        return "Date"
    if isinstance(field_or_table, StringJSONDatabaseField):
        return "Object"
    if isinstance(field_or_table, ast.ExpressionField):
        parent_table_chain = parent_table.replace("`", "").split(".")
        try:
            field_expr = resolve_types_from_table(field_or_table.expr, parent_table_chain, context, "hogql")
            assert field_expr.type is not None
            constant_type = field_expr.type.resolve_constant_type(context)

            return constant_type.print_type()
        except Exception as e:
            tracking_error = Exception("Cant resolve expression field in autocomplete")
            tracking_error.__cause__ = e
            capture_exception(tracking_error)

            return "Expression"
    if isinstance(field_or_table, ast.Table | ast.LazyJoin):
        return "Table"

    return None


def get_table(context: HogQLContext, join_expr: ast.JoinExpr, ctes: Optional[dict[str, CTE]]) -> None | Table:
    assert context.database is not None

    def resolve_fields_on_table(table: Table | None, table_query: ast.SelectQuery) -> Table | None:
        # Resolve types and only return selected fields
        if table is None:
            return None

        try:
            node = cast(ast.SelectQuery, resolve_types(node=table_query, dialect="hogql", context=context))
            if node.type is None:
                return None

            selected_columns = node.type.columns
            new_fields: dict[str, FieldOrTable] = {}
            for name, field in selected_columns.items():
                if isinstance(field, ast.FieldAliasType):
                    underlying_field_name = field.alias
                    if isinstance(field.type, ast.FieldAliasType):
                        underlying_field_name = field.type.alias
                    elif isinstance(field.type, ast.ConstantType):
                        constant_field = constant_type_to_database_field(field.type, name)
                        new_fields[name] = constant_field
                        continue
                    # `field` is already narrowed to FieldAliasType, so this elif is
                    # provably dead — `FieldAliasType` and `FieldType` are sibling Type
                    # subclasses. Kept as a defensive runtime guard; suppress for mypy.
                    elif isinstance(field, ast.FieldType):  # type: ignore[unreachable]
                        underlying_field_name = field.name  # type: ignore[unreachable]
                    else:
                        underlying_field_name = name
                elif isinstance(field, ast.FieldType):
                    underlying_field_name = field.name
                else:
                    underlying_field_name = name

                new_fields[name] = table.fields[underlying_field_name]

            table_name = table.to_printed_hogql()

            # Return a new table with a reduced field set
            class AnonTable(Table):
                fields: dict[str, FieldOrTable] = new_fields

                def to_printed_hogql(self):
                    # Use the base table name for resolving property definitions later
                    return table_name

            return AnonTable()
        except Exception:
            return None

    if isinstance(join_expr.table, ast.Field):
        table_name = str(join_expr.table.chain[0])
        if ctes is not None:
            # Handle CTEs
            cte = ctes.get(table_name)
            if cte is not None:
                if cte.cte_type == "subquery" and isinstance(cte.expr, ast.SelectQuery):
                    query = cast(ast.SelectQuery, cte.expr)
                    if query.select_from is not None:
                        table = get_table(context, query.select_from, ctes)
                        return resolve_fields_on_table(table, query)

        # Handle a base table
        table_chain = [str(e) for e in join_expr.table.chain]
        if context.database.has_table(table_chain):
            return context.database.get_table(table_chain)
    elif isinstance(join_expr.table, ast.SelectQuery):
        if join_expr.table.select_from is None:
            return None

        # Recursively get the base table
        underlying_table = get_table(context, join_expr.table.select_from, ctes)

        if underlying_table is None:
            return None

        return resolve_fields_on_table(underlying_table, join_expr.table)
    return None


def get_tables_aliases(query: ast.SelectQuery, context: HogQLContext) -> dict[str, ast.Table]:
    tables: dict[str, ast.Table] = {}

    if query.select_from is not None and query.select_from.alias is not None:
        table = get_table(context, query.select_from, query.ctes)
        if table is not None:
            tables[query.select_from.alias] = table

    if query.select_from is not None and query.select_from.next_join is not None:
        next_join: ast.JoinExpr | None = query.select_from.next_join
        while next_join is not None:
            if next_join.alias is not None:
                table = get_table(context, next_join, query.ctes)
                if table is not None:
                    tables[next_join.alias] = table
            next_join = next_join.next_join

    return tables


# Replaces all ast.FieldTraverser with the underlying node
def resolve_table_field_traversers(table: Table, context: HogQLContext) -> Table:
    new_table = deepcopy(table)
    new_fields: dict[str, FieldOrTable] = {}
    for key, field in list(new_table.fields.items()):
        if not isinstance(field, ast.FieldTraverser):
            new_fields[key] = field
            continue

        current_table_or_field: FieldOrTable = new_table
        for chain in field.chain:
            if isinstance(current_table_or_field, Table):
                chain_field = current_table_or_field.fields.get(str(chain))
            elif isinstance(current_table_or_field, LazyJoin):
                chain_field = current_table_or_field.resolve_table(context).fields.get(str(chain))
            elif isinstance(current_table_or_field, DatabaseField):
                chain_field = current_table_or_field
            else:
                # Cant find the field, default back
                new_fields[key] = field
                break

            if chain_field is not None:
                current_table_or_field = chain_field
                new_fields[key] = chain_field

    new_table.fields = new_fields
    return new_table


def append_table_field_to_response(
    table: Table, suggestions: list[AutocompleteCompletionItem], language: str, context: HogQLContext
) -> None:
    keys: list[str] = []
    details: list[str | None] = []
    table_fields = list(table.fields.items())
    for field_name, field_or_table in table_fields:
        # Skip over hidden fields
        if isinstance(field_or_table, ast.DatabaseField) and field_or_table.hidden:
            continue

        keys.append(field_name)
        details.append(convert_field_or_table_to_type_string(field_or_table, table.to_printed_hogql(), context))

    extend_responses(
        keys=keys,
        suggestions=suggestions,
        details=details,
        insert_text=lambda key: f"`{key}`" if any(n in key for n in HOGQL_CHARACTERS_TO_BE_WRAPPED) else key,
    )

    append_function_suggestions(suggestions=suggestions, language=language, context=context)


def extend_responses(
    keys: list[str],
    suggestions: list[AutocompleteCompletionItem],
    kind: AutocompleteCompletionItemKind = AutocompleteCompletionItemKind.VARIABLE,
    insert_text: Optional[Callable[[str], str]] = None,
    details: Optional[list[str | None]] = None,
) -> None:
    suggestions.extend(
        [
            AutocompleteCompletionItem(
                insertText=insert_text(key) if insert_text is not None else key,
                label=key,
                kind=kind,
                detail=details[index] if details is not None else None,
            )
            for index, key in enumerate(keys)
        ]
    )


class VariableFinder(TraversingVisitor):
    node: AST | None = None
    stack: list[AST]
    blocks: list[AST]
    vars: list[set[str]]
    node_vars: set[str]

    def __init__(self, node: ast.AST):
        super().__init__()
        self.node = node
        self.stack = []
        self.blocks = []
        self.vars = []
        self.node_vars = set()

    def visit(self, node: ast.AST | None):
        if node is None:
            return
        if node == self.node:
            for block_vars in self.vars:
                self.node_vars.update(block_vars)
            return

        has_block = isinstance(node, ast.Block) or isinstance(node, ast.Program) or isinstance(node, ast.Function)
        if has_block:
            self.blocks.append(node)
            self.vars.append(set())

        self.stack.append(node)
        super().visit(node)
        self.stack.pop()

        if has_block:
            self.blocks.pop()
            self.vars.pop()

    def visit_variable_declaration(self, node: ast.VariableDeclaration):
        if len(self.vars) > 0:
            self.vars[-1].add(node.name)
        super().visit_variable_declaration(node)


def gather_hog_variables_in_scope(root_node, node) -> list[str]:
    finder = VariableFinder(node)
    finder.visit(root_node)
    return list(finder.node_vars)


class _VariantFlow(Enum):
    """How the variant loop in `get_hogql_autocomplete` proceeds once a suggestion step is done."""

    PROCEED = auto()
    """Keep collecting suggestions for the current variant."""

    TRY_NEXT_VARIANT = auto()
    """Abandon the current variant and parse the next one, without checking what has been collected."""

    STOP = auto()
    """The suggestions are final, so no further variant is parsed."""


# Each entry is a string spliced in at the cursor so a half-written query still parses, paired with
# how far it pushes the end of the word being completed. They are tried in order.
_PARSE_VARIANTS: list[tuple[str, int]] = [
    ("", 0),
    (MATCH_ANY_CHARACTER, len(MATCH_ANY_CHARACTER)),
    ("}", 0),
    (MATCH_ANY_CHARACTER + "}", len(MATCH_ANY_CHARACTER)),
    (" FROM events", 0),
    (f"{MATCH_ANY_CHARACTER} FROM events", len(MATCH_ANY_CHARACTER)),
]


@dataclass(frozen=True, kw_only=True)
class _ParsedVariant:
    root_node: AST
    select_ast: Optional[ast.AST]
    query_to_try: str
    query_start: int
    query_end: int


def _parse_source_query(query: HogQLAutocomplete, team: Team) -> ast.SelectQuery | ast.SelectSetQuery:
    if not query.sourceQuery:
        return parse_select("select 1")

    if query.sourceQuery.kind == "HogQLQuery" and (query.sourceQuery.query is None or query.sourceQuery.query == ""):
        return parse_select("select 1")

    try:
        return get_query_runner(query=query.sourceQuery, team=team).to_query()
    except Exception:
        # A malformed source query (e.g. an unquoted reserved keyword used as an
        # identifier) must not break autocomplete — degrade gracefully instead.
        return parse_select("select 1")


def _parse_for_variant(
    *,
    query: HogQLAutocomplete,
    extra_characters: str,
    length_to_add: int,
    source_query: ast.SelectQuery | ast.SelectSetQuery,
    timings: HogQLTimings,
) -> Optional[_ParsedVariant]:
    """Parse one variant of the query. Returns None when the cursor sits outside any JSON string
    value, which no other variant can change, so the caller stops instead of trying the next one.
    """
    query_to_try = query.query[: query.endPosition] + extra_characters + query.query[query.endPosition :]
    query_start = query.startPosition
    query_end = query.endPosition + length_to_add
    select_ast: Optional[ast.AST] = None

    if query.language == HogLanguage.HOG_QL:
        with timings.measure("parse_select"):
            select_ast = parse_select(query_to_try, timings=timings)
            root_node: ast.AST = select_ast
    elif query.language == HogLanguage.HOG_QL_EXPR:
        with timings.measure("parse_expr"):
            root_node = parse_expr(query_to_try, timings=timings)
            select_ast = cast(ast.SelectQuery, clone_expr(source_query, clear_locations=True))
            select_ast.select = [root_node]
    elif query.language == HogLanguage.HOG_TEMPLATE:
        with timings.measure("parse_template"):
            root_node = parse_string_template(query_to_try, timings=timings)
    elif query.language == HogLanguage.LIQUID:
        with timings.measure("parse_liquid"):
            # Liquid templates are handled similarly to Hog templates for autocomplete
            # We treat them as string templates but with Liquid syntax
            root_node = parse_string_template(query_to_try, timings=timings)
    elif query.language == HogLanguage.HOG:
        with timings.measure("parse_program"):
            root_node = parse_program(query_to_try, timings=timings)
    elif query.language == HogLanguage.HOG_JSON:
        query_to_try, query_start, query_end = extract_json_row(query_to_try, query_start, query_end)
        if query_to_try == "":
            return None
        root_node = parse_string_template(query_to_try, timings=timings)
    else:
        raise ValueError(f"Unsupported autocomplete language: {query.language}")

    return _ParsedVariant(
        root_node=root_node,
        select_ast=select_ast,
        query_to_try=query_to_try,
        query_start=query_start,
        query_end=query_end,
    )


def _suggest_from_globals_chain(
    *, node: ast.Field, query_globals: dict, response: HogQLAutocompleteResponse
) -> _VariantFlow:
    loop_globals: dict | None = query_globals
    for index, key in enumerate(node.chain):
        if MATCH_ANY_CHARACTER in str(key):
            break
        if loop_globals is not None and str(key) in loop_globals:
            loop_globals = loop_globals[str(key)]
        elif index == len(node.chain) - 1:
            break
        else:
            loop_globals = None
            break

    if loop_globals is not None:
        add_globals_to_suggestions(loop_globals, response)
        # looking at a nested global object, no need for other suggestions
        if loop_globals != query_globals:
            return _VariantFlow.STOP

    return _VariantFlow.PROCEED


def _suggest_hog_variables_and_functions(
    *, root_node: AST, node: Optional[AST], language: HogLanguage, response: HogQLAutocompleteResponse
) -> None:
    # For Hog and Liquid, first add all local variables in scope
    hog_vars = gather_hog_variables_in_scope(root_node, node)
    extend_responses(
        keys=hog_vars,
        suggestions=response.suggestions,
        kind=AutocompleteCompletionItemKind.VARIABLE,
    )

    if language != HogLanguage.LIQUID:
        extend_responses(
            ALL_HOG_FUNCTIONS,
            response.suggestions,
            AutocompleteCompletionItemKind.FUNCTION,
            insert_text=lambda key: f"{key}()",
        )


def _suggest_unshadowed_globals(*, query_globals: dict, response: HogQLAutocompleteResponse) -> None:
    # Override globals if a local variable has the same name
    existing_values = {item.label for item in response.suggestions}
    filtered_globals = {key: value for key, value in query_globals.items() if key not in existing_values}
    add_globals_to_suggestions(filtered_globals, response)


def _property_definition_type(table: Table, field: StringJSONDatabaseField) -> Optional[PropertyDefinition.Type]:
    if isinstance(table, EventsPersonSubTable):
        return PropertyDefinition.Type.PERSON
    if isinstance(table, EventsGroupSubTable):
        return PropertyDefinition.Type.GROUP
    if isinstance(table, EventsTable):
        if field.name == "person_properties":
            return PropertyDefinition.Type.PERSON
        return PropertyDefinition.Type.EVENT
    if isinstance(table, PersonsTable):
        return PropertyDefinition.Type.PERSON
    if isinstance(table, GroupsTable):
        return PropertyDefinition.Type.GROUP

    return None


def _suggest_property_names(
    *,
    table: Table,
    field: StringJSONDatabaseField,
    match_term: str,
    context: HogQLContext,
    timings: HogQLTimings,
    response: HogQLAutocompleteResponse,
) -> None:
    property_type = _property_definition_type(table, field)
    if property_type is None:
        return

    with timings.measure("property_filter"):
        property_query = PropertyDefinition.objects.alias(
            effective_project_id=Coalesce("project_id", "team_id", output_field=models.BigIntegerField())
        ).filter(
            effective_project_id=context.team.project_id,  # type: ignore
            name__contains=match_term,
            type=property_type,
        )

    with timings.measure("property_count"):
        total_property_count = property_query.count()

    with timings.measure("property_get_values"):
        properties = property_query[:PROPERTY_DEFINITION_LIMIT].values("name", "property_type")

    extend_responses(
        keys=[prop["name"] for prop in properties],
        suggestions=response.suggestions,
        details=[prop["property_type"] for prop in properties],
    )
    response.incomplete_list = total_property_count > PROPERTY_DEFINITION_LIMIT


def _suggest_nested_table_fields(*, table: Table, context: HogQLContext, response: HogQLAutocompleteResponse) -> None:
    fields = list(table.fields.items())
    extend_responses(
        keys=[key for key, _ in fields],
        suggestions=response.suggestions,
        details=[
            convert_field_or_table_to_type_string(inner_field, table.to_printed_hogql(), context)
            for _, inner_field in fields
        ],
    )


def _suggest_select_fields(
    *,
    node: ast.Field,
    nearest_select: ast.SelectQuery,
    select_from: ast.JoinExpr,
    ctes: Optional[dict[str, CTE]],
    match_term: str,
    language: HogLanguage,
    context: HogQLContext,
    timings: HogQLTimings,
    response: HogQLAutocompleteResponse,
) -> _VariantFlow:
    table = get_table(context, select_from, ctes)
    if table is None:
        if len(node.chain) == 1:
            prefix = "" if str(node.chain[0]) == MATCH_ANY_CHARACTER else str(node.chain[0])
            append_function_suggestions(
                suggestions=response.suggestions,
                language=language,
                context=context,
                prefix=prefix,
            )
        return _VariantFlow.TRY_NEXT_VARIANT

    table_has_alias = select_from.alias is not None
    chain_len = len(node.chain)
    last_table: Table = table
    for index, chain_part in enumerate(node.chain):
        # Return just the table alias
        if table_has_alias and index == 0 and chain_len == 1:
            table_aliases = list(get_tables_aliases(nearest_select, context).keys())
            extend_responses(
                keys=table_aliases,
                suggestions=response.suggestions,
                kind=AutocompleteCompletionItemKind.FOLDER,
                details=["Table"] * len(table_aliases),
            )
            break

        if table_has_alias and index == 0:
            tables = get_tables_aliases(nearest_select, context)
            aliased_table = tables.get(str(chain_part))
            if aliased_table is not None:
                last_table = aliased_table
                continue
            else:
                # Don't continue if the alias is not found in the query
                break

        # Ignore last chain part, it's likely an incomplete word or added characters
        is_last_part = index >= (chain_len - 2)

        # Replaces all ast.FieldTraverser with the underlying node
        last_table = resolve_table_field_traversers(last_table, context)

        if is_last_part:
            if last_table.fields.get(str(chain_part)) is None:
                append_table_field_to_response(
                    table=last_table,
                    suggestions=response.suggestions,
                    language=language,
                    context=context,
                )
                break

            field = last_table.fields[str(chain_part)]

            if isinstance(field, StringJSONDatabaseField):
                _suggest_property_names(
                    table=last_table,
                    field=field,
                    match_term=match_term,
                    context=context,
                    timings=timings,
                    response=response,
                )
            elif isinstance(field, VirtualTable) or isinstance(field, LazyTable):
                _suggest_nested_table_fields(table=field, context=context, response=response)
            elif isinstance(field, LazyJoin):
                _suggest_nested_table_fields(table=field.resolve_table(context), context=context, response=response)
            break
        else:
            field = last_table.fields[str(chain_part)]
            if isinstance(field, Table):
                last_table = field
            elif isinstance(field, LazyJoin):
                last_table = field.resolve_table(context)

    return _VariantFlow.PROCEED


def _suggest_table_names(
    *, node: ast.Field, database: Database, context: HogQLContext, response: HogQLAutocompleteResponse
) -> None:
    table_names = [name for name in database.get_all_table_names() if database.has_table(name)]
    posthog_table_names = [name for name in database.get_posthog_table_names() if database.has_table(name)]

    if len(node.chain) == 1:
        extend_responses(
            keys=table_names,
            suggestions=response.suggestions,
            kind=AutocompleteCompletionItemKind.FOLDER,
            details=["Table"] * len(table_names),
        )
        table_function_names = get_direct_table_function_names(context)
        if table_function_names:
            extend_responses(
                keys=table_function_names,
                suggestions=response.suggestions,
                kind=AutocompleteCompletionItemKind.FUNCTION,
                insert_text=lambda key: f"{key}()",
                details=["Table function"] * len(table_function_names),
            )
    elif node.chain[0] in posthog_table_names:
        pass
    else:
        node_chain_arr = [str(x) for x in node.chain if x != MATCH_ANY_CHARACTER]
        node_chain = ".".join(node_chain_arr)
        filtered_table_names = [x.replace(f"{node_chain}.", "") for x in table_names if node_chain in x]

        extend_responses(
            keys=filtered_table_names,
            suggestions=response.suggestions,
            kind=AutocompleteCompletionItemKind.FOLDER,
            details=["Table"] * len(filtered_table_names),
        )


def _suggest_insight_variables(*, node: ast.Field, team: Team, response: HogQLAutocompleteResponse) -> None:
    if node.chain[0] == MATCH_ANY_CHARACTER or ("variables".startswith(str(node.chain[0])) and len(node.chain) == 1):
        # The `variables.` prefix is not typed out yet, so it is part of what gets inserted
        code_name_prefix = "variables."
    elif len(node.chain) > 1 and node.chain[0] == "variables":
        code_name_prefix = ""
    else:
        return

    insight_variables = InsightVariable.objects.filter(
        team_id=team.pk,
    ).order_by("name")
    code_names = [f"{code_name_prefix}{n.code_name}" for n in insight_variables if n.code_name]
    extend_responses(
        keys=code_names,
        suggestions=response.suggestions,
        kind=AutocompleteCompletionItemKind.CONSTANT,
        details=["Variable"] * len(code_names),
    )


def _suggest_from_schema(
    *,
    query: HogQLAutocomplete,
    parsed: _ParsedVariant,
    select_ast: ast.AST,
    find_node: GetNodeAtPositionTraverser,
    team: Team,
    context: HogQLContext,
    get_database: Callable[[], Database],
    timings: HogQLTimings,
    response: HogQLAutocompleteResponse,
) -> _VariantFlow:
    """Suggestions that resolve against the team's schema, so the database gets built here."""
    database = get_database()

    if query.filters:
        try:
            select_ast = cast(
                ast.SelectQuery,
                replace_filters(cast(ast.SelectQuery, select_ast), query.filters, team, database=database),
            )
        except Exception:
            pass

    ctes: Optional[dict[str, CTE]] = None
    if isinstance(select_ast, ast.SelectQuery):
        ctes = select_ast.ctes
    elif isinstance(select_ast, ast.SelectSetQuery):
        ctes = next(extract_select_queries(select_ast)).ctes
    nearest_select = find_node.nearest_select_query or select_ast

    node = find_node.node
    parent_node = find_node.parent_node

    if (
        isinstance(node, ast.Field)
        and isinstance(nearest_select, ast.SelectQuery)
        and nearest_select.select_from is not None
        and not isinstance(parent_node, ast.JoinExpr)
        and not isinstance(parent_node, ast.Placeholder)
    ):
        # Handle fields
        match_term = parsed.query_to_try[parsed.query_start : parsed.query_end]
        with timings.measure("select_field"):
            return _suggest_select_fields(
                node=node,
                nearest_select=nearest_select,
                select_from=nearest_select.select_from,
                ctes=ctes,
                match_term="" if match_term == MATCH_ANY_CHARACTER else match_term,
                language=query.language,
                context=context,
                timings=timings,
                response=response,
            )

    if isinstance(node, ast.Field) and isinstance(parent_node, ast.JoinExpr):
        # Handle table names
        with timings.measure("table_name"):
            _suggest_table_names(node=node, database=database, context=context, response=response)
    elif isinstance(node, ast.Field) and isinstance(parent_node, ast.Placeholder):
        _suggest_insight_variables(node=node, team=team, response=response)

    return _VariantFlow.PROCEED


def get_hogql_autocomplete(
    query: HogQLAutocomplete,
    team: Team,
    user: Optional[User] = None,
    database_arg: Optional[Database] = None,
) -> HogQLAutocompleteResponse:
    response = HogQLAutocompleteResponse(suggestions=[], incomplete_list=False)
    timings = HogQLTimings()

    built_database: Optional[Database] = database_arg
    context = HogQLContext(team_id=team.pk, team=team, user=user, database=database_arg, timings=timings)

    def get_database() -> Database:
        """`Database.create_for` walks every warehouse table, join and view for the team, which
        dominates the latency of an autocomplete request. Template languages (Hog, Hog templates,
        Liquid) answer from `query.globals` and the STL alone, so they must never reach it.
        """
        nonlocal built_database
        if built_database is None:
            built_database = Database.create_for(team=team, user=user, timings=timings)
            context.database = built_database
        return built_database

    source_query = _parse_source_query(query, team)

    for extra_characters, length_to_add in _PARSE_VARIANTS:
        try:
            parsed = _parse_for_variant(
                query=query,
                extra_characters=extra_characters,
                length_to_add=length_to_add,
                source_query=source_query,
                timings=timings,
            )
            if parsed is None:
                # No variant moves the cursor into a JSON string value, so none of them can help
                break

            with timings.measure("find_node"):
                # to account for the magic F' symbol we append to change antlr's mode
                extra = 2 if query.language == HogLanguage.HOG_TEMPLATE else 0
                find_node = GetNodeAtPositionTraverser(
                    parsed.root_node, parsed.query_start + extra, parsed.query_end + extra
                )
            node = find_node.node

            if HogLanguage.HOG_TEMPLATE and isinstance(node, ast.Constant):
                # Do not show suggestions if not inside the {} part in a template string
                continue

            if isinstance(query.globals, dict) and isinstance(node, ast.Field):
                globals_flow = _suggest_from_globals_chain(node=node, query_globals=query.globals, response=response)
                if globals_flow is _VariantFlow.STOP:
                    break

            if query.language in (HogLanguage.HOG, HogLanguage.HOG_TEMPLATE, HogLanguage.LIQUID):
                _suggest_hog_variables_and_functions(
                    root_node=parsed.root_node, node=node, language=query.language, response=response
                )

            if isinstance(query.globals, dict):
                _suggest_unshadowed_globals(query_globals=query.globals, response=response)

            select_ast = parsed.select_ast
            if select_ast is None:
                break

            schema_flow = _suggest_from_schema(
                query=query,
                parsed=parsed,
                select_ast=select_ast,
                find_node=find_node,
                team=team,
                context=context,
                get_database=get_database,
                timings=timings,
                response=response,
            )
            if schema_flow is _VariantFlow.TRY_NEXT_VARIANT:
                continue
        except Exception:
            pass

        if len(response.suggestions) != 0:
            break

    response.timings = timings.to_list()
    return response


def extract_json_row(query_to_try, query_start, query_end):
    query_row = ""
    for row in query_to_try.split("\n"):
        if query_start - len(row) <= 0:
            query_row = row
            break
        query_start -= len(row) + 1
        query_end -= len(row) + 1
    query_to_try = query_row

    count = query_to_try[:query_start].count('"')
    if count % 2 == 0:  # not in a string
        return "", 0, 0

    start_pos = query_to_try.rfind('"', 0, query_start)
    end_pos = query_to_try.find('"', query_start)
    if end_pos == -1:
        query_to_try = query_to_try[(start_pos + 1) :]
    else:
        query_to_try = query_to_try[(start_pos + 1) : end_pos]
    query_start -= start_pos + 1
    query_end -= start_pos + 1
    return query_to_try, query_start, query_end


def add_globals_to_suggestions(globalVars: dict, response: HogQLAutocompleteResponse):
    if isinstance(globalVars, dict):
        existing_values = {item.label for item in response.suggestions}
        values: list[str | None] = []
        for key, value in globalVars.items():
            if key in existing_values:
                continue
            if isinstance(value, dict):
                values.append("Object")
            elif isinstance(value, list):
                values.append("Array")
            elif isinstance(value, tuple):
                values.append("Tuple")
            else:
                value = json.dumps(value)
                if len(value) > 20:
                    value = value[:20] + "..."
                values.append(value)
        extend_responses(
            keys=list(globalVars.keys()),
            suggestions=response.suggestions,
            kind=AutocompleteCompletionItemKind.VARIABLE,
            details=values,
        )
