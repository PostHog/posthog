"""HogQL type-system observability.

Measures type-inference coverage and the shape of the generated SQL during each
prepare+typecheck pass, emitted as low-cardinality Prometheus metrics. Sampling is
gated by ``TYPE_OBSERVABILITY_SAMPLE_RATE``.
"""

from __future__ import annotations

import functools
from collections import Counter
from collections.abc import Callable
from dataclasses import dataclass, field
from random import random
from time import perf_counter
from typing import TYPE_CHECKING, Literal, TypeVar, cast

import structlog
from prometheus_client import (
    Counter as PromCounter,
    Histogram,
)

from posthog.hogql import ast
from posthog.hogql.visitor import TraversingVisitor

from posthog.clickhouse.query_tagging import Product, get_query_tags

if TYPE_CHECKING:
    from posthog.hogql.context import HogQLContext

logger = structlog.get_logger(__name__)

Precision = Literal["precise", "partial", "unknown"]
Labels = dict[str, str]
_F = TypeVar("_F", bound=Callable[..., object])

_BASE_LABELS = ["engine", "dialect", "source"]

TYPECHECK_TOTAL = PromCounter(
    "hogql_typecheck_total",
    "HogQL prepare+typecheck passes by result.",
    labelnames=[*_BASE_LABELS, "result"],
)
TYPECHECK_DURATION_SECONDS = Histogram(
    "hogql_typecheck_duration_seconds",
    "Wall-clock duration of a HogQL prepare+typecheck pass.",
    labelnames=_BASE_LABELS,
    buckets=(0.0005, 0.001, 0.0025, 0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0),
)
EXPRESSION_OBSERVED_TOTAL = PromCounter(
    "hogql_expression_observed_total",
    "HogQL AST expressions visited during type-coverage sampling.",
    labelnames=_BASE_LABELS,
)
EXPRESSION_TYPED_TOTAL = PromCounter(
    "hogql_expression_typed_total",
    "HogQL expressions by inferred type precision.",
    labelnames=[*_BASE_LABELS, "precision"],
)
TYPE_UNKNOWN_TOTAL = PromCounter(
    "hogql_type_unknown_total",
    "HogQL type-inference gaps by reason.",
    labelnames=[*_BASE_LABELS, "reason"],
)
FUNCTION_CALL_TOTAL = PromCounter(
    "hogql_function_call_total",
    "HogQL function calls observed during resolution.",
    labelnames=_BASE_LABELS,
)
FUNCTION_RETURN_TYPED_TOTAL = PromCounter(
    "hogql_function_return_typed_total",
    "HogQL function-call return types by precision.",
    labelnames=[*_BASE_LABELS, "precision"],
)
FUNCTION_SIGNATURE_MISS_TOTAL = PromCounter(
    "hogql_function_signature_miss_total",
    "Function calls with no signature metadata, by function group.",
    labelnames=[*_BASE_LABELS, "function_group"],
)
FUNCTION_SIGNATURE_MISMATCH_TOTAL = PromCounter(
    "hogql_function_signature_mismatch_total",
    "Function calls whose signatures did not resolve a return type, by function group.",
    labelnames=[*_BASE_LABELS, "function_group"],
)
PROPERTY_TYPING_TOTAL = PromCounter(
    "hogql_property_typing_total",
    "Property-definition lookups by source and known/unknown result.",
    labelnames=[*_BASE_LABELS, "result"],
)
MATERIALIZED_PROPERTY_USAGE_TOTAL = PromCounter(
    "hogql_materialized_property_usage_total",
    "Materialized vs JSON property access by result.",
    labelnames=[*_BASE_LABELS, "result"],
)
MATERIALIZED_RANGE_REWRITE_TOTAL = PromCounter(
    "hogql_materialized_range_rewrite_total",
    "Range comparisons on materialized property columns by rewrite outcome. "
    "'fired_compare' rewrote to a bare column comparison; 'fired_if_null' rewrote with an isNotNull(col) guard; "
    "'skipped' means a materialized source was identified but the bare (minmax-eligible) rewrite was unsafe.",
    labelnames=[*_BASE_LABELS, "result"],
)
SQL_SHAPE_TOTAL = PromCounter(
    "hogql_sql_shape_total",
    "Generated SQL shape pathologies by kind.",
    labelnames=[*_BASE_LABELS, "shape"],
)
OBSERVABILITY_ERRORS_TOTAL = PromCounter(
    "hogql_type_observability_errors_total",
    "Swallowed exceptions raised inside the type-observability code itself, by stage. "
    "Observability never propagates its own failures into query execution; this counter makes them visible.",
    labelnames=["stage"],
)


def _log_observability_error(stage: str) -> None:
    """Record and log a swallowed observability failure. Must never raise."""
    try:
        OBSERVABILITY_ERRORS_TOTAL.labels(stage=stage).inc()
        logger.warning("hogql_type_observability_error", stage=stage, exc_info=True)
    except Exception:
        pass


def _safe(fn: _F) -> _F:
    """Wrap an observability entry point so its own exceptions can never reach the query path.

    Instrumentation must never break the thing it observes: on failure we log, count, and
    continue. Functions that produce a value return ``None`` when they fail.
    """

    @functools.wraps(fn)
    def wrapper(*args: object, **kwargs: object) -> object:
        try:
            return fn(*args, **kwargs)
        except Exception:
            _log_observability_error(fn.__name__)
            return None

    return cast(_F, wrapper)


_UNKNOWN_REASONS = {
    "missing_function_signature",
    "signature_mismatch",
    "unsupported_ast_node",
    "unknown_property_metadata",
    "property_metadata_conflict",
    "unknown_database_field_type",
    "set_query_type_conflict",
    "lambda_type_unbound",
    "dialect_gap",
    "transform_invalidated_type",
    "inference_exception",
}

# Allowed values for the `source` label. Bounded to keep Prometheus label cardinality
# fixed even if a call site sets `context.observability_source` to a high-cardinality
# value (URL path, view name, …); anything off-list collapses to "unknown".
# When no explicit source is set, the per-request query-tagging Product (set by the API
# layer) is used, so the bounded Product taxonomy is allowed alongside explicit names.
_KNOWN_SOURCES = {product.value for product in Product} | {
    "sql_editor",
    "insights",
    "api",
    "mcp",
    "subscription",
    "probe",
    "unknown",
}

_MATERIALIZED_PROPERTY_RESULTS = {
    "materialized_column",
    "dynamic_materialized_column",
    "property_group",
    "map_subscript",
    "json",
}

_RANGE_REWRITE_RESULTS = {"fired_compare", "fired_if_null", "skipped"}


@dataclass
class HogQLTypeObservability:
    engine: str = "current"
    dialect: str = "unknown"
    source: str = "unknown"

    started_at: float = field(default_factory=perf_counter)
    result: str = "success"

    expression_count: int = 0
    typed_by_precision: Counter[str] = field(default_factory=Counter)
    unknown_by_reason: Counter[str] = field(default_factory=Counter)

    function_call_count: int = 0
    function_return_by_precision: Counter[str] = field(default_factory=Counter)
    function_signature_miss_by_group: Counter[str] = field(default_factory=Counter)
    function_signature_mismatch_by_group: Counter[str] = field(default_factory=Counter)

    property_typing: Counter[str] = field(default_factory=Counter)
    materialized_property_usage: Counter[str] = field(default_factory=Counter)
    materialized_range_rewrite: Counter[str] = field(default_factory=Counter)

    sql_shape: Counter[str] = field(default_factory=Counter)

    def tags(self) -> Labels:
        return {
            "engine": self.engine,
            "dialect": self.dialect,
            "source": self.source,
        }

    @_safe
    def record_unknown(self, reason: str, count: int = 1) -> None:
        self.unknown_by_reason[_bounded(reason, _UNKNOWN_REASONS)] += count

    @_safe
    def record_function_call(self, function_name: str, return_type: ast.ConstantType, signatures_present: bool) -> None:
        self.function_call_count += 1
        precision = classify_constant_type(return_type)
        self.function_return_by_precision[precision] += 1

        if isinstance(return_type, ast.UnknownType):
            function_group = classify_function_group(function_name)
            if signatures_present:
                self.function_signature_mismatch_by_group[function_group] += 1
                self.record_unknown("signature_mismatch")
            else:
                self.function_signature_miss_by_group[function_group] += 1
                self.record_unknown("missing_function_signature")

    @_safe
    def record_property_definition_lookup(self, property_source: str, known_count: int, total_count: int) -> None:
        property_source = _bounded(property_source, {"event", "person", "group"})
        unknown_count = max(total_count - known_count, 0)
        self.property_typing[f"{property_source}_known"] += known_count
        self.property_typing[f"{property_source}_unknown"] += unknown_count
        if unknown_count:
            self.record_unknown("unknown_property_metadata", unknown_count)

    @_safe
    def record_materialized_property_usage(self, result: str) -> None:
        self.materialized_property_usage[_bounded(result, _MATERIALIZED_PROPERTY_RESULTS)] += 1

    @_safe
    def record_materialized_range_rewrite(self, result: str) -> None:
        self.materialized_range_rewrite[_bounded(result, _RANGE_REWRITE_RESULTS)] += 1


# Fraction of HogQL prepare+typecheck passes to instrument. The collectors walk the whole
# prepared AST, so sampling bounds that cost; set to 0 to disable instrumentation entirely.
TYPE_OBSERVABILITY_SAMPLE_RATE = 0.01


@_safe
def create_hogql_type_observability(
    dialect: str, source: str = "unknown", engine: str = "current"
) -> HogQLTypeObservability | None:
    # Return an accumulator only when this pass is actually sampled. On the unsampled
    # majority we return None, so every per-pass hook (record_*/collect_*/emit_*)
    # short-circuits on a single `is not None` check — unsampled queries pay nothing
    # beyond the sampling draw below.
    if TYPE_OBSERVABILITY_SAMPLE_RATE <= 0 or random() >= TYPE_OBSERVABILITY_SAMPLE_RATE:
        return None
    if source == "unknown":
        source = _source_from_query_tags()
    return HogQLTypeObservability(
        engine=_clean_tag(engine),
        dialect=_clean_tag(dialect),
        source=_bounded(_clean_tag(source), _KNOWN_SOURCES),
    )


def _source_from_query_tags() -> str:
    """Attribute the pass to the product surface the request layer already tagged it with."""
    product = get_query_tags().product
    if product is None:
        return "unknown"
    return str(getattr(product, "value", product))


def classify_expr_type(type_: ast.Type | None, context: HogQLContext | None = None) -> Precision:
    if type_ is None or isinstance(type_, ast.UnknownType):
        return "unknown"
    if isinstance(type_, ast.CallType):
        return classify_constant_type(type_.return_type)
    if isinstance(type_, ast.FieldAliasType):
        return classify_expr_type(type_.type, context)
    if isinstance(type_, ast.ConstantType):
        return classify_constant_type(type_)
    # FieldType/PropertyType hide a concrete scalar behind a reference; resolve it if we have a
    # context. Other catch-all types (SelectQueryType, LazyJoinType, AsteriskType, lambda types)
    # genuinely lack a scalar, so they skip resolution and stay "partial".
    if context is not None and isinstance(type_, (ast.FieldType, ast.PropertyType)):
        return _classify_via_resolution(type_, context)
    return "partial"


def _classify_via_resolution(type_: ast.FieldType | ast.PropertyType, context: HogQLContext) -> Precision:
    """Classify by the resolved scalar. For properties, follow PropertyType.resolve_constant_type's
    precedence but stop before its nullable-String fallback: no metadata means "partial", not
    precise-via-String."""
    from posthog.hogql.property_planner import (
        metadata_constant_type,  # noqa: PLC0415 — observability ← context ← property_planner; deferring breaks the cycle
    )

    try:
        if isinstance(type_, ast.FieldType):
            return classify_constant_type(type_.resolve_constant_type(context))
        if (type_.joined_subquery is not None and type_.joined_subquery_field_name is not None) or isinstance(
            type_.field_type.resolve_database_field(context), ast.StructDatabaseField
        ):
            return classify_constant_type(type_.resolve_constant_type(context))
        metadata_type = metadata_constant_type(type_, context)
        if metadata_type is None:
            return "partial"
        return classify_constant_type(metadata_type)
    except Exception:
        # Resolution can raise for genuinely unresolvable references — expected, so "partial"
        # without bumping the observability error counter.
        return "partial"


def classify_constant_type(type_: ast.ConstantType | None) -> Precision:
    if type_ is None or isinstance(type_, ast.UnknownType):
        return "unknown"
    if isinstance(type_, ast.ArrayType):
        return classify_constant_type(type_.item_type)
    if isinstance(type_, ast.TupleType):
        item_precisions = {classify_constant_type(item_type) for item_type in type_.item_types}
        if "unknown" in item_precisions:
            return "unknown"
        if "partial" in item_precisions:
            return "partial"
        return "precise"
    return "precise"


def classify_function_group(function_name: str) -> str:
    name = function_name.lower()

    if name in {"equals", "notequals", "less", "greater", "lessorequals", "greaterorequals", "in", "notin"}:
        return "comparison"
    if name in {"and", "or", "xor", "not", "if", "multiif"}:
        return "logical"
    if name.startswith("json") or "json" in name:
        return "json"
    if name.startswith("array"):
        return "array"
    if name.startswith("tuple"):
        return "tuple"
    if name.startswith("map"):
        return "map"
    if name.startswith("to") or "cast" in name:
        return "cast"
    if name in {"count", "sum", "avg", "min", "max", "uniq", "quantile"}:
        return "aggregate"
    if name.endswith("state") or name.endswith("merge"):
        return "aggregate_state"
    if "date" in name or "time" in name or name in {"now", "today", "yesterday"}:
        return "datetime"
    if name in {"concat", "substring", "lower", "upper", "replace", "match", "like", "ilike", "regexp"}:
        return "string"
    if "url" in name:
        return "url"
    if name in {"abs", "round", "floor", "ceil", "sqrt", "pow", "exp", "log"}:
        return "math"
    if name.startswith("hogql") or name.startswith("__"):
        return "posthog"
    return "unknown"


@_safe
def collect_hogql_type_coverage(
    node: ast.AST, stats: HogQLTypeObservability | None, context: HogQLContext | None = None
) -> None:
    if stats is None:
        return
    TypeCoverageCollector(stats, context).visit(node)


@_safe
def collect_hogql_sql_shape(node: ast.AST, stats: HogQLTypeObservability | None) -> None:
    if stats is None:
        return
    SQLShapeCollector(stats).visit(node)


@_safe
def emit_hogql_type_observability(stats: HogQLTypeObservability | None) -> None:
    if stats is None:
        return

    base = stats.tags()
    TYPECHECK_TOTAL.labels(**base, result=_clean_tag(stats.result)).inc()
    TYPECHECK_DURATION_SECONDS.labels(**base).observe(max(0.0, perf_counter() - stats.started_at))

    if stats.expression_count:
        EXPRESSION_OBSERVED_TOTAL.labels(**base).inc(stats.expression_count)
    _emit_counter(EXPRESSION_TYPED_TOTAL, "precision", stats.typed_by_precision, base)
    _emit_counter(TYPE_UNKNOWN_TOTAL, "reason", stats.unknown_by_reason, base)

    if stats.function_call_count:
        FUNCTION_CALL_TOTAL.labels(**base).inc(stats.function_call_count)
    _emit_counter(FUNCTION_RETURN_TYPED_TOTAL, "precision", stats.function_return_by_precision, base)
    _emit_counter(FUNCTION_SIGNATURE_MISS_TOTAL, "function_group", stats.function_signature_miss_by_group, base)
    _emit_counter(FUNCTION_SIGNATURE_MISMATCH_TOTAL, "function_group", stats.function_signature_mismatch_by_group, base)
    _emit_counter(PROPERTY_TYPING_TOTAL, "result", stats.property_typing, base)
    _emit_counter(MATERIALIZED_PROPERTY_USAGE_TOTAL, "result", stats.materialized_property_usage, base)
    _emit_counter(MATERIALIZED_RANGE_REWRITE_TOTAL, "result", stats.materialized_range_rewrite, base)
    _emit_counter(SQL_SHAPE_TOTAL, "shape", stats.sql_shape, base)


class TypeCoverageCollector(TraversingVisitor):
    def __init__(self, stats: HogQLTypeObservability, context: HogQLContext | None = None):
        super().__init__()
        self.stats = stats
        self.context = context

    def visit(self, node: ast.AST | None) -> None:
        if isinstance(node, ast.Expr):
            self.stats.expression_count += 1
            self.stats.typed_by_precision[classify_expr_type(node.type, self.context)] += 1
        return super().visit(node)


# Type-coercion cast functions. Every matching call is counted (regardless of whether its
# argument is a property, field, or constant) and each also bumps property_conversion_wrapper.
_CAST_SHAPES = {
    "todatetime": "datetime_cast",
    "todatetime64": "datetime_cast",
    "todate": "datetime_cast",
    "tofloat": "numeric_cast",
    "tofloat32": "numeric_cast",
    "tofloat64": "numeric_cast",
    "toint": "numeric_cast",
    "toint32": "numeric_cast",
    "toint64": "numeric_cast",
    "todecimal": "numeric_cast",
    "tostring": "string_cast",
    "tofixedstring": "string_cast",
    "tobool": "boolean_cast",
}


class SQLShapeCollector(TraversingVisitor):
    def __init__(self, stats: HogQLTypeObservability):
        super().__init__()
        self.stats = stats

    def visit_call(self, node: ast.Call) -> None:
        name = node.name.lower()
        cast_shape = _CAST_SHAPES.get(name)
        if cast_shape is not None:
            self.stats.sql_shape[cast_shape] += 1
            self.stats.sql_shape["property_conversion_wrapper"] += 1
        elif name == "ifnull":
            self.stats.sql_shape["nullable_comparison_wrapper"] += 1
        elif name == "assumenotnull":
            self.stats.sql_shape["assume_not_null"] += 1
        elif name == "jsonextractraw":
            self.stats.sql_shape["json_extract_raw"] += 1
        elif name.startswith("jsonextract") or name in {"json_value", "jsonhas", "jsontype", "jsonlength"}:
            self.stats.sql_shape["json_extract"] += 1

        super().visit_call(node)


def _emit_counter(metric: PromCounter, label_name: str, values: Counter[str], base: Labels) -> None:
    for label_value, count in values.items():
        if count:
            metric.labels(**base, **{label_name: _clean_tag(label_value)}).inc(count)


def _bounded(value: str, allowed_values: set[str]) -> str:
    return value if value in allowed_values else "unknown"


def _clean_tag(value: str) -> str:
    safe = "".join(character if character.isalnum() or character in {"_", "-"} else "_" for character in str(value))
    return safe[:64] or "unknown"
