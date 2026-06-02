from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
from typing import TypeVar

from posthog.hogql import ast
from posthog.hogql.base import AST
from posthog.hogql.constants import HogQLDialect
from posthog.hogql.context import HogQLContext
from posthog.hogql.visitor import TraversingVisitor

T_AST = TypeVar("T_AST", bound=AST)


@dataclass(frozen=True, slots=True)
class UnknownTypeOccurrence:
    node_type: str
    source: str
    detail: str
    start: int | None = None
    end: int | None = None


@dataclass(frozen=True, slots=True)
class TypeDiagnosticReport:
    unknowns: list[UnknownTypeOccurrence] = field(default_factory=list)

    @property
    def unknown_count(self) -> int:
        return len(self.unknowns)

    def unknowns_by_source(self) -> dict[str, int]:
        return dict(Counter(unknown.source for unknown in self.unknowns))


@dataclass(frozen=True, slots=True)
class ResolvedTypeDiagnostics:
    node: AST
    report: TypeDiagnosticReport


@dataclass(frozen=True, slots=True)
class FunctionCatalogInventory:
    total_entries: int
    entries_by_dialect: dict[str, int]
    entries_with_legacy_signatures: int
    entries_with_precise_signatures: int
    entries_with_wildcard_signatures: int
    entries_with_unknown_return_signatures: int
    aggregate_entries: int
    aggregate_entries_without_return_types: int
    functions_without_signatures: list[str]
    aggregate_functions_without_return_types: list[str]


def resolve_with_type_diagnostics(
    node: T_AST,
    context: HogQLContext,
    dialect: HogQLDialect = "clickhouse",
) -> ResolvedTypeDiagnostics:
    from posthog.hogql.resolver import resolve_types  # noqa: PLC0415 - avoids importing resolver during model startup

    resolved = resolve_types(node, context, dialect=dialect)
    visitor = _UnknownTypeCollector(context=context)
    visitor.visit(resolved)
    return ResolvedTypeDiagnostics(node=resolved, report=TypeDiagnosticReport(unknowns=visitor.unknowns))


def function_catalog_inventory() -> FunctionCatalogInventory:
    from posthog.hogql.functions.mapping import (  # noqa: PLC0415 - avoids importing the function catalog during model startup
        HOGQL_AGGREGATIONS,
        HOGQL_CLICKHOUSE_FUNCTIONS,
    )

    function_catalog = {**HOGQL_CLICKHOUSE_FUNCTIONS, **HOGQL_AGGREGATIONS}
    functions_without_signatures: list[str] = []
    aggregate_functions_without_return_types: list[str] = []
    entries_with_legacy_signatures = 0
    entries_with_precise_signatures = 0
    entries_with_wildcard_signatures = 0
    entries_with_unknown_return_signatures = 0
    aggregate_entries = 0

    for name, meta in function_catalog.items():
        if meta.aggregate:
            aggregate_entries += 1
        if not meta.signatures:
            functions_without_signatures.append(name)
            if meta.aggregate:
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
        if meta.aggregate and has_unknown_return and not has_precise_signature:
            aggregate_functions_without_return_types.append(name)

    return FunctionCatalogInventory(
        total_entries=len(function_catalog),
        entries_by_dialect={"clickhouse": len(function_catalog)},
        entries_with_legacy_signatures=entries_with_legacy_signatures,
        entries_with_precise_signatures=entries_with_precise_signatures,
        entries_with_wildcard_signatures=entries_with_wildcard_signatures,
        entries_with_unknown_return_signatures=entries_with_unknown_return_signatures,
        aggregate_entries=aggregate_entries,
        aggregate_entries_without_return_types=len(aggregate_functions_without_return_types),
        functions_without_signatures=sorted(functions_without_signatures),
        aggregate_functions_without_return_types=sorted(aggregate_functions_without_return_types),
    )


class _UnknownTypeCollector(TraversingVisitor):
    def __init__(self, context: HogQLContext):
        super().__init__()
        self.context = context
        self.unknowns: list[UnknownTypeOccurrence] = []

    def visit(self, node: AST | None) -> None:
        if isinstance(node, ast.Expr) and node.type is not None:
            if isinstance(node.type, ast.SelectQueryType | ast.SelectSetQueryType):
                return super().visit(node)
            constant_type = node.type.resolve_constant_type(self.context)
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
