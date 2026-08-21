"""Per-predicate index eligibility for a query, decided before it runs.

``property_planner`` already resolves where a property physically lives (materialized column,
dynamic materialized column, property group, or the raw JSON blob) and which skip indexes sit on
that source. This module turns those facts into a per-predicate answer to "will this filter prune
data, and if not, why not" by pairing the source plan with the comparison operator: a minmax index
prunes range comparisons, a bloom filter prunes equality and IN, and neither prunes anything under
a negation.

The analysis runs on the AST as it looks straight after ``resolve_types``, which is the only point
where property reads are still recognizable as ``PropertyType``. Later stages lower them into bare
physical-column expressions.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from posthog.hogql import ast
from posthog.hogql.base import AST
from posthog.hogql.context import HogQLContext
from posthog.hogql.property_planner import (
    PropertyComparisonPlan,
    PropertyMinmaxBlocker,
    PropertyScope,
    PropertySourceKind,
    plan_property_comparison,
)
from posthog.hogql.type_system import ComparisonCompatibility, comparison_compatibility
from posthog.hogql.visitor import TraversingVisitor, clone_expr

from posthog.dataclasses import frozen
from posthog.schema_enums import QueryIndexUsage


class IndexKind(StrEnum):
    MINMAX = "minmax"
    BLOOM_FILTER = "bloom_filter"
    NGRAM_LOWER = "ngram_lower"
    BLOOM_FILTER_LOWER = "bloom_filter_lower"


class PredicateIndexVerdict(StrEnum):
    INDEXED = "indexed"
    """A skip index on the source column covers this predicate's operator.

    Whether it drops granules is a separate question this analysis does not answer: that depends on
    the table's sort order and on how selective the compared value is. Read as "an index applies",
    never as "this filter is fast".
    """

    BLOCKED = "blocked"
    """The source carries an index this operator could use, but a type mismatch defeats it."""

    UNINDEXED_COLUMN = "unindexed_column"
    """The property reads from a dedicated column, but no index prunes this operator."""

    UNINDEXED_JSON = "unindexed_json"
    """The property is parsed out of the JSON blob on every row."""

    OPERATOR_NOT_INDEXABLE = "operator_not_indexable"
    """Negations, regexes and case-sensitive LIKE match granules that skip indexes cannot exclude."""


# Which skip indexes ClickHouse can use to drop granules for a given operator. Negated operators are
# absent on purpose: a granule holding one non-matching row still satisfies `!=`, so no skip index
# can exclude it. `like` is absent because only a prefix pattern prunes, and whether a pattern is a
# prefix is decided at runtime from the literal rather than from the operator.
_OPERATOR_INDEXES: dict[ast.CompareOperationOp, frozenset[IndexKind]] = {
    ast.CompareOperationOp.Eq: frozenset({IndexKind.MINMAX, IndexKind.BLOOM_FILTER}),
    ast.CompareOperationOp.In: frozenset({IndexKind.MINMAX, IndexKind.BLOOM_FILTER}),
    ast.CompareOperationOp.GlobalIn: frozenset({IndexKind.MINMAX, IndexKind.BLOOM_FILTER}),
    ast.CompareOperationOp.Gt: frozenset({IndexKind.MINMAX}),
    ast.CompareOperationOp.GtEq: frozenset({IndexKind.MINMAX}),
    ast.CompareOperationOp.Lt: frozenset({IndexKind.MINMAX}),
    ast.CompareOperationOp.LtEq: frozenset({IndexKind.MINMAX}),
    ast.CompareOperationOp.ILike: frozenset({IndexKind.NGRAM_LOWER, IndexKind.BLOOM_FILTER_LOWER}),
}

_COMPATIBLE_COMPARISONS = frozenset({ComparisonCompatibility.DEFINITELY_COMPATIBLE, ComparisonCompatibility.CHEAP_CAST})

_COLUMN_SOURCE_KINDS = frozenset(
    {
        PropertySourceKind.MATERIALIZED_COLUMN,
        PropertySourceKind.DYNAMIC_MATERIALIZED_COLUMN,
        PropertySourceKind.PROPERTY_GROUP,
    }
)

_SCOPE_LABELS: dict[PropertyScope, str] = {
    PropertyScope.EVENT: "Event property",
    PropertyScope.PERSON: "Person property",
    PropertyScope.GROUP: "Group property",
    PropertyScope.UNKNOWN: "Property",
}

_INDEX_LABELS: dict[IndexKind, str] = {
    IndexKind.MINMAX: "min-max",
    IndexKind.BLOOM_FILTER: "bloom filter",
    IndexKind.NGRAM_LOWER: "n-gram",
    IndexKind.BLOOM_FILTER_LOWER: "bloom filter",
}

_SOURCE_LABELS: dict[PropertySourceKind, str] = {
    PropertySourceKind.JSON: "JSON blob",
    PropertySourceKind.MATERIALIZED_COLUMN: "materialized column",
    PropertySourceKind.DYNAMIC_MATERIALIZED_COLUMN: "materialized column",
    PropertySourceKind.PROPERTY_GROUP: "property group",
}


_PLAIN_TYPE_WORDS: dict[str, str] = {
    "String": "text",
    "Float": "a number",
    "Integer": "a number",
    "DateTime": "a date",
    "Date": "a date",
    "Boolean": "true or false",
}


def _plain_type(printed_type: str) -> str:
    """A reader-facing word for a HogQL type.

    The type names the engine prints are not the ones the property-type picker offers: it has
    `Numeric` and `Duration` where the engine has `Float`, and no `Float` at all. Naming the engine's
    type would send a reader looking for a setting that is not there, so the copy describes the kind
    of value instead and leaves the exact type to the structured fields.
    """
    return _PLAIN_TYPE_WORDS.get(printed_type, printed_type)


@dataclass(frozen=True, slots=True, kw_only=True)
class PredicateIndexEligibility:
    property_name: str
    scope: PropertyScope
    operator: ast.CompareOperationOp
    source_kind: PropertySourceKind
    source_label: str
    column_name: str | None
    semantic_type: str
    physical_type: str
    available_indexes: tuple[IndexKind, ...]
    usable_indexes: tuple[IndexKind, ...]
    verdict: PredicateIndexVerdict
    blocker: PropertyMinmaxBlocker | None
    message: str
    fix: str | None
    """Prose advice for a reader. Not a replacement string: `HogQLNotice.fix` means literal text to
    substitute into the marked range, so this must never be handed to an editor marker directly."""
    ai_fix_prompt: str | None
    """Instruction for the editor's "Fix with AI" action, set only where rewriting the query helps."""
    start: int | None
    end: int | None

    @property
    def prunes_data(self) -> bool:
        return self.verdict == PredicateIndexVerdict.INDEXED

    @property
    def editor_actionable(self) -> bool:
        """Whether a marker on this predicate would point at text the reader can change.

        A marker is a claim about the range it underlines. How a property is stored is a fact about
        the property definition, not about the query, so underlining a correct comparison leaves the
        reader nothing to edit and teaches them to ignore the markers that do carry an edit.
        """
        if self.verdict != PredicateIndexVerdict.BLOCKED:
            return False
        return self.blocker != PropertyMinmaxBlocker.SOURCE_TYPE_DIFFERS_FROM_PROPERTY_TYPE


@dataclass(frozen=True, slots=True)
class IndexEligibilityReport:
    predicates: tuple[PredicateIndexEligibility, ...] = ()

    @property
    def usage(self) -> QueryIndexUsage:
        if not self.predicates:
            return QueryIndexUsage.UNDECISIVE
        pruning = sum(1 for predicate in self.predicates if predicate.prunes_data)
        if pruning == len(self.predicates):
            return QueryIndexUsage.YES
        if pruning == 0:
            return QueryIndexUsage.NO
        return QueryIndexUsage.PARTIAL


def analyze_index_eligibility(node: AST, context: HogQLContext) -> IndexEligibilityReport:
    """Build the report from an AST that has been through ``resolve_types`` and nothing further."""
    collector = _FilterPredicateCollector(context)
    collector.visit(node)
    return IndexEligibilityReport(predicates=tuple(collector.predicates))


def build_index_eligibility_report(
    node: ast.SelectQuery | ast.SelectSetQuery,
    context: HogQLContext,
) -> IndexEligibilityReport:
    """Resolve a copy of the user's query far enough to plan its property reads, then analyze it.

    Resolution happens on a clone because the analysis has to see the AST at a stage the print
    pipeline has already moved past, and because callers hand us the node they still intend to use.
    The property-definition registry is reused when the caller's context already loaded it, so a
    caller that has printed the query first pays no extra Postgres round trip.

    That second resolution is the cost of running outside the print pipeline. Analyzing in-pipeline
    (between ``build_property_swapper`` and the first ``PropertySwapper`` pass, the one window where
    property types are still intact and the registry is loaded) would make it free, but the AST there
    has already been through simplification and projection pushdown, so the character offsets the
    editor squiggles with are no longer guaranteed to be the ones the user typed.
    """
    # Deferred: these pull in the resolver and the Django-side property-definition loader, neither of
    # which should sit on this module's import path (it is imported by the metadata endpoint).
    from posthog.hogql.resolver import resolve_types  # noqa: PLC0415
    from posthog.hogql.transforms.property_types import build_property_swapper  # noqa: PLC0415

    if context.database is None:
        return IndexEligibilityReport()

    with context.timings.measure("index_eligibility"):
        resolved = resolve_types(clone_expr(node), context, dialect="clickhouse")
        if context.property_metadata is None:
            build_property_swapper(resolved, context)
        return analyze_index_eligibility(resolved, context)


def eligibility_from_plan(
    plan: PropertyComparisonPlan,
    *,
    negated: bool = False,
    start: int | None = None,
    end: int | None = None,
) -> PredicateIndexEligibility:
    source = plan.access.source
    available = _available_indexes(plan)
    relevant = frozenset() if negated else _OPERATOR_INDEXES.get(plan.operator, frozenset())
    # `_minmax_blocker` reports the absent-index case first, so any other value it returns is a type
    # problem that makes the printer wrap the column in a cast. A cast defeats every skip index on
    # that column, not just the minmax one.
    type_blocker = plan.minmax_blocker if plan.minmax_blocker != PropertyMinmaxBlocker.NO_MINMAX_INDEX else None
    if type_blocker is not None and _set_members_match_source(plan):
        type_blocker = None
    usable: tuple[IndexKind, ...] = () if type_blocker is not None else tuple(sorted(available & relevant))

    verdict = _verdict(
        source_kind=source.kind,
        relevant=relevant,
        available=available,
        usable=usable,
        type_blocker=type_blocker,
    )
    semantic_type = plan.access.semantic_type.print_type()
    physical_type = source.physical_type.print_type()
    copy = _copy_for(
        verdict=verdict,
        plan=plan,
        usable=usable,
        type_blocker=type_blocker,
        semantic_type=semantic_type,
        physical_type=physical_type,
    )

    return PredicateIndexEligibility(
        property_name=plan.access.property_name,
        scope=plan.access.scope,
        operator=plan.operator,
        source_kind=source.kind,
        source_label=_SOURCE_LABELS[source.kind],
        column_name=source.column_name,
        semantic_type=semantic_type,
        physical_type=physical_type,
        available_indexes=tuple(sorted(available)),
        usable_indexes=usable,
        verdict=verdict,
        blocker=type_blocker,
        message=copy.message,
        fix=copy.fix,
        ai_fix_prompt=copy.ai_fix_prompt,
        start=start,
        end=end,
    )


def _set_members_match_source(plan: PropertyComparisonPlan) -> bool:
    """Whether an IN compares the column against a set whose members all match how it is stored.

    ``plan.minmax_blocker`` compares the property against the whole right-hand side, so an IN reads
    as String-versus-Tuple and is reported as a type mismatch. The printer disagrees: it emits
    ``has([...], column)`` with the column bare, and the skip index still applies. The mismatch that
    matters for a set membership is between the column and the set's members.
    """
    if plan.operator not in (ast.CompareOperationOp.In, ast.CompareOperationOp.GlobalIn):
        return False

    value_type = plan.value_type
    if isinstance(value_type, ast.TupleType):
        member_types: list[ast.ConstantType] = list(value_type.item_types)
    elif isinstance(value_type, ast.ArrayType):
        member_types = [value_type.item_type]
    else:
        return False

    if not member_types:
        return False

    return all(
        comparison_compatibility(plan.access.source.physical_type, member_type) in _COMPATIBLE_COMPARISONS
        for member_type in member_types
    )


def _available_indexes(plan: PropertyComparisonPlan) -> frozenset[IndexKind]:
    source = plan.access.source
    indexes: set[IndexKind] = set()
    if source.has_minmax_index:
        indexes.add(IndexKind.MINMAX)
    if source.has_bloom_filter_index:
        indexes.add(IndexKind.BLOOM_FILTER)
    if source.has_ngram_lower_index:
        indexes.add(IndexKind.NGRAM_LOWER)
    if source.has_bloom_filter_lower_index:
        indexes.add(IndexKind.BLOOM_FILTER_LOWER)
    return frozenset(indexes)


def _verdict(
    source_kind: PropertySourceKind,
    relevant: frozenset[IndexKind],
    available: frozenset[IndexKind],
    usable: tuple[IndexKind, ...],
    type_blocker: PropertyMinmaxBlocker | None,
) -> PredicateIndexVerdict:
    if not relevant:
        return PredicateIndexVerdict.OPERATOR_NOT_INDEXABLE
    if usable:
        return PredicateIndexVerdict.INDEXED
    if type_blocker is not None and available & relevant:
        return PredicateIndexVerdict.BLOCKED
    if source_kind in _COLUMN_SOURCE_KINDS:
        return PredicateIndexVerdict.UNINDEXED_COLUMN
    return PredicateIndexVerdict.UNINDEXED_JSON


@frozen
class _PredicateCopy:
    """What a reader is told about one predicate: the finding, the advice, the AI rewrite."""

    message: str
    fix: str | None = None
    ai_fix_prompt: str | None = None


def _copy_for(
    verdict: PredicateIndexVerdict,
    plan: PropertyComparisonPlan,
    usable: tuple[IndexKind, ...],
    type_blocker: PropertyMinmaxBlocker | None,
    semantic_type: str,
    physical_type: str,
) -> _PredicateCopy:
    # Messages name the property, never the physical column behind it. A reader cannot select,
    # create or drop `mat_$browser`, so naming it spends words on something they cannot act on.
    # The column name stays on the structured `column_name` field for callers that want it.
    label = _SCOPE_LABELS[plan.access.scope]
    name = plan.access.property_name

    if verdict == PredicateIndexVerdict.INDEXED:
        index_names = ", ".join(sorted({_INDEX_LABELS[index] for index in usable}))
        return _PredicateCopy(
            message=f"{label} '{name}' has a {index_names} index that covers this comparison. How much data it "
            "skips depends on how the values are spread across the table.",
        )

    if verdict == PredicateIndexVerdict.BLOCKED:
        if type_blocker == PropertyMinmaxBlocker.SOURCE_TYPE_DIFFERS_FROM_PROPERTY_TYPE:
            # No fix here changes how the value is stored: both auto-materialized and slot-backed
            # columns are String, so a numeric or datetime property is always converted at read time.
            # Correcting the definition only helps when the definition is the thing that is wrong.
            # No AI prompt: how the value is stored is not something a query rewrite can change.
            return _PredicateCopy(
                message=f"{label} '{name}' is stored as {_plain_type(physical_type)} but compared as "
                f"{_plain_type(semantic_type)}, so every row is converted before the filter runs and the index on "
                f"'{name}' cannot skip any data.",
                fix=f"If '{name}' does not really hold {_plain_type(semantic_type)}, correct its type in data management.",
            )
        return _PredicateCopy(
            message=f"{label} '{name}' is compared against a value of another type, so every row has to be "
            f"converted and the index on '{name}' goes unused.",
            fix=f"Compare '{name}' against {_plain_type(physical_type)}.",
            # The AI prompt keeps the engine's type name: its reader is a model rewriting HogQL, not
            # someone looking for a setting in the UI.
            ai_fix_prompt=f"Rewrite this filter so '{name}' is compared against a {physical_type} value.",
        )

    if verdict == PredicateIndexVerdict.UNINDEXED_JSON:
        # A property the reader is denied gets the same copy as one that simply is not materialized.
        # The printer drops restricted keys from the JSON blob rather than erroring, so a denied
        # property reads as one that was never set; copy that named the restriction would undo that.
        return _PredicateCopy(
            message=f"{label} '{name}' is read out of the properties JSON on every row, with no index to skip data.",
            fix=f"Materialize '{name}' so this filter reads a dedicated column instead of parsing the JSON.",
        )

    if verdict == PredicateIndexVerdict.UNINDEXED_COLUMN:
        return _PredicateCopy(
            message=f"{label} '{name}' has its own column, but no index on it covers '{plan.operator}'.",
        )

    return _PredicateCopy(
        message=f"{label} '{name}' is filtered with '{plan.operator}', which reads every row because no index "
        "can rule one out.",
    )


class _FilterPredicateCollector(TraversingVisitor):
    """Collects property comparisons from filtering positions only.

    A comparison in a select expression or a HAVING clause never prunes a read, so reporting it as
    unindexed would send the reader after a fix that changes nothing. Descends through and/or/not so
    a predicate nested in a boolean tree is still found, and treats anything under a negation as
    unprunable for the same reason `!=` is.
    """

    def __init__(self, context: HogQLContext) -> None:
        super().__init__()
        self.context = context
        self.predicates: list[PredicateIndexEligibility] = []
        self._seen: set[tuple[int | None, int | None, str, ast.CompareOperationOp]] = set()

    def visit_select_query(self, node: ast.SelectQuery) -> None:
        for filter_expr in (node.where, node.prewhere):
            if filter_expr is not None:
                self._collect(filter_expr, negated=False)
        super().visit_select_query(node)

    def _collect(self, node: ast.Expr, negated: bool) -> None:
        if isinstance(node, ast.Not):
            self._collect(node.expr, negated=not negated)
            return
        if isinstance(node, ast.And | ast.Or):
            for child in node.exprs:
                self._collect(child, negated=negated)
            return
        # `not x` parses to a Call rather than an ast.Not, and `and`/`or` can be written in call form,
        # so the boolean connectives have to be recognized in both shapes.
        if isinstance(node, ast.Call):
            name = node.name.lower()
            if name == "not" and len(node.args) == 1:
                self._collect(node.args[0], negated=not negated)
            elif name in ("and", "or"):
                for arg in node.args:
                    self._collect(arg, negated=negated)
            return
        if isinstance(node, ast.CompareOperation):
            self._record(node, negated=negated)

    def _record(self, node: ast.CompareOperation, negated: bool) -> None:
        plan = plan_property_comparison(node, self.context)
        if plan is None:
            return

        # A rewritten query can carry the same predicate twice with identical spans; the property name
        # and operator keep distinct predicates apart when they share a span, which is every predicate
        # in a JSON-sourced node, where there are no locations at all.
        key = (node.start, node.end, plan.access.property_name, plan.operator)
        if key in self._seen:
            return
        self._seen.add(key)

        self.predicates.append(eligibility_from_plan(plan, negated=negated, start=node.start, end=node.end))
