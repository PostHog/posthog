import functools
from collections.abc import Collection
from dataclasses import dataclass

from posthog.schema import HogQLNotice

from posthog.hogql import ast
from posthog.hogql.constants import FLAG_CALLED_EVENT
from posthog.hogql.context import HogQLContext
from posthog.hogql.database.models import FieldOrTable, Table, VirtualTable
from posthog.hogql.database.schema.events import EventsTable
from posthog.hogql.database.schema.flag_evaluations import FlagEvaluationsTable
from posthog.hogql.database.schema.util.where_clause_extractor import event_field_type, unwrap_table_alias_type
from posthog.hogql.resolver import resolve_types
from posthog.hogql.transforms.events_predicate_pushdown import PREDICATE_SAFE_JOIN_TYPES
from posthog.hogql.transforms.flag_calls_from_flag_evaluations import (
    EVENTS_NAMES,
    EventsScan,
    ScanVisitor,
    filter_conjuncts,
)
from posthog.hogql.visitor import TraversingVisitor, clone_expr

from posthog.dataclasses import frozen

# The copy describes the move the way the troubleshooting doc that the "Learn more" link opens does. First, PostHog
# reads flag calls from posthog.flag_evaluations. Then it stops writing them to the events table.
FLAG_CALLED_ON_EVENTS_NOTICE = (
    f"Once PostHog stops writing flag calls to the events table, this query reads {FLAG_CALLED_EVENT} events from "
    "posthog.flag_evaluations, which keeps the last 90 days of flag calls. If part of the query can't read that "
    "table, the query fails and says which part."
)

FLAG_CALLED_ON_EVENTS_AFTER_MOVE_WARNING = (
    f"PostHog no longer writes {FLAG_CALLED_EVENT} events to the events table, so this query, which reads them from "
    "there, returns only older ones. Query posthog.flag_evaluations to include recent flag calls."
)


FLAG_CALLED_STAYS_ON_EVENTS_WARNING = (
    f"Once PostHog stops writing flag calls to the events table, this query keeps reading {FLAG_CALLED_EVENT} events "
    "from there, so it misses new flag calls. Filter on that event alone, or query posthog.flag_evaluations directly."
)


def flag_called_fails_after_move_warning(reason: str) -> str:
    return (
        f"Once PostHog stops writing flag calls to the events table, this query fails because {reason}. Change that "
        "part of the query, or query posthog.flag_evaluations directly."
    )


# Querying posthog.flag_evaluations directly does not help here, because that table lacks the field too.
def flag_called_missing_field_warning(field_name: str) -> str:
    return (
        f"Once PostHog stops writing flag calls to the events table, this query fails because it reads {field_name}, "
        "which posthog.flag_evaluations doesn't have. Change that part of the query."
    )


FLAG_CALLED_FROM_FLAG_EVALUATIONS_NOTICE = (
    f"This query reads {FLAG_CALLED_EVENT} events from posthog.flag_evaluations, which keeps the last 90 days "
    "of flag calls."
)

FLAG_CALLED_FROM_BOTH_TABLES_NOTICE = (
    f"This query reads {FLAG_CALLED_EVENT} events from posthog.flag_evaluations, which keeps the last 90 days "
    "of flag calls, and other events from events."
)

# While events still holds every flag call, the union reads only the recent ones from posthog.flag_evaluations.
FLAG_CALLED_SPLIT_BY_AGE_NOTICE = (
    f"This query reads {FLAG_CALLED_EVENT} events from the last 90 days from posthog.flag_evaluations. "
    "It reads older ones and all other events from events."
)


class _FlagCalledLiteralFinder(TraversingVisitor):
    def __init__(self, table_class: type[Table]) -> None:
        super().__init__()
        self.table_class = table_class
        self.literals: list[ast.Constant] = []

    def visit_select_query(self, node: ast.SelectQuery) -> None:
        # The resolver inlines a saved view's body, parsed from the view's own text. Its offsets do not
        # point into the user's query.
        if node.view_name is not None:
            return
        super().visit_select_query(node)

    def visit_alias(self, node: ast.Alias) -> None:
        # The resolver inlines a saved expression's body in a hidden alias. The body's offsets point into its own text.
        if node.hidden:
            return
        super().visit_alias(node)

    def visit_field(self, node: ast.Field) -> None:
        # The inherited visit follows the field's type into shared CTE types, which takes exponential time.
        pass

    def visit_compare_operation(self, node: ast.CompareOperation) -> None:
        if node.op in (ast.CompareOperationOp.Eq, ast.CompareOperationOp.In, ast.CompareOperationOp.GlobalIn):
            for field_side, value_side in ((node.left, node.right), (node.right, node.left)):
                if _is_event_field_of(field_side, self.table_class):
                    self.literals.extend(_flag_called_constants(value_side))
        super().visit_compare_operation(node)


def _is_event_field_of(expr: ast.Expr, table_class: type[Table]) -> bool:
    field_type = event_field_type(expr)
    if field_type is None:
        return False
    table_type = unwrap_table_alias_type(field_type.table_type)
    return isinstance(table_type, ast.TableType) and isinstance(table_type.table, table_class)


def _flag_called_constants(expr: ast.Expr) -> list[ast.Constant]:
    if isinstance(expr, ast.Constant):
        return [expr] if expr.value == FLAG_CALLED_EVENT else []
    if isinstance(expr, (ast.Tuple, ast.Array)):
        return [constant for sub in expr.exprs for constant in _flag_called_constants(sub)]
    return []


def count_flag_calls_read_from_events(resolved: ast.AST) -> int:
    """How many `$feature_flag_called` literals a resolved query compares to the events table's `event` column.

    Unlike the warnings below, it counts a literal that a query builder made, which has no span.
    """
    finder = _FlagCalledLiteralFinder(EventsTable)
    finder.visit(resolved)
    return len(finder.literals)


def flag_called_on_events_notices(
    node: ast.SelectQuery | ast.SelectSetQuery, context: HogQLContext
) -> list[HogQLNotice]:
    """A notice on each `$feature_flag_called` literal that a query compares to the events table's `event` column.

    The query resolves on a clone, because the printed AST has been rewritten and its offsets no longer match
    what the user typed.
    """
    # A caller that passes an already printed AST never builds the database, and its AST may be rewritten.
    if context.database is None:
        return []
    finder = _FlagCalledLiteralFinder(EventsTable)
    with context.timings.measure("flag_called_warnings"):
        finder.visit(resolve_types(clone_expr(node), context, dialect="clickhouse"))
    # A literal that a variable supplies has no span, and a notice without one marks the whole query.
    return [
        HogQLNotice(message=FLAG_CALLED_ON_EVENTS_NOTICE, start=literal.start, end=literal.end)
        for literal in finder.literals
        if literal.start is not None and literal.end is not None
    ]


@frozen
class LiteralSpan:
    start: int | None
    end: int | None


def flag_called_spans_read_from_flag_evaluations(prepared: ast.AST) -> set[LiteralSpan]:
    """The spans of the `$feature_flag_called` literals that a prepared AST compares to `flag_evaluations.event`."""
    finder = _FlagCalledLiteralFinder(FlagEvaluationsTable)
    finder.visit(prepared)
    return {LiteralSpan(start=literal.start, end=literal.end) for literal in finder.literals}


def flag_called_spans_read_from_union(context: HogQLContext) -> set[LiteralSpan]:
    """The spans of the `$feature_flag_called` literals whose scan reads `events` and `flag_evaluations` together."""
    return {LiteralSpan(start=start, end=end) for start, end in context.flag_called_union_spans}


@functools.cache
def _flag_evaluations_fields() -> dict[str, FieldOrTable]:
    return FlagEvaluationsTable().fields


def _missing_field(chain: list[str | int]) -> str | None:
    """The name of the field that `chain`, a read of the events scan, takes from a flag_evaluations sub-table that
    lacks it, such as `goe_0.properties`, or None."""
    if len(chain) < 2:
        return None
    sub_table = _flag_evaluations_fields().get(str(chain[0]))
    if isinstance(sub_table, VirtualTable) and str(chain[1]) not in sub_table.fields:
        return f"{chain[0]}.{chain[1]}"
    return None


# The swap's reason for a flag-call scan that it can't move, such as one joined under a name other than `events`.
_UNMOVABLE_SHAPE = "it reads events in a shape that can't be moved to posthog.flag_evaluations yet"


@dataclass(frozen=False)
class _ScanCheck:
    scan: EventsScan
    literals: list[LiteralSpan]
    warning: str | None


class _ScanLiteralFinder(TraversingVisitor):
    """The `$feature_flag_called` literals that `root`, one SELECT, compares to the `event` column of `scan`."""

    def __init__(self, root: ast.SelectQuery, scan: EventsScan) -> None:
        super().__init__()
        self.root = root
        self.scan = scan
        self.literals: list[LiteralSpan] = []

    def visit_select_query(self, node: ast.SelectQuery) -> None:
        # A subquery has its own scans.
        if node is self.root:
            super().visit_select_query(node)

    def visit_select_set_query(self, node: ast.SelectSetQuery) -> None:
        pass

    def visit_field(self, node: ast.Field) -> None:
        pass

    def visit_compare_operation(self, node: ast.CompareOperation) -> None:
        if node.op in (ast.CompareOperationOp.Eq, ast.CompareOperationOp.In, ast.CompareOperationOp.GlobalIn):
            for field_side, value_side in ((node.left, node.right), (node.right, node.left)):
                if self.scan.column(field_side) == ["event"]:
                    self.literals.extend(
                        LiteralSpan(start=constant.start, end=constant.end)
                        for constant in _flag_called_constants(value_side)
                        if constant.start is not None and constant.end is not None
                    )
        super().visit_compare_operation(node)


@frozen
class _FoundScan:
    position: int
    # The name the query gives the table, such as `events` or `posthog.events`.
    name: str
    scan: EventsScan


def _events_scans(node: ast.SelectQuery, ctes: Collection[str]) -> list[_FoundScan]:
    """Each events scan in the FROM chain of `node`."""
    scans: list[_FoundScan] = []
    join = node.select_from
    position = 0
    while join is not None:
        # The query is unresolved, so the chain is all there is to read.
        # nosemgrep: hogql-no-string-table-chain
        name = ".".join(str(part) for part in join.table.chain) if isinstance(join.table, ast.Field) else None
        if name is not None and name in EVENTS_NAMES and name not in ctes:
            # Only the first scan can read unqualified names, and EventsScan.of decides when it can.
            scan = (
                EventsScan.of(node, lambda: True, ctes)
                if position == 0
                else EventsScan(
                    join,
                    join.alias or name.replace(".", "__"),
                    other_tables=frozenset(),
                    qualified_only=True,
                    flag_key_compares_as_string=lambda: True,
                )
            )
            if scan is not None:
                scans.append(_FoundScan(position=position, name=name, scan=scan))
        join = join.next_join
        position += 1
    return scans


def _union_refusal(node: ast.SelectQuery, scan: EventsScan, position: int) -> str | None:
    if position > 0:
        return "it joins events after another table"
    refusal = scan.shape_refusal(node, ratio_sample_ok=True)
    if refusal is not None:
        return refusal
    join = scan.join.next_join
    while join is not None:
        if join.join_type is None or join.join_type.removeprefix("GLOBAL ") not in PREDICATE_SAFE_JOIN_TYPES:
            return f"it joins another table to events with {join.join_type or 'an unknown join type'}"
        join = join.next_join
    return None


def _mode_2_check(node: ast.SelectQuery, found: _FoundScan, literals: list[LiteralSpan], union_on: bool) -> _ScanCheck:
    """How the scan of `found` reads flag calls once they are only in flag_evaluations.

    It follows the rules of `_EventsScanSwapper` and `_UnionRenamer`. The swap moves a scan whose filters pin `event` to
    flag calls. It moves a joined scan only when the query names it `events`. The union reads a sampled first scan and
    every scan the swap leaves, when `union_on`. A scan that neither reads stays on events and misses new flag calls.
    """
    scan, position = found.scan, found.position
    sampled = scan.join.sample is not None and not scan.join.sample.samples_all_rows()
    if scan.pins_flag_calls(filter_conjuncts(node), needs_flag_key=False) and not (
        union_on and sampled and position == 0
    ):
        refusal = _UNMOVABLE_SHAPE if position > 0 and found.name != "events" else scan.shape_refusal(node)
    elif union_on:
        refusal = _union_refusal(node, scan, position)
    else:
        return _ScanCheck(scan=scan, literals=literals, warning=FLAG_CALLED_STAYS_ON_EVENTS_WARNING)
    warning = flag_called_fails_after_move_warning(refusal) if refusal is not None else None
    return _ScanCheck(scan=scan, literals=literals, warning=warning)


class _MoveRefusalFinder(ScanVisitor):
    def __init__(self, union_on: bool) -> None:
        super().__init__()
        self.union_on = union_on
        # The checks of the scans in each enclosing SELECT, innermost last.
        self.frames: list[list[_ScanCheck]] = []
        self.refusals: dict[LiteralSpan, str] = {}

    def visit_select_query(self, node: ast.SelectQuery) -> None:
        self.frames.append([])
        super().visit_select_query(node)
        for check in self.frames.pop():
            if check.warning is not None:
                self.refusals.update(dict.fromkeys(check.literals, check.warning))

    def visit_scan_query(self, node: ast.SelectQuery) -> None:
        for found in _events_scans(node, self.ctes):
            finder = _ScanLiteralFinder(node, found.scan)
            finder.visit(node)
            if not finder.literals:
                continue
            self.frames[-1].append(_mode_2_check(node, found, finder.literals, self.union_on))

    def visit_field(self, node: ast.Field) -> None:
        for check in self.frames[-1] if self.frames else []:
            if check.warning is not None:
                continue
            chain = check.scan.column(node)
            missing = _missing_field(chain) if chain else None
            if missing is not None:
                check.warning = flag_called_missing_field_warning(missing)


def flag_called_move_refusals(node: ast.SelectQuery | ast.SelectSetQuery, *, union_on: bool) -> dict[LiteralSpan, str]:
    """The warning for each `$feature_flag_called` literal whose query fails once flag calls are only in
    posthog.flag_evaluations, keyed by the literal's span. `union_on` says whether the union reads the scans that the
    swap leaves, such as one filtered with `event IN ('$pageview', '$feature_flag_called')` or a sampled flag-call scan.

    It reads only the text of the unresolved query. It finds the shapes that the swap and the union refuse and the
    sub-table fields, such as `goe_0.properties`, that flag_evaluations lacks. It misses a refusal that only
    resolution shows, such as a name that binds to another column in flag_evaluations.
    """
    finder = _MoveRefusalFinder(union_on)
    finder.visit(node)
    return finder.refusals
