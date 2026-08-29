"""Candidate discovery: distill a team's query usage into proposed catalog metrics and relationships.

Three usage signals feed the flow:

- Recurring SQL from ``query_log`` (the archived ClickHouse query log): a query that keeps being
  run is a metric candidate.
- Saved insights and their dashboard placements: an insight that sits on dashboards (for example a
  "Churn rate MoM" chart on a "Churn analysis" dashboard) is a metric candidate, linked back to
  the insight via ``source_insight_short_id`` so drift tracking applies.
- Join edges parsed out of the recurring SQL: a table pair joined repeatedly on the same keys is a
  relationship candidate.

Each SQL query is distilled into a structural shape (tables, aggregate functions, group keys, time
grain, join edges) plus a literal-normalized fingerprint, so runs of the same query with different
constants (date ranges, ids) group together. Groups are ranked by run and user counts, and the top
groups become candidates.

Candidates land through the existing write paths (``upsert_metric`` / ``propose_relationship``) as
``proposed`` rows with ``created_source=ai_generated``, ``confidence``, and ``reasoning``, so the
normal review lifecycle applies. Names and descriptions are deterministic heuristics by default;
pass ``summarize_sql_group`` to let an LLM produce better ones for grouped SQL before proposing.
"""

import re
import math
import hashlib
from collections import Counter, defaultdict
from collections.abc import Callable, Iterable
from typing import TYPE_CHECKING, Optional

from rest_framework.exceptions import ValidationError

from posthog.hogql import ast
from posthog.hogql.parser import parse_select
from posthog.hogql.query import execute_hogql_query
from posthog.hogql.visitor import CloningVisitor, TraversingVisitor

from posthog.clickhouse.query_tagging import Feature, Product, tag_queries
from posthog.dataclasses import frozen
from posthog.models import Team, User

from products.data_tools.backend.facade.models import DataWarehouseJoin
from products.product_analytics.backend.facade.models import Insight

from ..facade.enums import CreatedSource
from ..models import METRIC_NAME_MAX_LENGTH, Metric, RelationshipProposal
from .drift import effective_insight_query
from .exceptions import CatalogConflict
from .metrics import upsert_metric
from .relationships import propose_relationship

if TYPE_CHECKING:
    from rest_framework.request import Request

_AGGREGATE_FUNCTIONS = frozenset(
    {
        "count",
        "countif",
        "countdistinct",
        "countdistinctif",
        "uniq",
        "uniqif",
        "uniqexact",
        "uniqexactif",
        "sum",
        "sumif",
        "avg",
        "avgif",
        "min",
        "max",
        "median",
        "quantile",
        "quantiles",
    }
)

# Coarsest first, so a query mixing grains is named by its widest bucket.
_TIME_GRAINS = ("year", "quarter", "month", "week", "day", "hour")
_TIME_GRAIN_FUNCTIONS = {f"tostartof{grain}": grain for grain in _TIME_GRAINS}
_TIME_GRAIN_ADJECTIVES = {
    "year": "yearly",
    "quarter": "quarterly",
    "month": "monthly",
    "week": "weekly",
    "day": "daily",
    "hour": "hourly",
}

# Tables that describe PostHog itself rather than the team's product data. Queries reading only
# these are meta-queries (catalog browsing, query-log analysis) and never metric material.
_META_TABLE_PREFIXES = ("system.", "information_schema.", "numbers")
_META_TABLES = frozenset({"query_log", "raw_query_log", "numbers", "system"})

# Definition kinds the catalog's validator accepts from an insight snapshot (InsightVizNode unwraps
# to its source). Other insight kinds would be rejected at write time, so they are not proposed.
_SUPPORTED_INSIGHT_SOURCE_KINDS = frozenset(
    {"TrendsQuery", "FunnelsQuery", "HogQLQuery", "EventsNode", "ActionsNode", "DataWarehouseNode"}
)

_IDENTIFIER_RE = re.compile(r"^[A-Za-z][A-Za-z0-9_]*$")

DEFAULT_WINDOW_DAYS = 30
DEFAULT_MIN_SQL_RUNS = 5
DEFAULT_MIN_JOIN_OCCURRENCES = 3
DEFAULT_MAX_SQL_SIGNALS = 500
DEFAULT_MAX_METRIC_CANDIDATES = 20
DEFAULT_MAX_RELATIONSHIP_CANDIDATES = 10

# A definition has to stay reviewable; a query longer than this is a report, not a metric.
MAX_DEFINITION_SQL_CHARS = 20_000


@frozen
class JoinEdge:
    """An undirected equality join between two tables, canonicalized so a->b and b->a compare equal."""

    source_table: str
    source_key: str
    joining_table: str
    joining_key: str


@frozen
class SqlShape:
    """The structure of one SQL query, with literals normalized out of the fingerprint."""

    fingerprint: str
    tables: tuple[str, ...]
    aggregations: tuple[str, ...]
    group_keys: tuple[str, ...]
    time_grain: Optional[str]
    join_edges: tuple[JoinEdge, ...]


@frozen
class SqlUsageSignal:
    """One distinct query text from the query log, with its usage counts."""

    sql: str
    run_count: int
    user_count: int


@frozen
class QueryGroup:
    """Usage signals that share a structural fingerprint, i.e. the same query modulo literals."""

    shape: SqlShape
    run_count: int
    user_count: int
    representative_sql: str
    variant_count: int


@frozen
class InsightSignal:
    """One saved insight, with the dashboard placements and run counts that signal it matters."""

    short_id: str
    title: str
    description: str
    dashboard_names: tuple[str, ...]
    source_kind: Optional[str]
    run_count: int


@frozen
class SqlGroupSummary:
    """LLM-authored naming for a query group, overriding the heuristic name and description."""

    name: str
    display_name: str = ""
    description: str = ""
    unit: str = ""


@frozen
class MetricCandidate:
    name: str
    display_name: str
    description: str
    definition: Optional[dict]
    source_insight_short_id: Optional[str]
    unit: str
    confidence: float
    reasoning: str
    evidence: dict


@frozen
class RelationshipCandidate:
    source_table_name: str
    source_table_key: str
    joining_table_name: str
    joining_table_key: str
    field_name: str
    confidence: float
    reasoning: str
    evidence: dict


@frozen
class DiscoveryReport:
    metric_candidates: tuple[MetricCandidate, ...]
    relationship_candidates: tuple[RelationshipCandidate, ...]
    sql_groups: tuple[QueryGroup, ...]
    stats: dict


@frozen
class CandidateSkip:
    name: str
    reason: str


@frozen
class DiscoveryWriteSummary:
    created_metrics: tuple[str, ...]
    skipped_metrics: tuple[CandidateSkip, ...]
    created_relationships: tuple[str, ...]
    skipped_relationships: tuple[CandidateSkip, ...]


def _canonical_edge(table_a: str, key_a: str, table_b: str, key_b: str) -> Optional[JoinEdge]:
    if table_a == table_b:
        return None
    if (table_b, key_b) < (table_a, key_a):
        table_a, key_a, table_b, key_b = table_b, key_b, table_a, key_a
    return JoinEdge(source_table=table_a, source_key=key_a, joining_table=table_b, joining_key=key_b)


class _LiteralNormalizer(CloningVisitor):
    """Clones the AST with every constant blanked, so literal-only variants print identically.

    Placeholders (``{variables.x}``, ``{filters.dateRange.from}``) become string constants naming
    the placeholder: the printer refuses to print an unresolved placeholder, and the name has to
    survive so queries parameterized over different variables keep distinct fingerprints.
    """

    def visit_constant(self, node: ast.Constant) -> ast.Constant:
        return ast.Constant(value=None)

    def visit_placeholder(self, node: ast.Placeholder) -> ast.Constant:
        return ast.Constant(value=f"{{{node.field}}}")


class _ShapeCollector(TraversingVisitor):
    def __init__(self) -> None:
        self.table_names: set[str] = set()
        self.cte_names: set[str] = set()
        self.aggregations: set[str] = set()
        self.time_grains: set[str] = set()
        self.group_keys: list[str] = []
        self.join_edges: list[JoinEdge] = []

    def visit_cte(self, node: ast.CTE) -> None:
        self.cte_names.add(node.name)
        super().visit(node.expr)

    def visit_call(self, node: ast.Call) -> None:
        name = node.name.lower()
        if name in _AGGREGATE_FUNCTIONS:
            self.aggregations.add(name)
        grain = _TIME_GRAIN_FUNCTIONS.get(name)
        if grain is None and name in ("datetrunc", "date_trunc") and node.args:
            first = node.args[0]
            if isinstance(first, ast.Constant) and isinstance(first.value, str):
                grain = first.value.lower() if first.value.lower() in _TIME_GRAINS else None
        if grain is not None:
            self.time_grains.add(grain)
        super().visit_call(node)

    def visit_select_query(self, node: ast.SelectQuery) -> None:
        aliases: dict[str, str] = {}
        join = node.select_from
        while join is not None:
            if isinstance(join.table, ast.Field):
                table_name = ".".join(str(part) for part in join.table.chain)
                self.table_names.add(table_name)
                aliases[join.alias or table_name] = table_name
            join = join.next_join
        join = node.select_from
        while join is not None:
            if join.constraint is not None and join.constraint.constraint_type == "ON":
                self._collect_edges(join.constraint.expr, aliases)
            join = join.next_join
        for expr in node.group_by or []:
            try:
                self.group_keys.append(expr.to_hogql())
            except Exception:
                pass
        super().visit_select_query(node)

    def _collect_edges(self, expr: ast.Expr, aliases: dict[str, str]) -> None:
        if isinstance(expr, ast.And):
            for sub_expr in expr.exprs:
                self._collect_edges(sub_expr, aliases)
            return
        if not isinstance(expr, ast.CompareOperation) or expr.op != ast.CompareOperationOp.Eq:
            return
        left = self._qualified_field(expr.left, aliases)
        right = self._qualified_field(expr.right, aliases)
        if left is None or right is None:
            return
        edge = _canonical_edge(*left, *right)
        if edge is not None:
            self.join_edges.append(edge)

    @staticmethod
    def _qualified_field(expr: ast.Expr, aliases: dict[str, str]) -> Optional[tuple[str, str]]:
        if not isinstance(expr, ast.Field) or len(expr.chain) < 2:
            return None
        table = aliases.get(str(expr.chain[0]))
        if table is None:
            return None
        return table, ".".join(str(part) for part in expr.chain[1:])


def distill_sql(sql: str) -> Optional[SqlShape]:
    """Parse a query into its structural shape, or None when it does not parse as a select.

    The fingerprint hashes the query with every literal blanked, so the same query run with
    different date ranges or ids lands in one group.
    """
    try:
        select = parse_select(sql)
        collector = _ShapeCollector()
        collector.visit(select)
        normalized = _LiteralNormalizer(clear_types=True, clear_locations=True).visit(select)
        fingerprint = hashlib.sha256(normalized.to_hogql().encode()).hexdigest()
    except Exception:
        # Query-log text can be any dialect fragment; whatever HogQL cannot parse carries no shape.
        return None

    grain = next((g for g in _TIME_GRAINS if g in collector.time_grains), None)
    # A join onto a CTE is internal query structure, not a relationship between real tables.
    edges = [
        edge
        for edge in dict.fromkeys(collector.join_edges)
        if edge.source_table not in collector.cte_names and edge.joining_table not in collector.cte_names
    ]
    return SqlShape(
        fingerprint=fingerprint,
        tables=tuple(sorted(collector.table_names - collector.cte_names)),
        aggregations=tuple(sorted(collector.aggregations)),
        group_keys=tuple(dict.fromkeys(collector.group_keys)),
        time_grain=grain,
        join_edges=tuple(edges),
    )


def _is_meta_table(table: str) -> bool:
    return table in _META_TABLES or table.startswith(_META_TABLE_PREFIXES)


def group_sql_signals(signals: Iterable[SqlUsageSignal]) -> list[QueryGroup]:
    """Group usage signals by structural fingerprint, dropping unparseable and meta-only queries."""
    by_fingerprint: dict[str, list[tuple[SqlShape, SqlUsageSignal]]] = defaultdict(list)
    for signal in signals:
        shape = distill_sql(signal.sql)
        if shape is None or not shape.tables or all(_is_meta_table(t) for t in shape.tables):
            continue
        by_fingerprint[shape.fingerprint].append((shape, signal))

    groups = []
    for members in by_fingerprint.values():
        members.sort(key=lambda pair: pair[1].run_count, reverse=True)
        shape, top_signal = members[0]
        groups.append(
            QueryGroup(
                shape=shape,
                run_count=sum(signal.run_count for _, signal in members),
                # Distinct users per variant may overlap across variants, so this is an upper bound.
                user_count=sum(signal.user_count for _, signal in members),
                representative_sql=top_signal.sql,
                variant_count=len(members),
            )
        )
    groups.sort(key=lambda group: group.run_count, reverse=True)
    return groups


def _identifier(text: str, fallback: str = "metric") -> str:
    slug = re.sub(r"[^a-z0-9]+", "_", text.lower()).strip("_") or fallback
    if not slug[0].isalpha():
        slug = f"m_{slug}"
    return slug[:METRIC_NAME_MAX_LENGTH]


def _confidence(weight: int, *, base: float, per_doubling: float = 0.06, cap: float = 0.9) -> float:
    return round(min(cap, base + per_doubling * math.log2(max(weight, 1) + 1)), 2)


def _unique_name(name: str, taken: set[str]) -> str:
    candidate = name
    suffix = 2
    while candidate in taken:
        candidate = f"{name[: METRIC_NAME_MAX_LENGTH - len(str(suffix)) - 1]}_{suffix}"
        suffix += 1
    taken.add(candidate)
    return candidate


def _insight_metric_candidates(
    insight_signals: Iterable[InsightSignal],
    *,
    days: int,
    existing_names: frozenset[str],
    taken_names: set[str],
) -> list[MetricCandidate]:
    candidates = []
    ranked = sorted(insight_signals, key=lambda s: (len(s.dashboard_names), s.run_count), reverse=True)
    for signal in ranked:
        if not signal.dashboard_names and signal.run_count <= 0:
            continue
        if signal.source_kind not in _SUPPORTED_INSIGHT_SOURCE_KINDS:
            continue
        base_name = _identifier(signal.title)
        if base_name in existing_names:
            # A live metric already holds this name, so the concept is likely cataloged already.
            continue
        name = _unique_name(base_name, taken_names)
        dashboards_phrase = (
            " on the dashboard(s) " + ", ".join(f'"{d}"' for d in signal.dashboard_names[:3])
            if signal.dashboard_names
            else ""
        )
        description = (
            signal.description.strip() or f'Proposed from the saved insight "{signal.title}"{dashboards_phrase}.'
        )
        weight = signal.run_count + 10 * len(signal.dashboard_names)
        candidates.append(
            MetricCandidate(
                name=name,
                display_name=signal.title,
                description=description[:900],
                definition=None,
                source_insight_short_id=signal.short_id,
                unit="",
                confidence=_confidence(weight, base=0.5),
                reasoning=(
                    f'The saved insight "{signal.title}" appears on {len(signal.dashboard_names)} dashboard(s)'
                    f"{dashboards_phrase} and ran {signal.run_count} times in the last {days} days, "
                    "so the team likely already treats it as a metric."
                ),
                evidence={
                    "signal": "insight",
                    "insight_short_id": signal.short_id,
                    "dashboards": list(signal.dashboard_names),
                    "run_count": signal.run_count,
                    "window_days": days,
                },
            )
        )
    return candidates


def _heuristic_group_name(group: QueryGroup) -> str:
    shape = group.shape
    parts = []
    if shape.time_grain:
        parts.append(_TIME_GRAIN_ADJECTIVES[shape.time_grain])
    parts.append(shape.aggregations[0] if shape.aggregations else "query")
    primary_table = next((t for t in shape.tables if not _is_meta_table(t)), shape.tables[0])
    parts.append(primary_table.split(".")[-1])
    simple_keys = [key for key in shape.group_keys if _IDENTIFIER_RE.match(key)]
    if simple_keys:
        parts.append(f"by_{simple_keys[0]}")
    return _identifier("_".join(parts))


def _sql_metric_candidates(
    groups: Iterable[QueryGroup],
    *,
    days: int,
    min_sql_runs: int,
    existing_names: frozenset[str],
    taken_names: set[str],
    summarize_sql_group: Optional[Callable[[QueryGroup], Optional[SqlGroupSummary]]] = None,
) -> list[MetricCandidate]:
    candidates = []
    for group in groups:
        if group.run_count < min_sql_runs or not group.shape.aggregations:
            continue
        if len(group.representative_sql) > MAX_DEFINITION_SQL_CHARS:
            continue
        summary = None
        if summarize_sql_group is not None:
            try:
                summary = summarize_sql_group(group)
            except Exception:
                summary = None

        aggregations = ", ".join(group.shape.aggregations)
        tables = ", ".join(group.shape.tables)
        if summary is not None and _IDENTIFIER_RE.match(summary.name):
            base_name = summary.name[:METRIC_NAME_MAX_LENGTH]
        else:
            summary = None
            base_name = _heuristic_group_name(group)
        if base_name in existing_names:
            continue
        if summary is not None:
            name = _unique_name(base_name, taken_names)
            display_name = summary.display_name
            description = summary.description
            unit = summary.unit
        else:
            name = _unique_name(base_name, taken_names)
            display_name = name.replace("_", " ").capitalize()
            description = (
                f"Recurring SQL query computing {aggregations} over {tables}. "
                "Proposed automatically from query history. Review the name, description, and definition."
            )
            unit = ""
        candidates.append(
            MetricCandidate(
                name=name,
                display_name=display_name,
                description=description[:900],
                definition={"kind": "HogQLQuery", "query": group.representative_sql},
                source_insight_short_id=None,
                unit=unit,
                confidence=_confidence(group.run_count, base=0.35),
                reasoning=(
                    f"This query shape ran {group.run_count} times ({group.variant_count} literal variant(s), "
                    f"about {group.user_count} distinct users) in the last {days} days, so it likely computes "
                    "a number the team keeps coming back to."
                ),
                evidence={
                    "signal": "query_history",
                    "run_count": group.run_count,
                    "user_count": group.user_count,
                    "variant_count": group.variant_count,
                    "fingerprint": group.shape.fingerprint,
                    "window_days": days,
                },
            )
        )
    return candidates


def _pair_key(table_a: str, key_a: str, table_b: str, key_b: str) -> frozenset:
    return frozenset({(table_a, key_a.strip()), (table_b, key_b.strip())})


def _relationship_candidates(
    groups: Iterable[QueryGroup],
    *,
    days: int,
    min_join_occurrences: int,
    existing_join_pairs: frozenset,
) -> list[RelationshipCandidate]:
    occurrences: Counter[JoinEdge] = Counter()
    total_runs: Counter[JoinEdge] = Counter()
    for group in groups:
        for edge in group.shape.join_edges:
            occurrences[edge] += 1
            total_runs[edge] += group.run_count

    candidates = []
    for edge, occurrence_count in occurrences.most_common():
        if occurrence_count < min_join_occurrences:
            continue
        if _is_meta_table(edge.source_table) or _is_meta_table(edge.joining_table):
            continue
        if _pair_key(edge.source_table, edge.source_key, edge.joining_table, edge.joining_key) in existing_join_pairs:
            continue
        # Prefer hanging the accessor off the events table when it is one side of the join, since
        # that is where insight queries start from.
        source_table, source_key = edge.source_table, edge.source_key
        joining_table, joining_key = edge.joining_table, edge.joining_key
        if joining_table == "events":
            source_table, source_key, joining_table, joining_key = joining_table, joining_key, source_table, source_key
        sample = f"{source_table}.{source_key} = {joining_table}.{joining_key}"
        candidates.append(
            RelationshipCandidate(
                source_table_name=source_table,
                source_table_key=source_key,
                joining_table_name=joining_table,
                joining_table_key=joining_key,
                field_name=_identifier(joining_table.split(".")[-1], fallback="joined"),
                confidence=_confidence(occurrence_count, base=0.4),
                reasoning=(
                    f"{occurrence_count} distinct recurring query shapes ({total_runs[edge]} total runs in the "
                    f"last {days} days) join these tables on {sample}, so the relationship is already in active use."
                ),
                evidence={
                    "signal": "query_history",
                    "distinct_query_shapes": occurrence_count,
                    "total_runs": total_runs[edge],
                    "sample_join": sample,
                    "window_days": days,
                },
            )
        )
    return candidates


def build_report(
    *,
    sql_signals: Iterable[SqlUsageSignal],
    insight_signals: Iterable[InsightSignal],
    days: int,
    existing_metric_names: frozenset[str] = frozenset(),
    existing_join_pairs: frozenset = frozenset(),
    min_sql_runs: int = DEFAULT_MIN_SQL_RUNS,
    min_join_occurrences: int = DEFAULT_MIN_JOIN_OCCURRENCES,
    max_metric_candidates: int = DEFAULT_MAX_METRIC_CANDIDATES,
    max_relationship_candidates: int = DEFAULT_MAX_RELATIONSHIP_CANDIDATES,
    summarize_sql_group: Optional[Callable[[QueryGroup], Optional[SqlGroupSummary]]] = None,
) -> DiscoveryReport:
    """Pure candidate construction from already-collected signals; no database access."""
    sql_signals = list(sql_signals)
    insight_signals = list(insight_signals)
    groups = group_sql_signals(sql_signals)

    taken_names = set(existing_metric_names)
    metric_candidates = _insight_metric_candidates(
        insight_signals, days=days, existing_names=existing_metric_names, taken_names=taken_names
    )
    metric_candidates += _sql_metric_candidates(
        groups,
        days=days,
        min_sql_runs=min_sql_runs,
        existing_names=existing_metric_names,
        taken_names=taken_names,
        summarize_sql_group=summarize_sql_group,
    )
    metric_candidates.sort(key=lambda c: c.confidence, reverse=True)

    relationship_candidates = _relationship_candidates(
        groups,
        days=days,
        min_join_occurrences=min_join_occurrences,
        existing_join_pairs=existing_join_pairs,
    )

    return DiscoveryReport(
        metric_candidates=tuple(metric_candidates[:max_metric_candidates]),
        relationship_candidates=tuple(relationship_candidates[:max_relationship_candidates]),
        sql_groups=tuple(groups),
        stats={
            "sql_signals_scanned": len(sql_signals),
            "query_groups": len(groups),
            "insights_scanned": len(insight_signals),
            "window_days": days,
        },
    )


def collect_sql_usage(
    team: Team, *, days: int, min_runs: int = 2, limit: int = DEFAULT_MAX_SQL_SIGNALS
) -> list[SqlUsageSignal]:
    """Distinct successfully-run SQL texts from the team's query log, heaviest first."""
    query = parse_select(
        """
        SELECT query AS sql, count() AS run_count, count(DISTINCT created_by) AS user_count
        FROM query_log
        WHERE query_start_time >= now() - toIntervalDay({days})
          AND status = 'QueryFinish'
          AND notEmpty(query)
        GROUP BY sql
        HAVING run_count >= {min_runs}
        ORDER BY run_count DESC
        LIMIT {limit}
        """,
        placeholders={
            "days": ast.Constant(value=days),
            "min_runs": ast.Constant(value=min_runs),
            "limit": ast.Constant(value=limit),
        },
    )
    tag_queries(product=Product.DATA_CATALOG, feature=Feature.QUERY)
    response = execute_hogql_query(query=query, team=team)
    return [SqlUsageSignal(sql=row[0], run_count=int(row[1]), user_count=int(row[2])) for row in response.results or []]


def collect_endpoint_usage(team: Team, *, days: int, limit: int = 5000) -> dict[str, int]:
    """Run counts per originating endpoint/insight identifier (``query_log.endpoint``)."""
    query = parse_select(
        """
        SELECT endpoint, count() AS run_count
        FROM query_log
        WHERE query_start_time >= now() - toIntervalDay({days})
          AND status = 'QueryFinish'
          AND notEmpty(endpoint)
        GROUP BY endpoint
        ORDER BY run_count DESC
        LIMIT {limit}
        """,
        placeholders={"days": ast.Constant(value=days), "limit": ast.Constant(value=limit)},
    )
    tag_queries(product=Product.DATA_CATALOG, feature=Feature.QUERY)
    response = execute_hogql_query(query=query, team=team)
    return {row[0]: int(row[1]) for row in response.results or []}


def _insight_source_kind(query: dict) -> Optional[str]:
    kind = query.get("kind")
    if kind in ("InsightVizNode", "DataTableNode"):
        source = query.get("source")
        return source.get("kind") if isinstance(source, dict) else None
    return kind


def collect_insight_signals(team: Team, *, endpoint_usage: Optional[dict[str, int]] = None) -> list[InsightSignal]:
    """Saved insights with a resolvable query, plus their dashboard placements and run counts."""
    usage: dict[str, int] = defaultdict(int)
    for endpoint, count in (endpoint_usage or {}).items():
        # The endpoint identifier ends with the insight short id in every format observed
        # (bare short id or a path-like identifier).
        usage[endpoint.rsplit("/", 1)[-1]] += count

    signals = []
    for insight in Insight.objects.filter(team_id=team.id, deleted=False).prefetch_related("dashboards"):
        title = (insight.name or insight.derived_name or "").strip()
        if not title:
            continue
        try:
            query = effective_insight_query(insight)
        except Exception:
            query = None
        if not isinstance(query, dict):
            continue
        dashboard_names = tuple(sorted({d.name for d in insight.dashboards.all() if not d.deleted and d.name}))
        signals.append(
            InsightSignal(
                short_id=insight.short_id,
                title=title,
                description=(insight.description or "").strip(),
                dashboard_names=dashboard_names,
                source_kind=_insight_source_kind(query),
                run_count=usage.get(insight.short_id, 0),
            )
        )
    return signals


def _existing_join_pairs(team: Team) -> frozenset:
    pairs = set()
    for join in DataWarehouseJoin.objects.filter(team_id=team.id).exclude(deleted=True):
        pairs.add(
            _pair_key(join.source_table_name, join.source_table_key, join.joining_table_name, join.joining_table_key)
        )
    for proposal in RelationshipProposal.objects.for_team(team.id):
        pairs.add(
            _pair_key(
                proposal.source_table_name,
                proposal.source_table_key,
                proposal.joining_table_name,
                proposal.joining_table_key,
            )
        )
    return frozenset(pairs)


def discover_candidates(
    team: Team,
    *,
    days: int = DEFAULT_WINDOW_DAYS,
    min_sql_runs: int = DEFAULT_MIN_SQL_RUNS,
    min_join_occurrences: int = DEFAULT_MIN_JOIN_OCCURRENCES,
    max_sql_signals: int = DEFAULT_MAX_SQL_SIGNALS,
    max_metric_candidates: int = DEFAULT_MAX_METRIC_CANDIDATES,
    max_relationship_candidates: int = DEFAULT_MAX_RELATIONSHIP_CANDIDATES,
    summarize_sql_group: Optional[Callable[[QueryGroup], Optional[SqlGroupSummary]]] = None,
) -> DiscoveryReport:
    """Collect the team's usage signals and build a candidate report. Read-only."""
    sql_signals = collect_sql_usage(team, days=days, limit=max_sql_signals)
    endpoint_usage = collect_endpoint_usage(team, days=days)
    insight_signals = collect_insight_signals(team, endpoint_usage=endpoint_usage)
    existing_names = frozenset(Metric.objects.for_team(team.id).filter(deleted=False).values_list("name", flat=True))
    return build_report(
        sql_signals=sql_signals,
        insight_signals=insight_signals,
        days=days,
        existing_metric_names=existing_names,
        existing_join_pairs=_existing_join_pairs(team),
        min_sql_runs=min_sql_runs,
        min_join_occurrences=min_join_occurrences,
        max_metric_candidates=max_metric_candidates,
        max_relationship_candidates=max_relationship_candidates,
        summarize_sql_group=summarize_sql_group,
    )


def apply_candidates(
    report: DiscoveryReport,
    *,
    team: Team,
    user: Optional[User] = None,
    ai_model: str = "",
    request: "Request | None" = None,
) -> DiscoveryWriteSummary:
    """Persist a report's candidates as proposed catalog rows through the standard write paths.

    A candidate whose name is already a live metric is skipped rather than refined, so discovery
    never rewrites something a person curated. Every write lands as ``proposed`` and goes through
    the normal review lifecycle.
    """
    created_metrics: list[str] = []
    skipped_metrics: list[CandidateSkip] = []
    existing_names = set(Metric.objects.for_team(team.id).filter(deleted=False).values_list("name", flat=True))
    for candidate in report.metric_candidates:
        if candidate.name in existing_names:
            skipped_metrics.append(CandidateSkip(name=candidate.name, reason="A metric with this name already exists."))
            continue
        definition_kwargs: dict = (
            {"source_insight_short_id": candidate.source_insight_short_id}
            if candidate.source_insight_short_id
            else {"definition": candidate.definition}
        )
        try:
            upsert_metric(
                team=team,
                user=user,
                name=candidate.name,
                description=candidate.description,
                display_name=candidate.display_name,
                unit=candidate.unit,
                created_source=CreatedSource.AI_GENERATED,
                ai_model=ai_model,
                confidence=candidate.confidence,
                reasoning=candidate.reasoning,
                request=request,
                **definition_kwargs,
            )
        except ValidationError as error:
            skipped_metrics.append(CandidateSkip(name=candidate.name, reason=str(error.detail)))
        else:
            created_metrics.append(candidate.name)
            existing_names.add(candidate.name)

    created_relationships: list[str] = []
    skipped_relationships: list[CandidateSkip] = []
    for relationship in report.relationship_candidates:
        label = f"{relationship.source_table_name} -> {relationship.joining_table_name}"
        try:
            propose_relationship(
                team=team,
                user=user,
                source_table_name=relationship.source_table_name,
                source_table_key=relationship.source_table_key,
                joining_table_name=relationship.joining_table_name,
                joining_table_key=relationship.joining_table_key,
                field_name=relationship.field_name,
                confidence=relationship.confidence,
                reasoning=relationship.reasoning,
                evidence=relationship.evidence,
                request=request,
            )
        except (CatalogConflict, ValidationError) as error:
            detail = getattr(error, "detail", error)
            skipped_relationships.append(CandidateSkip(name=label, reason=str(detail)))
        else:
            created_relationships.append(label)

    return DiscoveryWriteSummary(
        created_metrics=tuple(created_metrics),
        skipped_metrics=tuple(skipped_metrics),
        created_relationships=tuple(created_relationships),
        skipped_relationships=tuple(skipped_relationships),
    )
