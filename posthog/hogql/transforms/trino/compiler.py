from __future__ import annotations

import json
import hashlib
from collections.abc import Callable, Mapping
from dataclasses import replace
from typing import Any, cast

from posthog.schema import HogQLFilters, HogQLQueryModifiers, HogQLVariable

from posthog.hogql import ast
from posthog.hogql.context import HogQLContext
from posthog.hogql.database.direct_trino_table import DirectTrinoTable
from posthog.hogql.database.models import SavedQuery
from posthog.hogql.database.trino_locator import resolve_trino_table_locator
from posthog.hogql.errors import (
    NotImplementedError as HogQLNotImplementedError,
    QueryError,
)
from posthog.hogql.filters import replace_filters
from posthog.hogql.parser import parse_select, sanitize_client_parser_mode
from posthog.hogql.placeholders import find_placeholders, replace_placeholders
from posthog.hogql.printer.trino_hogql import TrinoHogQLPrinter
from posthog.hogql.printer.utils import prepare_and_print_ast
from posthog.hogql.resolver import resolve_types
from posthog.hogql.resolver_utils import extract_select_queries
from posthog.hogql.transforms.trino.contracts import (
    TRINO_COMPILER_VERSION,
    TrinoColumn,
    TrinoCompilation,
    TrinoDiagnostic,
    TrinoExpansionMode,
)
from posthog.hogql.transforms.trino.errors import TrinoLoweringError
from posthog.hogql.type_system import runtime_type_from_constant_type
from posthog.hogql.variables import replace_variables
from posthog.hogql.visitor import TraversingVisitor, clone_expr


class _TrinoDependencies(TraversingVisitor):
    def __init__(self, context: HogQLContext, expansion_mode: TrinoExpansionMode) -> None:
        self.context = context
        self.expansion_mode = expansion_mode
        self.bindings: dict[str, object] = {}
        self.warnings: list[TrinoDiagnostic] = []

    def visit_join_expr(self, node: ast.JoinExpr) -> None:
        if node.type is not None:
            self.visit(node.type)
        super().visit_join_expr(node)

    def visit_table_type(self, node: ast.TableType) -> None:
        table = node.table
        locator = resolve_trino_table_locator(table, self.context)
        if (
            isinstance(table, DirectTrinoTable)
            and self.expansion_mode == TrinoExpansionMode.DJANGO
            and self.context.trino_table_locators.get(table.name or "") != locator
        ):
            raise TrinoLoweringError(
                "TRINO_UNMANAGED_TABLE_UNSUPPORTED",
                "external Trino relation",
                detail="This table is not provisioned in the selected managed Trino catalog.",
            )
        if locator is not None:
            self.bindings[table.name or table.to_printed_hogql()] = {
                "locator": locator,
                "fields": sorted(
                    (name, type(value).__name__, getattr(value, "nullable", None))
                    for name, value in table.fields.items()
                ),
            }

    def visit_select_view_type(self, node: ast.SelectViewType) -> None:
        table = node.resolve_database_table(self.context)
        if isinstance(table, SavedQuery):
            self.bindings[node.view_name] = {"id": table.id, "query": table.query}
        super().visit_select_view_type(node)

    def visit_call(self, node: ast.Call) -> None:
        if node.name.lower() in {"median", "medianif", "quantile", "quantileif", "quantiles", "quantilesif"}:
            self.warnings.append(
                TrinoDiagnostic(
                    code="TRINO_APPROXIMATE_QUANTILE_PARITY",
                    message="Trino and ClickHouse use different approximate quantile algorithms. Results can differ.",
                    start=node.start,
                    end=node.end,
                )
            )
        super().visit_call(node)


def compilation_fingerprint(value: object) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"), default=str).encode()).hexdigest()


def compile_trino_query(
    query: str | ast.SelectQuery | ast.SelectSetQuery,
    *,
    context: HogQLContext,
    expansion_mode: TrinoExpansionMode = TrinoExpansionMode.PURE,
    values: Mapping[str, object] | None = None,
    filters: HogQLFilters | None = None,
    variables: Mapping[str, HogQLVariable] | None = None,
    modifiers: HogQLQueryModifiers | None = None,
    default_limit: int | None = None,
    include_hogql: bool = False,
    pretty: bool = False,
    select_transform: Callable[[ast.SelectQuery | ast.SelectSetQuery], ast.SelectQuery | ast.SelectSetQuery]
    | None = None,
) -> TrinoCompilation:
    from posthog.hogql.transforms.trino.manifest import (  # noqa: PLC0415 -- the manifest front end delegates to this compiler
        _validate_pure_inputs,
        find_unsupported_pure_trino_features,
    )

    if expansion_mode not in (TrinoExpansionMode.PURE, TrinoExpansionMode.DJANGO):
        raise ValueError(f"Unknown Trino expansion mode: {expansion_mode}")
    if expansion_mode == TrinoExpansionMode.PURE:
        if select_transform is not None:
            raise ValueError("A select transform needs Django expansion")
        _validate_pure_inputs(filters=filters, variables=variables, modifiers=modifiers)
    placeholders: dict[str, ast.Expr] = {key: ast.Constant(value=value) for key, value in (values or {}).items()}
    node = (
        parse_select(
            query,
            placeholders=placeholders,
            parser_mode=sanitize_client_parser_mode(context.modifiers.parserMode)
            if expansion_mode == TrinoExpansionMode.DJANGO
            else None,
        )
        if isinstance(query, str)
        else clone_expr(query, True)
    )
    if placeholders and not isinstance(query, str):
        node = cast(ast.SelectQuery | ast.SelectSetQuery, replace_placeholders(node, placeholders))
    finder = find_placeholders(node)
    if expansion_mode == TrinoExpansionMode.PURE:
        if finder.has_filters or finder.placeholder_fields or finder.placeholder_expressions:
            raise TrinoLoweringError(
                "TRINO_PURE_PLACEHOLDER_UNSUPPORTED",
                "unresolved placeholder",
                node,
                detail="Pure Trino transpilation only accepts constant values supplied by the caller.",
            )
        find_unsupported_pure_trino_features(node)
    else:
        if context.team is None or context.team.pk != context.team_id:
            raise QueryError("PostHog semantic expansion requires a matching project context.")
        if finder.has_filters:
            node = replace_filters(node, filters, context.team, database=context.database)
        if variables:
            node = replace_variables(node, list(variables.values()), context.team)
        if finder.placeholder_fields or finder.placeholder_expressions:
            replacements: dict[str, Any] = {
                "variables": {variable.code_name: variable.value for variable in (variables or {}).values()},
                **placeholders,
            }
            node = cast(ast.SelectQuery | ast.SelectSetQuery, replace_placeholders(node, replacements))
    if select_transform is not None:
        node = select_transform(node)
    if default_limit is not None:
        for select in extract_select_queries(node):
            if select.limit is None:
                select.limit = ast.Constant(value=default_limit)

    diagnostic_node = clone_expr(node)
    sql, prepared = prepare_and_print_ast(node, context, dialect="trino", pretty=pretty)
    resolved = resolve_types(diagnostic_node, replace(context, values={}, cte_database_table_cache={}), dialect="trino")
    dependencies = _TrinoDependencies(context, expansion_mode)
    dependencies.visit(resolved)
    columns: list[str] = []
    output_columns: list[TrinoColumn] = []
    hogql: str | None = None
    if include_hogql:
        diagnostic_context = replace(context, values={})
        hogql = TrinoHogQLPrinter(context=diagnostic_context).visit(resolved)
        columns_query = next(extract_select_queries(resolved))
        for expression in columns_query.select:
            columns.append(
                expression.alias
                if isinstance(expression, ast.Alias)
                else TrinoHogQLPrinter(
                    context=diagnostic_context, stack=[resolved] if isinstance(resolved, ast.SelectQuery) else []
                ).visit(expression)
            )
    if include_hogql:
        columns_query = next(extract_select_queries(resolved))
        for name, expression in zip(columns, columns_query.select):
            try:
                output_type = expression.type.resolve_constant_type(context) if expression.type else ast.UnknownType()
            except HogQLNotImplementedError:
                output_type = ast.UnknownType()
            output_columns.append(TrinoColumn(name=name, type=runtime_type_from_constant_type(output_type).display()))
    if prepared is not None:
        dependencies.visit(prepared)
    warnings = tuple(dict.fromkeys(dependencies.warnings))
    return TrinoCompilation(
        sql=sql,
        values=dict(context.values),
        hogql=hogql,
        print_columns=tuple(columns),
        output_columns=tuple(output_columns),
        dependencies=tuple(sorted(dependencies.bindings)),
        warnings=warnings,
        fingerprint=compilation_fingerprint(
            {
                "version": TRINO_COMPILER_VERSION,
                "sql": sql,
                "values": context.values,
                "bindings": dependencies.bindings,
                "mode": expansion_mode,
                "timezone": context.database.get_timezone() if context.database is not None else context.timezone,
                "week_start_day": context.database.get_week_start_day()
                if context.database is not None
                else context.week_start_day,
            }
        ),
    )
