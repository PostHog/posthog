"""Fingerprint catalog metrics, and classify a query shape against them.

A query shape and a metric definition meet on ``MeasureFingerprint``. A HogQL definition is
fingerprinted as written. A node or single-series trends definition is first printed as the HogQL an
analyst would write for it, so both sides go through the one extractor.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable
from datetime import datetime
from typing import Any
from uuid import UUID

import structlog

from posthog.hogql import ast
from posthog.hogql.parser import parse_expr
from posthog.hogql.property import property_to_expr

from posthog.dataclasses import frozen
from posthog.models import Team

from ..facade.enums import HOGQL_DEFINITION_KIND, MetricStatus, ShapeOutcome
from ..models import Metric
from .measure_fingerprint import MeasureExtractionError, MeasureFingerprint, extract_measures

logger = structlog.get_logger(__name__)

_PROPERTY_MATH = frozenset({"sum", "avg", "min", "max", "median"})
_QUANTILE_MATH = {"p75": 0.75, "p90": 0.9, "p95": 0.95, "p99": 0.99}


@frozen
class CatalogMeasure:
    """One measure of one catalog metric. A metric with several aggregates has several."""

    metric_id: UUID
    status: MetricStatus
    created_at: datetime
    fingerprint: MeasureFingerprint


@frozen
class ShapeMatch:
    outcome: ShapeOutcome
    metric_id: UUID | None = None
    metric_status: MetricStatus | None = None


class CatalogIndex:
    """The catalog's measures, indexed for classifying many query shapes in one scan."""

    def __init__(self, measures: Iterable[CatalogMeasure], *, unmeasured_metric_ids: Iterable[UUID] = ()) -> None:
        self._by_digest: dict[str, list[CatalogMeasure]] = defaultdict(list)
        self._by_source: dict[tuple[tuple[str, ...], str], list[CatalogMeasure]] = defaultdict(list)
        for measure in measures:
            self._by_digest[measure.fingerprint.digest].append(measure)
            self._by_source[(measure.fingerprint.tables, measure.fingerprint.aggregate)].append(measure)
        # Metrics the index cannot match: markdown, funnels, multi-series trends, or no aggregate.
        # They still count direct runs; they never cover a shape.
        self.unmeasured_metric_ids = frozenset(unmeasured_metric_ids)

    @classmethod
    def for_team(cls, team: Team) -> CatalogIndex:
        measures: list[CatalogMeasure] = []
        unmeasured: list[UUID] = []
        for metric in Metric.objects.for_team(team.id).filter(deleted=False):
            fingerprints = fingerprint_metric(metric, team)
            if not fingerprints:
                unmeasured.append(metric.id)
            measures.extend(
                CatalogMeasure(
                    metric_id=metric.id,
                    status=MetricStatus(metric.status),
                    created_at=metric.created_at,
                    fingerprint=fingerprint,
                )
                for fingerprint in fingerprints
            )
        return cls(measures, unmeasured_metric_ids=unmeasured)

    def classify(self, shape: MeasureFingerprint) -> ShapeMatch:
        """``covered`` when the shape equals any measure of a metric, ``slice`` when it adds filters to one."""
        exact = self._by_digest.get(shape.digest)
        if exact:
            return _match(ShapeOutcome.COVERED, exact)

        shape_predicate = set(shape.predicate)
        narrower = [
            measure
            for measure in self._by_source.get((shape.tables, shape.aggregate), [])
            if set(measure.fingerprint.predicate) < shape_predicate
        ]
        if narrower:
            return _match(ShapeOutcome.SLICE, narrower)
        return ShapeMatch(outcome=ShapeOutcome.UNCOVERED)


def _match(outcome: ShapeOutcome, candidates: list[CatalogMeasure]) -> ShapeMatch:
    # An approved metric is the answer people should reach for, so it wins over a proposed one;
    # the older metric then wins, and the id keeps the choice stable between scans.
    best = min(
        candidates,
        key=lambda measure: (measure.status != MetricStatus.APPROVED, measure.created_at, str(measure.metric_id)),
    )
    return ShapeMatch(outcome=outcome, metric_id=best.metric_id, metric_status=best.status)


def fingerprint_metric(metric: Metric, team: Team) -> list[MeasureFingerprint]:
    definition = metric.definition or {}
    if definition.get("kind") == HOGQL_DEFINITION_KIND:
        query = definition.get("query")
    else:
        query = definition_to_hogql(definition, team)
    if not query:
        return []
    try:
        return extract_measures(query)
    except MeasureExtractionError as error:
        logger.warning("data_catalog_metric_fingerprint_failed", metric_id=str(metric.id), error=str(error))
        return []


def definition_to_hogql(definition: dict[str, Any], team: Team) -> str | None:
    """Print a node or single-series trends definition as plain HogQL, or None when no single
    aggregate captures it (funnels, formulas over several series, markdown)."""
    node: dict[str, Any] = definition
    query_filters: list[ast.Expr] = []
    if definition.get("kind") == "TrendsQuery":
        series = definition.get("series") or []
        if len(series) != 1:
            return None
        node = series[0]
        query_filters = _filters(definition.get("properties"), team)
        if definition.get("filterTestAccounts"):
            query_filters.extend(_filters(team.test_account_filters, team))

    source = _node_source(node)
    if source is None:
        return None
    table, node_conditions = source
    aggregate = _aggregate(node)
    if aggregate is None:
        return None

    conditions = [*node_conditions, *_filters(node.get("properties"), team), *query_filters]
    select = ast.SelectQuery(
        select=[aggregate],
        select_from=ast.JoinExpr(table=ast.Field(chain=[table])),
        where=ast.And(exprs=conditions) if conditions else None,
    )
    return select.to_hogql()


def _node_source(node: dict[str, Any]) -> tuple[str, list[ast.Expr]] | None:
    # An ActionsNode returns None: an action compiles to step conditions an analyst never writes by
    # hand, so its fingerprint would match no query anyway.
    kind = node.get("kind")
    if kind == "EventsNode":
        event = node.get("event")
        if event is None:
            return "events", []
        return "events", [
            ast.CompareOperation(
                op=ast.CompareOperationOp.Eq, left=ast.Field(chain=["event"]), right=ast.Constant(value=event)
            )
        ]
    if kind == "DataWarehouseNode" and node.get("table_name"):
        return str(node["table_name"]), []
    return None


def _aggregate(node: dict[str, Any]) -> ast.Expr | None:
    math = node.get("math") or "total"
    is_warehouse = node.get("kind") == "DataWarehouseNode"
    if math == "total":
        return ast.Call(name="count", args=[])
    if math == "dau":
        actor = node.get("distinct_id_field") if is_warehouse else "person_id"
        return ast.Call(name="uniq", args=[ast.Field(chain=[actor])]) if actor else None
    if math == "unique_session" and not is_warehouse:
        return ast.Call(name="uniq", args=[ast.Field(chain=["$session_id"])])
    if math == "hogql" and node.get("math_hogql"):
        return parse_expr(node["math_hogql"])

    math_property = node.get("math_property")
    if not math_property:
        return None
    column = ast.Field(chain=[math_property] if is_warehouse else ["properties", math_property])
    if math in _PROPERTY_MATH:
        return ast.Call(name=math, args=[column])
    if math in _QUANTILE_MATH:
        return ast.Call(name="quantile", params=[ast.Constant(value=_QUANTILE_MATH[math])], args=[column])
    return None


def _filters(properties: Any, team: Team) -> list[ast.Expr]:
    if not properties:
        return []
    return [property_to_expr(properties, team)]
