"""Read flag calls from `events` and `posthog.flag_evaluations` together when a query reads them with other events.

The flag_evaluations swap in `flag_calls_from_flag_evaluations` swaps a scan that reads only flag calls to
`posthog.flag_evaluations`. This transform renames each remaining `events` scan that names
`$feature_flag_called` to `posthog.events_with_flag_calls`, a lazy table with the events fields. Lazy table
resolution replaces it with a union of the two tables, split at the coverage start.

The rename runs before type resolution, so every rule here is syntactic. The union returns the right rows for any
scan, so the rules decide which scans pay for a second table, and which shapes the union cannot read yet.
"""

import math
from collections import ChainMap
from collections.abc import Callable, Iterator, Mapping
from contextlib import contextmanager
from functools import cache, cached_property, partial
from math import floor
from typing import TYPE_CHECKING, cast

import structlog

from posthog.hogql import ast
from posthog.hogql.constants import FLAG_CALLED_EVENT
from posthog.hogql.context import HogQLContext
from posthog.hogql.database.lazy_join_tags import (
    EVENTS_TO_SESSIONS_V1,
    EVENTS_TO_SESSIONS_V2,
    EVENTS_TO_SESSIONS_V3,
    FOREIGN_KEY,
    GROUP_N,
    PERSON_DISTINCT_ID_OVERRIDES,
    PERSON_DISTINCT_IDS,
    PERSONS,
)
from posthog.hogql.database.models import Table
from posthog.hogql.database.schema.events import EventsTable
from posthog.hogql.database.schema.events_with_flag_calls import (
    EVENTS_WITH_FLAG_CALLS_CHAIN,
    EVENTS_WITH_FLAG_CALLS_TABLE,
    EventsWithFlagCallsTable,
    FlagEvaluationsColumns,
    property_read,
    serialized_like_events,
    union_table_of,
)
from posthog.hogql.database.schema.util.where_clause_extractor import (
    contains_in_cohort,
    contains_row_multiplying_function,
    is_nondeterministic_function,
)
from posthog.hogql.errors import QueryError, ResolutionError
from posthog.hogql.restricted_properties import key_read_overlaps_restriction, restricted_property_keys_for_table_type
from posthog.hogql.transforms.events_predicate_pushdown import PREDICATE_SAFE_JOIN_TYPES, SelectAliasInliner
from posthog.hogql.transforms.flag_calls_from_flag_evaluations import (
    EVENTS_NAMES,
    EventsScan,
    ScanVisitor,
    SyntaxVisitor,
    and_conditions,
    boolean_operands,
    compared_values,
    comparison_of,
    filter_conjuncts,
    flag_calls_only_in_flag_evaluations_error,
    flag_key_predicate,
    names_flag_called_event,
    point_scan_at,
    ratio_sample_fraction,
    select_aliases,
    team_flag_key_compares_as_string,
)
from posthog.hogql.transforms.order_by_pushdown import unwrap_alias
from posthog.hogql.type_system import parse_sql_runtime_type
from posthog.hogql.visitor import CloningVisitor

from posthog.dataclasses import frozen
from posthog.property_columns import TableColumn

if TYPE_CHECKING:
    from posthog.hogql.database.database import Database

logger = structlog.get_logger(__name__)

# The joins whose resolver compares only the join's key and `extra_from_fields` on the source table. Lazy table
# resolution projects exactly those from the union, so a join that reads anything else would name a missing column.
# The most compared values the flag-call finder reads for one scan. Past it, the finder treats the scan as one that
# names flag calls. The union returns the right rows for any scan, so the limit costs only a second table read.
_COMPARED_VALUES_BUDGET = 100_000

# The resolver reads a name as a column of events before it reads it as a CTE. The database only adds fields to the
# events table, so each of these names shadows a CTE in every query.
_EVENTS_FIELDS = frozenset(EventsTable().fields)

# The value the flag-call finder gives a CTE whose value is not a constant or a list of constants, because such a value
# can compute `$feature_flag_called` or read a name the finder does not track. A scan that the union can read then
# costs a second table read. On mode 2, a scan that the union refuses then fails the query.
_MAY_NAME_FLAG_CALLS = ast.Constant(value=FLAG_CALLED_EVENT)

# The value the flag-call finder gives a read of a lambda argument. It is not a field, so the finder never reads the
# argument as a column of the scan, even when the argument is named `event`.
_LAMBDA_ARGUMENT = ast.Constant(value=None)

_UNION_JOIN_RESOLVERS = frozenset(
    {
        EVENTS_TO_SESSIONS_V1,
        EVENTS_TO_SESSIONS_V2,
        EVENTS_TO_SESSIONS_V3,
        FOREIGN_KEY,
        GROUP_N,
        PERSON_DISTINCT_ID_OVERRIDES,
        PERSON_DISTINCT_IDS,
        PERSONS,
    }
)


def refuse_union_table_by_name(node: ast.AST, context: HogQLContext) -> None:
    """Raises when `node` names the union table. The table exists only for the rename to point at, so a query that
    names it would depend on an internal table."""
    if context.database is None or not context.database.has_table(EVENTS_WITH_FLAG_CALLS_CHAIN):
        return
    finder = _UnionTableFinder(context.database)
    finder.visit(node)
    if finder.found:
        raise QueryError(f"Unknown table `posthog.{EVENTS_WITH_FLAG_CALLS_TABLE}`.")


@frozen
class UnionRefusal:
    join: ast.JoinExpr
    reason: str


@frozen
class UnionRename:
    renamed: bool
    # Why the union cannot read each other scan that names `$feature_flag_called` with other events.
    refusals: tuple[UnionRefusal, ...]
    # The (start, end) of each `$feature_flag_called` literal that a renamed scan compares with its `event`.
    literal_spans: frozenset[tuple[int, int]] = frozenset()


def read_flag_calls_with_union(
    node: ast.AST, context: HogQLContext, flag_key_compares_as_string: Callable[[], bool]
) -> UnionRename:
    """Points each mixed flag-call scan in `node` at the union, in place, when the union reads this query's scans.

    An organization whose flag calls are only in `flag_evaluations` cannot read a refused scan at all. Every other
    organization keeps reading `events` for it.
    """
    database = _union_database(context)
    if database is None:
        return UnionRename(renamed=False, refusals=())
    only_in_flag_evaluations = context.flag_calls_only_in_flag_evaluations()
    if not only_in_flag_evaluations and _flag_key_is_restricted(database, context):
        # The union tells the flag calls that only events holds by their raw `$feature_flag`, with `_HAS_FLAG_KEY`, and
        # a restricted property reads as missing. Each flag call since the cutoff would then come from both tables.
        return UnionRename(renamed=False, refusals=())
    return rename_flag_call_scans_to_union(
        node, flag_key_compares_as_string, only_in_flag_evaluations=only_in_flag_evaluations
    )


def union_applies(context: HogQLContext) -> bool:
    """Whether the union reads this query's mixed flag-call scans."""
    return _union_database(context) is not None


def read_flag_calls_in_inline_cohort(
    query: ast.SelectQuery | ast.SelectSetQuery, context: HogQLContext
) -> ast.SelectQuery | ast.SelectSetQuery:
    """Points each flag-call scan in an inline cohort `query` at the union, in place, and returns `query`.

    The resolver and the subquery and LEFTJOIN paths of `IN COHORT` splice an inline cohort in after the swap in
    `resolve_flag_calls_from_flag_evaluations` has run, so that swap never sees its scans. Only the rename applies
    here, because the swap's binding check needs the whole query.

    Only an organization whose flag calls are only in `flag_evaluations` reads the union here. While `events` holds
    every flag call, an inline cohort reads them from `events` as before. `resolve_in_cohorts_conjoined` splices its
    cohorts in before the swap runs, so its caller passes `read_flag_calls_from_union=False`: the swap sees those scans.
    """
    if _union_database(context) is None or not context.flag_calls_only_in_flag_evaluations():
        return query
    renamer = _UnionRenamer(
        cache(partial(team_flag_key_compares_as_string, context)),
        only_in_flag_evaluations=True,
        rename_flag_only_scans=True,
    )
    renamer.visit(query)
    if renamer.refusals:
        raise flag_calls_only_in_flag_evaluations_error(renamer.refusals[0].reason)
    return query


def require_union_readable(resolved: ast.AST, context: HogQLContext, view_name: str | None = None) -> None:
    """Raises a QueryError when an organization with flag calls only in `flag_evaluations` has a union scan in
    `resolved` that reads a field the union cannot supply. An inline cohort is spliced in after the rename, so only
    the resolved query shows its scans. `IN COHORT` resolves its join before lazy table resolution builds the
    union, so that call is the last point where ClickHouse has not yet rejected the query."""
    if _union_database(context) is None or not context.flag_calls_only_in_flag_evaluations():
        return
    unreadable = union_unreadable_reason(resolved, context)
    if unreadable is not None:
        raise flag_calls_only_in_flag_evaluations_error(unreadable, view_name)


def union_unreadable_reason(node: ast.AST, context: HogQLContext) -> str | None:
    """Why the union cannot read a scan in the resolved `node`, or None when it can read them all.

    Lazy table resolution builds the union after this check, from these same fields, the keys of the joins that start
    from the scan, and the other fields those joins declare that they read.
    """
    database = _union_database(context)
    if database is None:
        return None
    collector = _UnionChainCollector()
    collector.visit(node)
    if collector.unreadable_joins:
        return f"it reads {collector.unreadable_joins[0]}, a join that the union can't read yet"
    columns = FlagEvaluationsColumns(
        database.get_table(EVENTS_WITH_FLAG_CALLS_CHAIN), database.get_table(["posthog", "flag_evaluations"])
    )
    if collector.export_collision is not None:
        first, second = (".".join(str(part) for part in chain) for chain in collector.export_collision)
        return f"it reads {first} and {second}, which the union would return as one column"
    for chain in collector.chains:
        if columns.chain(chain) is None:
            return f"it reads {'.'.join(str(part) for part in chain)}, which that table doesn't have"
    return _typed_materialized_property(columns.events, collector.chains, context)


def _typed_materialized_property(union: Table, chains: list[list[str | int]], context: HogQLContext) -> str | None:
    # A raw read of a typed materialized column keeps the column's type, but the flag_evaluations branch reads a JSON
    # String, so the UNION ALL has no common type. The native events schema and disabled materialization read JSON.
    if context.uses_new_events_schema() or context.modifiers.materializationMode == "disabled":
        return None
    reads = {read for chain in chains if (read := property_read(union, chain)) is not None}
    if not reads:
        return None
    # Deferred: the registry reads Django models, which this module does not import.
    from posthog.clickhouse.materialized_columns import get_enabled_materialized_columns_by_table  # noqa: PLC0415

    materialized = get_enabled_materialized_columns_by_table().get("events", {})
    for read in sorted(reads, key=lambda read: (read.column, read.key)):
        backing = materialized.get((read.key, cast(TableColumn, read.column)))
        if backing is not None and parse_sql_runtime_type(backing.type).family != "string":
            return f"it reads {read.key}, which events stores in a {backing.type} column"
    return None


@frozen
class UnionBranchFilters:
    """The predicates that a union scan's branches copy from the query that reads the scan.

    Each is a set of conjuncts from that query's WHERE and PREWHERE, so every row the query keeps passes it.
    """

    events: ast.Expr | None
    # For the branch that reads flag_evaluations. A read of `event` is `$feature_flag_called` there.
    flag_evaluations: ast.Expr | None
    # False when the query pins `$feature_flag` to keys that only a call with a non-empty string key matches.
    keyless_flag_calls_can_match: bool


def union_branch_filters(
    node: ast.SelectQuery,
    union: EventsWithFlagCallsTable,
    columns: FlagEvaluationsColumns,
    flag_key_compares_as_string: Callable[[], bool],
    context: HogQLContext,
) -> UnionBranchFilters:
    """The filters for the union scan that `node` reads, from the resolved WHERE and PREWHERE of `node`."""
    extracted = _scan_conjuncts(node, union)
    flag_call_conjuncts = [_fold(_EventAsFlagCall().visit(conjunct)) for conjunct in extracted]
    # The flag_evaluations swap accepts a key only when it is a non-empty string that no other JSON value prints as.
    # A flag call that ingestion left in events, with a missing, empty or non-string key, cannot match one.
    keys = EventsScan.of_scan_chains(flag_key_compares_as_string).flag_keys(
        [_StepTests().visit(conjunct) for conjunct in flag_call_conjuncts]
    )
    flag_evaluations_conjuncts = [
        mapped
        for conjunct in flag_call_conjuncts
        if _truth(conjunct) is not True
        and (mapped := _FlagEvaluationsReads(columns, context).copy(conjunct)) is not None
    ]
    return UnionBranchFilters(
        events=_events_filter(extracted),
        flag_evaluations=and_conditions([*flag_evaluations_conjuncts, flag_key_predicate("flag_evaluations", keys)]),
        keyless_flag_calls_can_match=not keys,
    )


def union_events_filter(node: ast.SelectQuery, union: EventsWithFlagCallsTable) -> ast.Expr | None:
    """The filter that a scan of `events` copies from `node`, as `union_branch_filters` builds it."""
    return _events_filter(_scan_conjuncts(node, union))


def union_scan_sample(node: ast.SelectQuery, union: EventsWithFlagCallsTable) -> ast.SampleExpr | None:
    """The SAMPLE that `node` puts on its scan of the union, or None."""
    join = node.select_from
    while join is not None:
        if join.sample is not None and union_table_of(join.table.type if join.table else join.type) is union:
            return join.sample
        join = join.next_join
    return None


def sample_flag_evaluations_filter(sample: ast.SampleExpr, distinct_id: ast.Field) -> ast.Expr:
    """The predicate that keeps the `flag_evaluations` rows whose `distinct_id` ClickHouse's `SAMPLE` keeps on `events`.

    `events` samples by `cityHash64(distinct_id)`, and a ratio keeps the hashes below that ratio of the UInt64 range.
    """
    fraction = ratio_sample_fraction(sample)
    if fraction is None:
        raise QueryError("The flag call union reads only a SAMPLE ratio between 0 and 1.")
    return ast.CompareOperation(
        op=ast.CompareOperationOp.Lt,
        left=ast.Call(name="cityHash64", args=[distinct_id]),
        right=ast.Constant(value=floor(fraction * 2**64)),
    )


def rename_flag_call_scans_to_union(
    node: ast.AST,
    flag_key_compares_as_string: Callable[[], bool],
    *,
    only_in_flag_evaluations: bool,
) -> UnionRename:
    """Point each `events` scan that the union can read, and whose query names `$feature_flag_called`, at the union.

    A scan qualifies when all of these hold:

    1. Its query compares the scan's `event` with `$feature_flag_called` by `=` or `IN`, in one of the query's own
       clauses. A subquery's comparison does not count. A funnel step column such as
       `if(event = '$feature_flag_called' AND ..., 1, 0)` counts. A name of one of the query's aliases reads the
       expression that the alias names. A name of a column CTE in scope, `WITH <expr> AS name`, reads `<expr>` when
       no lambda's name, select alias or events column has that name.
    2. The scan is the first table in FROM, and every join after it is INNER, LEFT or CROSS, GLOBAL or not.
    3. The scan has no FINAL, table arguments or column aliases, and its SAMPLE is 1 or a ratio between 0 and 1 without
       OFFSET. Its query selects no `*` or `COLUMNS(...)`.

    A scan that the flag_evaluations swap changed reads `posthog.flag_evaluations` and is not an `events` scan any
    more. The flag_evaluations swap swaps or refuses a first scan that reads only flag calls, so the union neither
    renames nor refuses it. The swap cannot read an unqualified `event` next to a join. On mode 1 a first scan that
    reads only flag calls through such an `event` stays on events. On mode 2 the union renames it.

    A refusal does not decide the query on mode 2. `swap_scans_found_by_type` can still move the refused scan to
    flag_evaluations, as it does for a scan of only flag calls joined after another table.
    """
    renamer = _UnionRenamer(flag_key_compares_as_string, only_in_flag_evaluations)
    renamer.visit(node)
    return UnionRename(
        renamed=renamer.renamed, refusals=tuple(renamer.refusals), literal_spans=frozenset(renamer.literal_spans)
    )


def _union_database(context: HogQLContext) -> "Database | None":
    """The database when the union reads this query's mixed flag-call scans, and None otherwise."""
    if not context.rewrite_flag_calls_to_flag_evaluations or not context.reads_flag_calls_with_union():
        return None
    return context.database


def _flag_key_is_restricted(database: "Database", context: HogQLContext) -> bool:
    restricted = restricted_property_keys_for_table_type(ast.TableType(table=database.get_table("events")), context)
    return key_read_overlaps_restriction("$feature_flag", restricted)


def _union_chain(field_type: ast.Type | None) -> tuple[EventsWithFlagCallsTable, list[str | int]] | None:
    """The union scan that a resolved field reads directly, and its chain there, or None."""
    property_chain: list[str | int] = []
    if isinstance(field_type, ast.PropertyType):
        property_chain = list(field_type.chain)
        field_type = field_type.field_type
    if not isinstance(field_type, ast.FieldType):
        return None
    chain: list[str | int] = [field_type.name, *property_chain]
    if isinstance(field_type.table_type, ast.VirtualTableType):
        chain = [field_type.table_type.field, *chain]
    union = union_table_of(field_type.table_type)
    return (union, chain) if union is not None else None


def _scan_conjuncts(node: ast.SelectQuery, union: EventsWithFlagCallsTable) -> list[ast.Expr]:
    """The parts of the WHERE and PREWHERE of `node` that read only the union scan, with reads as chains on it."""
    aliases = {expr.alias: expr.expr for expr in node.select if isinstance(expr, ast.Alias)}
    inliner = SelectAliasInliner(aliases)
    # The union exports a SELECT alias as its value, and `toJSONString` of the alias serializes that value. A copy of
    # the inlined read would serialize the way a direct read does instead, so a conjunct like that is not copied.
    conjuncts = [
        conjunct for conjunct in filter_conjuncts(node) if not (aliases and _serializes_select_alias(conjunct, aliases))
    ]
    extracted = [_scan_predicate(inliner.visit(conjunct), union) for conjunct in conjuncts]
    return [conjunct for conjunct in extracted if conjunct is not None]


def _scan_predicate(expr: ast.Expr, union: EventsWithFlagCallsTable) -> ast.Expr | None:
    """`expr` with each read as a chain on the scan, or the conjuncts of it that read only the scan, or None.

    An OR counts only when every branch of it does, so every row that `expr` accepts passes the result.
    """
    if (parts := boolean_operands(expr, ast.And)) is not None:
        return and_conditions([_scan_predicate(part, union) for part in parts])
    if (branches := boolean_operands(expr, ast.Or)) is not None:
        extracted = [_scan_predicate(branch, union) for branch in branches]
        kept = [branch for branch in extracted if branch is not None]
        return ast.Or(exprs=kept) if kept and len(kept) == len(extracted) else None
    # A copy in each branch would multiply rows, or would move a cohort join that the printer adds later.
    if contains_row_multiplying_function(expr) or contains_in_cohort(expr):
        return None
    copier = _ScanReadCopier(union)
    copied = copier.visit(expr)
    return None if copier.failed else copied


def _events_filter(scan_conjuncts: list[ast.Expr]) -> ast.Expr | None:
    return and_conditions([_Qualified("events").visit(conjunct) for conjunct in scan_conjuncts])


def _truth(expr: ast.Expr) -> bool | None:
    """The truth value of a constant false, true, 0 or 1, or None for any other expression."""
    if isinstance(expr, ast.Constant) and expr.value in (0, 1):
        return bool(expr.value)
    return None


# Whether a comparison of constants passes when the left value is among the right values.
_MATCH_PASSES = {
    ast.CompareOperationOp.Eq: True,
    ast.CompareOperationOp.In: True,
    ast.CompareOperationOp.NotEq: False,
    ast.CompareOperationOp.NotIn: False,
}


def _compares_like_clickhouse(values: list[object]) -> bool:
    """Whether Python and ClickHouse agree on how these constants compare.

    ClickHouse converts mixed types before it compares (`1 IN ('1')` is true), which Python does not.
    NULL and floats are neither str nor int, so they never fold.
    """
    return any(all(isinstance(value, kind) for value in values) for kind in (str, int))


def _fold(expr: ast.Expr) -> ast.Expr:
    """`expr` with comparisons of constants, and the AND, OR, NOT and `if` they decide, replaced by their value."""
    if (parts := boolean_operands(expr, ast.And)) is not None:
        folded = [_fold(part) for part in parts]
        if any(_truth(part) is False for part in folded):
            return ast.Constant(value=False)
        return and_conditions([part for part in folded if _truth(part) is not True]) or ast.Constant(value=True)
    if (parts := boolean_operands(expr, ast.Or)) is not None:
        folded = [_fold(part) for part in parts]
        if any(_truth(part) is True for part in folded):
            return ast.Constant(value=True)
        kept = [part for part in folded if _truth(part) is not False]
        if not kept:
            return ast.Constant(value=False)
        return kept[0] if len(kept) == 1 else ast.Or(exprs=kept)
    if isinstance(expr, ast.Not) or (isinstance(expr, ast.Call) and expr.name == "not" and len(expr.args) == 1):
        inner = _fold(expr.expr if isinstance(expr, ast.Not) else expr.args[0])
        truth = _truth(inner)
        return ast.Constant(value=not truth) if truth is not None else ast.Not(expr=inner)
    if isinstance(expr, ast.Call) and expr.name == "if" and len(expr.args) == 3:
        args = [_fold(arg) for arg in expr.args]
        truth = _truth(args[0])
        if truth is not None:
            return args[1] if truth else args[2]
        return ast.Call(name="if", args=args)
    compared = comparison_of(expr)
    if compared is None:
        return expr
    op, left, right = compared.op, _fold(compared.left), _fold(compared.right)
    values = right.exprs if isinstance(right, (ast.Tuple, ast.Array)) else [right]
    constants = [value.value for value in values if isinstance(value, ast.Constant)]
    if (
        op in _MATCH_PASSES
        and isinstance(left, ast.Constant)
        and len(constants) == len(values)
        and _compares_like_clickhouse([left.value, *constants])
        and (len(values) == 1 or op in (ast.CompareOperationOp.In, ast.CompareOperationOp.NotIn))
    ):
        return ast.Constant(value=(left.value in constants) == _MATCH_PASSES[op])
    return ast.CompareOperation(op=op, left=left, right=right)


def _step_condition(expr: ast.Expr) -> ast.Expr | None:
    """`c` for a funnel step test such as `if(c, 1, 0) = 1`, or None for any other expression."""
    compared = comparison_of(expr)
    if compared is None or compared.op != ast.CompareOperationOp.Eq:
        return None
    for step, value in ((compared.left, compared.right), (compared.right, compared.left)):
        if (
            isinstance(step, ast.Call)
            and step.name == "if"
            and len(step.args) == 3
            and _truth(step.args[1]) is True
            and _truth(step.args[2]) is False
            and _truth(value) is True
        ):
            return step.args[0]
    return None


def _union_refusal(node: ast.SelectQuery, scan: EventsScan, position: int) -> str | None:
    """Why the union cannot stand in for `scan`, the scan at `position` in the FROM chain of `node`, or None."""
    if position > 0:
        return "it joins events after another table"
    refusal = scan.shape_refusal(node, ratio_sample_ok=True)
    if refusal is not None:
        return refusal
    join = scan.join.next_join
    while join is not None:
        # A predicate moves into the union's branches only across these joins. GLOBAL changes only where ClickHouse
        # builds the right side, not which rows the join keeps.
        if join.join_type is None or join.join_type.removeprefix("GLOBAL ") not in PREDICATE_SAFE_JOIN_TYPES:
            return f"it joins another table to events with {join.join_type or 'an unknown join type'}"
        join = join.next_join
    return None


@frozen
class _FlagCallScan:
    position: int
    scan: EventsScan
    literals: list[ast.Constant]
    with_values: list["_WithValue"]

    @property
    def unchecked(self) -> bool:
        """True when the finder stopped at the budget before it found a `$feature_flag_called` literal."""
        return not (self.literals or self.with_values)


def _flag_call_scans(
    node: ast.SelectQuery,
    flag_key_compares_as_string: Callable[[], bool],
    ctes: Mapping[str, ast.CTE],
    aliases: "_Aliases",
    with_values: "_WithValues",
) -> list[_FlagCallScan]:
    """Each `events` scan in the FROM chain of `node` whose query names `$feature_flag_called`, with its position and
    the literals that name it."""
    scans: list[_FlagCallScan] = []
    join = node.select_from
    position = 0
    while join is not None:
        # The rename runs before type resolution, so the chain is all it can read. EventsScan.of matches the same
        # names, and the binding check rejects a rename that changes what a name binds to.
        # nosemgrep: hogql-no-string-table-chain
        name = ".".join(str(part) for part in join.table.chain) if isinstance(join.table, ast.Field) else None
        if name is not None and name in EVENTS_NAMES and name not in ctes:
            # Only the first scan can read unqualified names, and EventsScan.of decides when it can.
            scan = (
                EventsScan.of(node, flag_key_compares_as_string, ctes)
                if position == 0
                else EventsScan(
                    join,
                    join.alias or name.replace(".", "__"),
                    other_tables=frozenset(),
                    qualified_only=True,
                    flag_key_compares_as_string=flag_key_compares_as_string,
                )
            )
            if (
                scan is not None
                and (finder := _flag_call_finder(node, scan, aliases, ctes, with_values)).names_flag_calls
            ):
                scans.append(
                    _FlagCallScan(
                        position=position,
                        scan=scan,
                        literals=finder.literals,
                        with_values=list(finder.with_values_read.values()),
                    )
                )
        join = join.next_join
        position += 1
    return scans


def _flag_call_finder(
    node: ast.SelectQuery,
    scan: EventsScan,
    aliases: "_Aliases",
    ctes: Mapping[str, ast.CTE],
    with_values: "_WithValues",
) -> "_FlagCallComparisonFinder":
    finder = _FlagCallComparisonFinder(node, scan, aliases, ctes, with_values)
    finder.visit(node)
    return finder


class _Aliases(CloningVisitor):
    """Copies an unresolved expression with each name of a select alias that names a field replaced by that field.

    The resolver reads a name without a table prefix as a select alias before it reads it as a column.
    `swap_scans_found_by_type` reads a pin of `event` through aliases of a field, and through no other alias or CTE.
    A scan that the union leaves to that swap must be one that the swap can read, so this copy keeps each CTE name.
    """

    def __init__(self, node: ast.SelectQuery) -> None:
        super().__init__()
        self.node = node
        self._named: dict[tuple[str, float], ast.Expr] = {}

    @cached_property
    def aliases(self) -> dict[str, tuple[int, ast.Expr]]:
        declared: dict[str, tuple[int, ast.Expr]] = {}
        for position, (name, expr) in enumerate(select_aliases(self.node, in_scope_only=True)):
            declared.setdefault(name, (position, expr))
        return declared

    def target(self, expr: ast.Expr) -> ast.Expr:
        """The expression that `expr`, without its own alias, names through a chain of select aliases."""
        expr = unwrap_alias(expr)
        if not (isinstance(expr, ast.Field) and len(expr.chain) == 1):
            return expr
        return self._follow(str(expr.chain[0])) or expr

    def _follow(self, name: str) -> ast.Expr | None:
        """The expression at the end of the chain of select aliases that starts at `name`, or None for no alias."""
        visible: float = math.inf
        hops: list[tuple[str, float]] = []
        named: ast.Expr | None = None
        # Each hop is cached, so a query that reads one long chain many times walks the chain once.
        while (name, visible) not in self._named:
            declared = self.aliases.get(name)
            # The resolver binds a name in an alias's expression only to an alias declared before it. In
            # `event AS event`, the inner `event` is therefore the column.
            if declared is None or declared[0] >= visible:
                break
            hops.append((name, visible))
            visible, aliased = declared
            named = unwrap_alias(aliased)
            if not (isinstance(named, ast.Field) and len(named.chain) == 1):
                break
            name = str(named.chain[0])
        else:
            named = self._named[(name, visible)]
        for hop in hops:
            self._named[hop] = cast(ast.Expr, named)
        return named

    def visit_field(self, node: ast.Field):
        target = self.target(node)
        return super().visit_field(target if isinstance(target, ast.Field) else node)

    def visit_alias(self, node: ast.Alias):
        # `swap_scans_found_by_type` reads through an alias of a field, but it does not read a comparison inside an
        # alias.
        inner = unwrap_alias(node)
        if isinstance(inner, ast.Field):
            return self.visit(inner)
        return super().visit_alias(node)

    def _keep(self, node):
        # A subquery has its own aliases, and a lambda has its own arguments. No rule here reads a comparison inside
        # either one.
        return node

    visit_select_query = visit_select_set_query = visit_lambda = _keep


@frozen
class _WithValue:
    value: ast.Expr
    # How many values a comparison with `value` reads, and the `$feature_flag_called` constants among them.
    count: int
    literals: list[ast.Constant]


class _WithValues:
    """The value that each column CTE, `WITH <expr> AS name`, gives a read of its name, cached by CTE.

    A CTE is in scope in every subquery under its WITH, so the finder of each scan reads the cached count and literals
    of a CTE's list instead of its items."""

    def __init__(self) -> None:
        self._by_cte: dict[int, _WithValue] = {}
        self._by_value: dict[int, _WithValue] = {}
        # Whether a column CTE in scope can name `$feature_flag_called`. The renamer sets it for each SELECT from the
        # SELECT's own WITH, so a CTE body also counts the later CTEs of its WITH.
        self.cte_in_scope_names_flag_calls = False

    def of(self, cte: ast.CTE) -> ast.Expr:
        return self._entry(cte).value

    def read(self, value: ast.Expr) -> _WithValue | None:
        """The cached reading of `value` when `of` returned it, or None for any other expression."""
        return self._by_value.get(id(value))

    def any_name_flag_calls(self, ctes: Mapping[str, ast.CTE]) -> bool:
        return any(cte.cte_type == "column" and bool(self._entry(cte).literals) for cte in ctes.values())

    def _entry(self, cte: ast.CTE) -> _WithValue:
        entry = self._by_cte.get(id(cte))
        if entry is None:
            value = unwrap_alias(cte.expr)
            items = [
                unwrap_alias(item) for item in (value.exprs if isinstance(value, (ast.Tuple, ast.Array)) else [value])
            ]
            if not all(isinstance(item, ast.Constant) for item in items):
                value = _MAY_NAME_FLAG_CALLS
                items = [value]
            # Every item is a constant, so a read of an item does not depend on the scope that reads it.
            literals = [item for item in items if isinstance(item, ast.Constant) and item.value == FLAG_CALLED_EVENT]
            entry = self._by_cte[id(cte)] = self._by_value[id(value)] = _WithValue(
                value=value, count=len(items), literals=literals
            )
        return entry


class _ScanReadCopier(CloningVisitor):
    """Copies an expression that reads only one union scan, with each read as its chain on the scan."""

    def __init__(self, union: EventsWithFlagCallsTable) -> None:
        super().__init__(clear_types=True, clear_locations=True)
        self.union = union
        self.failed = False

    def visit_field(self, node: ast.Field):
        read = _union_chain(node.type)
        if read is None or read[0] is not self.union:
            self.failed = True
            return super().visit_field(node)
        return ast.Field(chain=read[1])

    def visit_alias(self, node: ast.Alias):
        # A hidden alias wraps an expression field, such as `person_id`, that the resolver expanded in place.
        if not node.hidden:
            self.failed = True
        return self.visit(node.expr)

    def visit_call(self, node: ast.Call):
        # Each branch would call the function again and filter on a different value.
        if is_nondeterministic_function(node.name):
            self.failed = True
        return super().visit_call(node)

    def _refuse(self, node):
        self.failed = True
        return node

    visit_select_query = visit_select_set_query = visit_lambda = _refuse


class _EventAsFlagCall(CloningVisitor):
    def visit_field(self, node: ast.Field):
        if node.chain == ["event"]:
            return ast.Constant(value=FLAG_CALLED_EVENT)
        return super().visit_field(node)


class _StepTests(CloningVisitor):
    """Reads each funnel step test such as `if(c, 1, 0) = 1` as `c`, to find the keys a predicate pins.

    The copy is not a filter: for a NULL `c` the test is false, and `c` is NULL.
    """

    def visit_compare_operation(self, node: ast.CompareOperation):
        condition = _step_condition(node)
        return self.visit(condition) if condition is not None else super().visit_compare_operation(node)

    def visit_call(self, node: ast.Call):
        condition = _step_condition(node)
        return self.visit(condition) if condition is not None else super().visit_call(node)


class _Qualified(CloningVisitor):
    def __init__(self, table: str) -> None:
        super().__init__()
        self.table = table

    def visit_field(self, node: ast.Field):
        return ast.Field(chain=[self.table, *node.chain])


class _FlagEvaluationsReads(CloningVisitor):
    def __init__(self, columns: FlagEvaluationsColumns, context: HogQLContext) -> None:
        super().__init__()
        self.columns = columns
        self.context = context
        self.failed = False

    def copy(self, expr: ast.Expr) -> ast.Expr | None:
        copied = self.visit(expr)
        return None if self.failed else copied

    def visit_field(self, node: ast.Field):
        chain = self.columns.chain(node.chain)
        if chain is None:
            self.failed = True
            return super().visit_field(node)
        return ast.Field(chain=["flag_evaluations", *chain])

    def visit_call(self, node: ast.Call):
        argument = _serialized_argument(node)
        if isinstance(argument, ast.Field):
            read = self.visit_field(argument)
            return serialized_like_events(self.columns.events, argument.chain, read, self.context)
        return super().visit_call(node)


def _serialized_argument(node: ast.Call) -> ast.Expr | None:
    """The argument of a one-argument `toJSONString` call, through any aliases, or None for any other call."""
    if node.name != "toJSONString" or len(node.args) != 1:
        return None
    argument = node.args[0]
    while isinstance(argument, ast.Alias):
        argument = argument.expr
    return argument


def _serializes_select_alias(expr: ast.Expr, aliases: dict[str, ast.Expr]) -> bool:
    finder = _SelectAliasSerializationFinder(aliases)
    finder.visit(expr)
    return finder.found


class _SelectAliasSerializationFinder(SyntaxVisitor):
    """Finds a `toJSONString` call whose argument is a reference to one of `aliases`."""

    def __init__(self, aliases: dict[str, ast.Expr]) -> None:
        super().__init__()
        self.aliases = aliases
        self.found = False

    def visit_call(self, node: ast.Call) -> None:
        argument = _serialized_argument(node)
        if (
            isinstance(argument, ast.Field)
            and isinstance(argument.type, ast.FieldAliasType)
            and argument.type.alias in self.aliases
        ):
            self.found = True
            return
        super().visit_call(node)


class _UnionChainCollector(SyntaxVisitor):
    """Collects the chain each resolved field reads on a union scan, as lazy table resolution will request it."""

    def __init__(self) -> None:
        super().__init__()
        self.chains: list[list[str | int]] = []
        self.unreadable_joins: list[str] = []
        self.exports: dict[tuple[int, str], list[str | int]] = {}
        self._select: ast.SelectQuery | None = None
        self.export_collision: tuple[list[str | int], list[str | int]] | None = None

    def visit_select_query(self, node: ast.SelectQuery) -> None:
        outer = self._select
        self._select = node
        super().visit_select_query(node)
        self._select = outer

    def visit_field(self, node: ast.Field) -> None:
        read = _union_chain(node.type)
        if read is not None:
            chain = read[1]
            self.chains.append(chain)
            if not isinstance(node.type, ast.FieldType):
                # Lazy table resolution names a property read by joining the path with `___`, so `a.b` and `a___b` share a name.
                name = "___".join(str(link) for link in chain)
                first = self.exports.setdefault((id(self._select), name), chain)
                if first != chain and self.export_collision is None:
                    self.export_collision = (first, chain)
            return
        field_type = node.type.field_type if isinstance(node.type, ast.PropertyType) else node.type
        if not isinstance(field_type, ast.FieldType):
            return
        table_type: ast.Type = field_type.table_type
        while isinstance(table_type, ast.VirtualTableType):
            table_type = table_type.table_type
        # A join that starts from the scan, such as `override` or `person`, reads its key from the union.
        while isinstance(table_type, ast.LazyJoinType):
            source = table_type.table_type
            while isinstance(source, ast.TableAliasType):
                source = source.table_type
            if union_table_of(source) is not None:
                lazy_join = table_type.lazy_join
                if isinstance(source, ast.VirtualTableType) or lazy_join.resolver not in _UNION_JOIN_RESOLVERS:
                    self.unreadable_joins.append(table_type.field)
                else:
                    self.chains.extend([list(lazy_join.from_field), *lazy_join.extra_from_fields])
                return
            table_type = table_type.table_type


class _UnionTableFinder(SyntaxVisitor):
    def __init__(self, database: "Database") -> None:
        super().__init__()
        self.database = database
        self.found = False

    def visit_join_expr(self, node: ast.JoinExpr) -> None:
        if isinstance(node.table, ast.Field):
            try:
                # Unlike get_table, a miss here builds no table name suggestions.
                table = self.database.get_table_node([str(part) for part in node.table.chain]).table
            except ResolutionError:
                # A CTE or a subquery alias, which only the resolver can tell apart.
                table = None
            self.found = self.found or isinstance(table, EventsWithFlagCallsTable)
        super().visit_join_expr(node)


class _FlagCallComparisonFinder(SyntaxVisitor):
    """Finds `event = '$feature_flag_called'` or an `IN` list with it, on the scan, in its own query's clauses."""

    def __init__(
        self,
        root: ast.SelectQuery,
        scan: EventsScan,
        aliases: _Aliases,
        ctes: Mapping[str, ast.CTE],
        with_values: _WithValues,
    ) -> None:
        super().__init__()
        self.root = root
        self.reader = scan
        self.aliases = aliases
        self.ctes = ctes
        self.with_values = with_values
        # The names that the enclosing lambdas bind, or None outside a lambda. A lambda argument maps to
        # `_LAMBDA_ARGUMENT`. An alias inside a lambda maps to the expression that it names. Each lambda adds a layer, so
        # entering one copies nothing.
        self.lambda_names: ChainMap[str, ast.Expr] | None = None
        self.values_left = _COMPARED_VALUES_BUDGET
        self.literals: list[ast.Constant] = []
        # A CTE's list can be read by many scans, so each finder keeps the cached value, not a copy of its literals.
        self.with_values_read: dict[int, _WithValue] = {}

    @property
    def names_flag_calls(self) -> bool:
        # Past the budget the finder cannot tell which values it compares with `event`. A query without any
        # `$feature_flag_called` constant cannot compare `event` with one, so only a query with one counts. A column CTE
        # in scope can hold that constant outside the query.
        return bool(self.literals or self.with_values_read) or (
            self.values_left < 0
            and (names_flag_called_event(self.root) or self.with_values.cte_in_scope_names_flag_calls)
        )

    def visit_select_query(self, node: ast.SelectQuery) -> None:
        if node is self.root:
            super().visit_select_query(node)

    def visit_lambda(self, node: ast.Lambda) -> None:
        outer = self.lambda_names
        self.lambda_names = (outer if outer is not None else ChainMap()).new_child(
            dict.fromkeys(node.args, _LAMBDA_ARGUMENT)
        )
        super().visit_lambda(node)
        self.lambda_names = outer

    def visit_alias(self, node: ast.Alias) -> None:
        super().visit_alias(node)
        # Inside a lambda, the resolver binds an alias's name in the lambda's scope when it visits the alias. Later
        # uses of the name in that lambda resolve to the alias's expression, not to a select alias.
        if self.lambda_names is not None:
            # The write goes to this lambda's own layer, so the name stays inside this lambda.
            self.lambda_names[node.alias] = self._resolve(node.expr)

    def visit_select_set_query(self, node: ast.SelectSetQuery) -> None:
        pass

    def visit_compare_operation(self, node: ast.CompareOperation) -> None:
        self._check(node)
        super().visit_compare_operation(node)

    def visit_call(self, node: ast.Call) -> None:
        self._check(node)
        super().visit_call(node)

    def _resolve(self, read: ast.Expr) -> ast.Expr:
        read = unwrap_alias(read)
        names = self.lambda_names
        if names is not None and isinstance(read, ast.Field) and len(read.chain) == 1 and str(read.chain[0]) in names:
            return names[str(read.chain[0])]
        return self._cte_value(self.aliases.target(read))

    def _cte_value(self, expr: ast.Expr) -> ast.Expr:
        """The value of the column CTE that `expr` names, or `expr` when it names none.

        The caller has already read `expr` as a lambda's name and a select alias. The resolver also reads a name as a
        column of any table in FROM before it reads a CTE. This check knows only the events columns, so a column of
        another table that shadows a CTE can send the scan to the union.
        """
        if not (isinstance(expr, ast.Field) and len(expr.chain) == 1):
            return expr
        name = str(expr.chain[0])
        cte = self.ctes.get(name)
        if cte is None or cte.cte_type != "column" or name in _EVENTS_FIELDS:
            return expr
        return self.with_values.of(cte)

    def _check(self, expr: ast.Expr) -> None:
        if self.values_left < 0:
            return
        values = compared_values(expr, lambda read: self.reader.column(self._resolve(read)) == ["event"])
        # An alias of a list can appear many times in one comparison, so each list is read once.
        read_lists: set[int] = set()
        for value in map(self._resolve, values or []):
            with_value = self.with_values.read(value)
            if with_value is not None or isinstance(value, (ast.Tuple, ast.Array)):
                if id(value) in read_lists:
                    continue
                read_lists.add(id(value))
            if with_value is not None:
                self.values_left -= with_value.count
                if self.values_left < 0:
                    return
                if with_value.literals:
                    self.with_values_read[id(with_value)] = with_value
                continue
            for item in value.exprs if isinstance(value, (ast.Tuple, ast.Array)) else [value]:
                self.values_left -= 1
                if self.values_left < 0:
                    return
                named = self._resolve(item)
                if isinstance(named, ast.Constant) and named.value == FLAG_CALLED_EVENT:
                    self.literals.append(named)


class _UnionRenamer(ScanVisitor):
    def __init__(
        self,
        flag_key_compares_as_string: Callable[[], bool],
        only_in_flag_evaluations: bool,
        *,
        rename_flag_only_scans: bool = False,
    ) -> None:
        super().__init__()
        self.flag_key_compares_as_string = flag_key_compares_as_string
        self.only_in_flag_evaluations = only_in_flag_evaluations
        self.rename_flag_only_scans = rename_flag_only_scans
        self.renamed = False
        self.refusals: list[UnionRefusal] = []
        self.with_values = _WithValues()
        self.literal_spans: set[tuple[int, int]] = set()
        self.spanned_with_values: set[int] = set()

    def visit_select_set_query(self, node: ast.SelectSetQuery) -> None:
        initial = node.initial_select_query
        with self._with_scope(initial.ctes if isinstance(initial, ast.SelectQuery) else None):
            super().visit_select_set_query(node)

    def visit_select_query(self, node: ast.SelectQuery) -> None:
        with self._with_scope(node.ctes):
            super().visit_select_query(node)

    @contextmanager
    def _with_scope(self, ctes: Mapping[str, ast.CTE] | None) -> Iterator[None]:
        outer = self.with_values.cte_in_scope_names_flag_calls
        if ctes:
            self.with_values.cte_in_scope_names_flag_calls = outer or self.with_values.any_name_flag_calls(ctes)
        try:
            yield
        finally:
            self.with_values.cte_in_scope_names_flag_calls = outer

    def visit_scan_query(self, node: ast.SelectQuery) -> None:
        aliases = _Aliases(node)
        # Only the first scan can be renamed, and it comes first, so each refusal reads the query as written.
        for found in _flag_call_scans(node, self.flag_key_compares_as_string, self.ctes, aliases, self.with_values):
            position, scan, literals = found.position, found.scan, found.literals
            if position == 0 and self._left_to_the_swap(node, scan, aliases):
                continue
            refusal = _union_refusal(node, scan, position)
            if refusal is not None and found.unchecked:
                refusal = "it compares `event` with more values than the flag-call check reads"
            if refusal is not None:
                self.refusals.append(UnionRefusal(join=scan.join, reason=refusal))
            else:
                point_scan_at(node, scan, list(EVENTS_WITH_FLAG_CALLS_CHAIN))
                # A lazy table cannot be sampled. SAMPLE 1 keeps every row anyway, and the union applies a ratio
                # sample in its branches, where lazy table resolution reads it from this scan.
                if scan.join.sample is not None and scan.join.sample.samples_all_rows():
                    scan.join.sample = None
                self.renamed = True
                self._add_spans(literals)
                for with_value in found.with_values:
                    if id(with_value) not in self.spanned_with_values:
                        self.spanned_with_values.add(id(with_value))
                        self._add_spans(with_value.literals)

    def _add_spans(self, literals: list[ast.Constant]) -> None:
        self.literal_spans.update(
            (literal.start, literal.end)
            for literal in literals
            if literal.start is not None and literal.end is not None
        )

    def _left_to_the_swap(self, node: ast.SelectQuery, scan: EventsScan, aliases: _Aliases) -> bool:
        # The flag_evaluations swap handles a first scan whose `event` filter it reads as only flag calls. It swaps or
        # refuses that scan on mode 2. On mode 1 events holds every flag call, so the union would read the same calls
        # twice there.
        if self.rename_flag_only_scans:
            return False
        # The swap cannot read a sampled scan. On mode 2 the union reads it.
        sampled = scan.join.sample is not None and not scan.join.sample.samples_all_rows()
        conjuncts = filter_conjuncts(node)
        if aliases.aliases:
            conjuncts = [aliases.visit(conjunct) for conjunct in conjuncts]
        return scan.pins_flag_calls(conjuncts, needs_flag_key=False) and not (self.only_in_flag_evaluations and sampled)
