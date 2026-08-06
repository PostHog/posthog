from __future__ import annotations

import dataclasses
from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import cast

from posthog.hogql import ast
from posthog.hogql.base import _T_AST, AST
from posthog.hogql.constants import HogQLDialect
from posthog.hogql.context import HogQLContext
from posthog.hogql.errors import NotImplementedError as HogQLNotImplementedError
from posthog.hogql.type_system import RuntimeType, parse_sql_runtime_type, runtime_type_from_constant_type
from posthog.hogql.visitor import TraversingVisitor, clone_expr

OPTIMIZER_BLOCKER_SOURCES = frozenset(
    {
        "missing_function_signature",
        "unknown_cast_target",
        "unknown_expression",
        "unknown_field",
    }
)


@dataclass(frozen=True, slots=True)
class UnknownTypeOccurrence:
    node_type: str
    source: str
    detail: str
    start: int | None = None
    end: int | None = None


@dataclass(frozen=True, slots=True)
class SelectExpressionTypeDiagnostic:
    index: int
    alias: str | None
    expression: str
    constant_type: ast.ConstantType
    runtime_type: RuntimeType
    start: int | None = None
    end: int | None = None

    @property
    def runtime_type_display(self) -> str:
        return self.runtime_type.display()

    def debug_dict(self) -> dict[str, object]:
        return {
            "index": self.index,
            "alias": self.alias,
            "expression": self.expression,
            "constant_type": self.constant_type.print_type(),
            "runtime_type": self.runtime_type.debug_dict(),
            "start": self.start,
            "end": self.end,
        }


@dataclass(frozen=True, slots=True)
class SelectExpressionTypeNameComparison:
    index: int
    alias: str | None
    expression: str
    inferred_runtime_type: RuntimeType
    clickhouse_type_name: str
    clickhouse_runtime_type: RuntimeType
    family_matches: bool
    nullability_matches: bool

    @property
    def matches(self) -> bool:
        return self.family_matches and self.nullability_matches


@dataclass(frozen=True, slots=True)
class TypeDiagnosticReport:
    unknowns: list[UnknownTypeOccurrence] = field(default_factory=list)
    select_expressions: list[SelectExpressionTypeDiagnostic] = field(default_factory=list)

    @property
    def unknown_count(self) -> int:
        return len(self.unknowns)

    def unknowns_by_source(self) -> dict[str, int]:
        return dict(Counter(unknown.source for unknown in self.unknowns))

    def unknowns_by_detail(self) -> dict[str, int]:
        return dict(Counter(unknown.detail for unknown in self.unknowns))

    @property
    def optimizer_blockers(self) -> list[UnknownTypeOccurrence]:
        return [unknown for unknown in self.unknowns if unknown.source in OPTIMIZER_BLOCKER_SOURCES]

    @property
    def optimizer_blocker_count(self) -> int:
        return len(self.optimizer_blockers)

    def optimizer_blockers_by_source(self) -> dict[str, int]:
        return dict(Counter(unknown.source for unknown in self.optimizer_blockers))

    def select_expression_types_by_alias(self) -> dict[str, SelectExpressionTypeDiagnostic]:
        return {diagnostic.alias: diagnostic for diagnostic in self.select_expressions if diagnostic.alias is not None}


@dataclass(frozen=True, slots=True)
class ResolvedTypeDiagnostics:
    node: AST
    report: TypeDiagnosticReport


@dataclass(frozen=True, slots=True)
class FunctionCatalogInventory:
    total_entries: int
    entries_by_dialect: dict[str, int]
    entries_with_legacy_signatures: int
    entries_with_generic_inference: int
    entries_with_precise_generic_inference: int
    entries_with_precise_signatures: int
    entries_with_wildcard_signatures: int
    entries_with_unknown_return_signatures: int
    aggregate_entries: int
    aggregate_entries_without_return_types: int
    functions_without_signatures: list[str]
    functions_without_type_inference: list[str]
    aggregate_functions_without_return_types: list[str]


def resolve_with_type_diagnostics(
    node: _T_AST,
    context: HogQLContext,
    dialect: HogQLDialect = "clickhouse",
) -> ResolvedTypeDiagnostics:
    from posthog.hogql.resolver import resolve_types  # noqa: PLC0415 - avoids importing resolver during model startup

    resolved = resolve_types(node, context, dialect=dialect)
    visitor = _UnknownTypeCollector(context=context)
    visitor.visit(resolved)
    select_expressions = _select_expression_diagnostics(resolved, context=context, dialect=dialect)
    return ResolvedTypeDiagnostics(
        node=resolved,
        report=TypeDiagnosticReport(unknowns=visitor.unknowns, select_expressions=select_expressions),
    )


def build_select_expression_type_name_query(
    node: ast.SelectQuery,
    context: HogQLContext,
    dialect: HogQLDialect = "clickhouse",
    expression_indexes: Sequence[int] | None = None,
) -> ast.SelectQuery:
    diagnostics = resolve_with_type_diagnostics(node, context=context, dialect=dialect)
    resolved = cast(ast.SelectQuery, diagnostics.node)
    selected_indexes = (
        set(expression_indexes)
        if expression_indexes is not None
        else {diagnostic.index for diagnostic in diagnostics.report.select_expressions}
    )

    type_name_select: list[ast.Expr] = []
    for diagnostic, expression in zip(diagnostics.report.select_expressions, resolved.select):
        if diagnostic.index not in selected_indexes:
            continue

        unwrapped = _select_expression_inner(expression)
        type_name_select.append(
            ast.Alias(
                alias=f"__hogql_type_{diagnostic.index + 1}",
                expr=ast.Call(name="toTypeName", args=[clone_expr(unwrapped, clear_types=True)]),
            )
        )

    cloned = cast(ast.SelectQuery, clone_expr(resolved, clear_types=True))
    return dataclasses.replace(
        cloned,
        select=type_name_select,
        order_by=None,
        limit_by=None,
        limit=None,
        limit_with_ties=None,
        limit_percent=None,
        offset=None,
    )


def compare_select_expression_types_with_type_names(
    report: TypeDiagnosticReport,
    type_names: Sequence[str],
    dialect: HogQLDialect = "clickhouse",
    expression_indexes: Sequence[int] | None = None,
) -> list[SelectExpressionTypeNameComparison]:
    selected_indexes = set(expression_indexes) if expression_indexes is not None else None
    diagnostics = [
        diagnostic
        for diagnostic in report.select_expressions
        if selected_indexes is None or diagnostic.index in selected_indexes
    ]
    if len(type_names) != len(diagnostics):
        raise ValueError(f"Expected {len(diagnostics)} ClickHouse type name(s), got {len(type_names)}")

    comparisons: list[SelectExpressionTypeNameComparison] = []
    for diagnostic, type_name in zip(diagnostics, type_names):
        clickhouse_runtime_type = parse_sql_runtime_type(type_name, dialect=dialect)
        comparisons.append(
            SelectExpressionTypeNameComparison(
                index=diagnostic.index,
                alias=diagnostic.alias,
                expression=diagnostic.expression,
                inferred_runtime_type=diagnostic.runtime_type,
                clickhouse_type_name=type_name,
                clickhouse_runtime_type=clickhouse_runtime_type,
                family_matches=diagnostic.runtime_type.family == clickhouse_runtime_type.family,
                nullability_matches=diagnostic.runtime_type.nullable == clickhouse_runtime_type.nullable,
            )
        )
    return comparisons


def function_catalog_inventory() -> FunctionCatalogInventory:
    from posthog.hogql.functions.mapping import (  # noqa: PLC0415 - avoids importing the function catalog during model startup
        HOGQL_AGGREGATIONS,
        HOGQL_CLICKHOUSE_FUNCTIONS,
    )

    function_catalog = {**HOGQL_CLICKHOUSE_FUNCTIONS, **HOGQL_AGGREGATIONS}
    functions_without_signatures: list[str] = []
    functions_without_type_inference: list[str] = []
    aggregate_functions_without_return_types: list[str] = []
    entries_with_legacy_signatures = 0
    entries_with_generic_inference = 0
    entries_with_precise_generic_inference = 0
    entries_with_precise_signatures = 0
    entries_with_wildcard_signatures = 0
    entries_with_unknown_return_signatures = 0
    aggregate_entries = 0

    for name, meta in function_catalog.items():
        if meta.aggregate:
            aggregate_entries += 1

        generic_return_type = _generic_catalog_return_type(name, min_args=meta.min_args)
        has_generic_inference = generic_return_type is not None
        has_precise_generic_inference = generic_return_type is not None and not isinstance(
            generic_return_type, ast.UnknownType
        )
        if has_generic_inference:
            entries_with_generic_inference += 1
        if has_precise_generic_inference:
            entries_with_precise_generic_inference += 1

        if not meta.signatures:
            functions_without_signatures.append(name)
            if not has_precise_generic_inference:
                functions_without_type_inference.append(name)
            if meta.aggregate and not has_precise_generic_inference:
                aggregate_functions_without_return_types.append(name)
            continue

        entries_with_legacy_signatures += 1
        has_precise_signature = False
        has_wildcard_signature = False
        has_unknown_return = False
        for arg_types, return_type in meta.signatures:
            if isinstance(return_type, ast.UnknownType):
                has_unknown_return = True
            else:
                has_precise_signature = True
            if any(isinstance(arg_type, ast.UnknownType) for arg_type in arg_types):
                has_wildcard_signature = True

        if has_precise_signature:
            entries_with_precise_signatures += 1
        if has_wildcard_signature:
            entries_with_wildcard_signatures += 1
        if has_unknown_return:
            entries_with_unknown_return_signatures += 1
        if meta.aggregate and has_unknown_return and not has_precise_signature and not has_precise_generic_inference:
            aggregate_functions_without_return_types.append(name)

    return FunctionCatalogInventory(
        total_entries=len(function_catalog),
        entries_by_dialect={"clickhouse": len(function_catalog)},
        entries_with_legacy_signatures=entries_with_legacy_signatures,
        entries_with_generic_inference=entries_with_generic_inference,
        entries_with_precise_generic_inference=entries_with_precise_generic_inference,
        entries_with_precise_signatures=entries_with_precise_signatures,
        entries_with_wildcard_signatures=entries_with_wildcard_signatures,
        entries_with_unknown_return_signatures=entries_with_unknown_return_signatures,
        aggregate_entries=aggregate_entries,
        aggregate_entries_without_return_types=len(aggregate_functions_without_return_types),
        functions_without_signatures=sorted(functions_without_signatures),
        functions_without_type_inference=sorted(functions_without_type_inference),
        aggregate_functions_without_return_types=sorted(aggregate_functions_without_return_types),
    )


def _generic_catalog_return_type(name: str, min_args: int) -> ast.ConstantType | None:
    from posthog.hogql.type_system import infer_function_return_type  # noqa: PLC0415 - keeps diagnostics import-light

    inference = infer_function_return_type(
        name,
        [ast.UnknownType(nullable=False) for _ in range(min_args)],
        args=None,
        meta=None,
        dialect="clickhouse",
    )
    if inference.source != "generic":
        return None
    return inference.return_type


def _select_expression_diagnostics(
    node: AST,
    context: HogQLContext,
    dialect: HogQLDialect,
) -> list[SelectExpressionTypeDiagnostic]:
    if not isinstance(node, ast.SelectQuery):
        return []

    diagnostics: list[SelectExpressionTypeDiagnostic] = []
    for index, expression in enumerate(node.select):
        inner_expression = _select_expression_inner(expression)
        expression_type = expression.type or inner_expression.type
        if expression_type is None:
            constant_type: ast.ConstantType = ast.UnknownType()
        else:
            try:
                constant_type = expression_type.resolve_constant_type(context)
            except HogQLNotImplementedError:
                constant_type = ast.UnknownType()

        diagnostics.append(
            SelectExpressionTypeDiagnostic(
                index=index,
                alias=expression.alias if isinstance(expression, ast.Alias) else None,
                expression=_print_select_expression(inner_expression, query=node, context=context, dialect=dialect),
                constant_type=constant_type,
                runtime_type=runtime_type_from_constant_type(constant_type),
                start=expression.start,
                end=expression.end,
            )
        )
    return diagnostics


def _select_expression_inner(expression: ast.Expr) -> ast.Expr:
    return expression.expr if isinstance(expression, ast.Alias) else expression


def _print_select_expression(
    expression: ast.Expr,
    query: ast.SelectQuery,
    context: HogQLContext,
    dialect: HogQLDialect,
) -> str:
    from posthog.hogql.printer import print_prepared_ast  # noqa: PLC0415 - keeps diagnostics import-light

    try:
        return print_prepared_ast(expression, context=context, dialect=dialect, stack=[query])
    except Exception:
        return type(expression).__name__


class _UnknownTypeCollector(TraversingVisitor):
    def __init__(self, context: HogQLContext):
        super().__init__()
        self.context = context
        self.unknowns: list[UnknownTypeOccurrence] = []

    def visit(self, node: AST | None) -> None:
        if isinstance(node, ast.Expr) and node.type is not None:
            if isinstance(node.type, ast.SelectQueryType | ast.SelectSetQueryType):
                return super().visit(node)
            try:
                constant_type = node.type.resolve_constant_type(self.context)
            except HogQLNotImplementedError:
                return super().visit(node)
            if isinstance(constant_type, ast.UnknownType):
                self.unknowns.append(
                    UnknownTypeOccurrence(
                        node_type=type(node).__name__,
                        source=self._source_for_node(node),
                        detail=self._detail_for_node(node),
                        start=node.start,
                        end=node.end,
                    )
                )
        return super().visit(node)

    def _source_for_node(self, node: ast.Expr) -> str:
        if isinstance(node.type, ast.CallType):
            return "missing_function_signature"
        if isinstance(node, ast.Field):
            return "unknown_field"
        if isinstance(node, ast.TypeCast | ast.TryCast):
            return "unknown_cast_target"
        return "unknown_expression"

    def _detail_for_node(self, node: ast.Expr) -> str:
        if isinstance(node.type, ast.CallType):
            return node.type.name
        if isinstance(node, ast.Field):
            return ".".join(str(part) for part in node.chain)
        if isinstance(node, ast.TypeCast | ast.TryCast):
            return node.type_name
        return type(node).__name__
