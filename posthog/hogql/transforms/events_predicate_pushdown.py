"""Events predicate pushdown.

Wraps a `FROM events <JOIN…> WHERE p LIMIT n` query's events scan in a pre-filtering subquery so the events table is
read once, filtered and `LIMIT`-bounded, before the joins fan out:

    FROM events <JOIN…> WHERE <p> LIMIT n
    ->
    FROM (SELECT <needed cols> FROM events WHERE <pushable p> LIMIT n) AS events <JOIN…> WHERE <residual p>

It runs *after* logical lowering and *before* the ClickHouse physical passes (see `prepare_ast_for_printing`), so it
operates on the dialect-neutral logical form: property reads are `PropertyAccess`, not yet materialized columns. Two
pieces move events work into the subquery:

1. The pushable predicates (`EventsPredicatePushdownExtractor`) move into the subquery WHERE verbatim — they already
   reference the real events table, so the physical pass optimizes them (materialized columns, skip indexes) in place.
2. Everything the *outer* query still references is handled by `EventsSubexprHoister`: each maximal subexpression that
   depends only on the events table is projected into the subquery and replaced by a reference to that column. The
   physical pass then resolves any `PropertyAccess` / property-group form inside the subquery. Pushdown itself never
   inspects physical columns or special-cases particular functions.

It is a pure optimization: any unexpected error leaves the query untouched (run flat), and every rewrite is
result-equivalent.

Two things are built by hand here, on purpose:

- **The subquery's types.** `_build_subquery` constructs the subquery's `SelectQueryType` directly rather than calling
  `resolve_types`. It has to: `resolve_types` runs before lowering, has no handling for `PropertyAccess`, and clones
  with `clear_types=True` — so re-resolving a subquery that already holds lowered `PropertyAccess` projections would
  wipe their types and break nullability and printing downstream. Teaching the resolver about lowered nodes would cross
  a layering boundary, so the types are assembled here instead.
- **Hoisted-column nullability.** The printer reads a hoisted column's nullability from the subquery's projected column
  type, not as a blanket-nullable subquery column. That is what lets a join key be hoisted like any other column: it
  wraps in `ifNull(...)` only when the value is genuinely nullable.
"""

from typing import TYPE_CHECKING, cast

import structlog

from posthog.hogql import ast
from posthog.hogql.base import _T_AST
from posthog.hogql.constants import LimitContext, get_max_limit_for_context
from posthog.hogql.context import HogQLContext
from posthog.hogql.database.models import DatabaseField
from posthog.hogql.database.schema.events import EventsTable
from posthog.hogql.database.schema.util.where_clause_extractor import EventsPredicatePushdownExtractor
from posthog.hogql.functions.mapping import find_hogql_aggregation
from posthog.hogql.visitor import CloningVisitor, TraversingVisitor, clone_expr

from posthog.settings import TEST

if TYPE_CHECKING:
    from posthog.schema import HogQLQueryModifiers

logger = structlog.get_logger(__name__)


def events_pushdown_enabled(modifiers: "HogQLQueryModifiers") -> bool:
    """Enabled when explicitly on, or unset under TEST. Shared by the call site and the transform."""
    return bool(modifiers.pushDownPredicates or (modifiers.pushDownPredicates is None and TEST))


def _printer_top_level_select_ids(node: _T_AST) -> set[int]:
    """Selects the printer will inject a top-level LIMIT into: the root, or the direct SelectQuery branches of
    the outermost union. Nested-union branches are excluded; they'd get an inner LIMIT with no outer cap."""
    if isinstance(node, ast.SelectQuery):
        return {id(node)}
    if isinstance(node, ast.SelectSetQuery):
        return {id(branch) for branch in node.select_queries() if isinstance(branch, ast.SelectQuery)}
    return set()


def apply_events_predicate_pushdown(
    node: _T_AST,
    context: HogQLContext,
) -> _T_AST:
    """Apply predicate pushdown to eligible `FROM events … JOIN …` queries. Mutates the AST in place; returns it."""
    top_level_select_ids = _printer_top_level_select_ids(node)
    EventsPredicatePushdownTransform(context=context, top_level_select_ids=top_level_select_ids).visit(node)
    return node


class SelectAliasInliner(CloningVisitor):
    """Inlines SELECT-alias references in a pushed predicate so the full aliased expression is carried into the
    subquery, not the bare name (which would re-bind to the raw column and drop the wrapper)."""

    def __init__(self, select_aliases: dict[str, ast.Expr]):
        super().__init__(clear_types=False)
        self.select_aliases = select_aliases
        self._resolving: set[str] = set()

    def visit_field(self, node: ast.Field):
        alias = node.type.alias if isinstance(node.type, ast.FieldAliasType) else None
        if alias is not None and alias in self.select_aliases and alias not in self._resolving:
            self._resolving.add(alias)
            try:
                return self.visit(clone_expr(self.select_aliases[alias], clear_types=False))
            finally:
                self._resolving.discard(alias)
        return super().visit_field(node)


class _StructuralNormalizer(CloningVisitor):
    """Builds the hoister's structural-identity clone of an events-only expression: type- and location-stripped,
    with every events column leaf rewritten to its resolved database column name. After lowering, two reads off
    different blobs can carry the same chain (`properties` vs poe's `person_properties`, where the blob identity
    lives only in the type), so the chain alone would wrongly identify them; the database name disambiguates.
    Sets `failed` for an unresolvable column so the caller declines."""

    def __init__(self, hoister: "EventsSubexprHoister"):
        super().__init__(clear_types=True, clear_locations=True)
        self.hoister = hoister
        self.failed = False

    def visit_field(self, node: ast.Field) -> ast.Field:
        if self.hoister._is_target_field(node.type):
            assert isinstance(node.type, ast.FieldType)
            name = self.hoister._database_column_name(node.type)
            if name is None:
                self.failed = True
            return ast.Field(chain=[name or ""])
        return cast(ast.Field, super().visit_field(node))


class _EventsOnlyScan(TraversingVisitor):
    """Classifies the leaf references in an expression so the hoister can decide whether the whole subtree depends
    only on the target events table. Counts target-table vs foreign field references (a lazy-join or any other
    non-events ref is simply foreign) and flags nested subqueries."""

    def __init__(self, hoister: "EventsSubexprHoister"):
        super().__init__()
        self.hoister = hoister
        self.target_refs = 0
        self.foreign_refs = 0
        self.has_subquery = False

    def visit_field(self, node: ast.Field) -> None:
        super().visit_field(node)
        if self.hoister._is_target_field(node.type):
            self.target_refs += 1
        else:
            self.foreign_refs += 1

    def visit_select_query(self, node: ast.SelectQuery) -> None:
        self.has_subquery = True

    def visit_select_set_query(self, node: ast.SelectSetQuery) -> None:
        self.has_subquery = True


class EventsSubexprHoister(CloningVisitor):
    """Rewrites an events query's outer expressions so the work that depends only on the events table moves into the
    pre-filtering subquery.

    For each *maximal* subexpression that references only the target events table (its columns and property reads)
    plus constants — a property value read, `JSONHas(properties, k)`, `match(uuid, …)`, `upper(properties.x)`, … — the
    whole subexpression is projected into the subquery under a stable name and the outer occurrence becomes a
    reference to that column. The ClickHouse physical pass, running afterwards, resolves any `PropertyAccess` /
    property-group form *inside the subquery*; pushdown itself never inspects physical columns, mimics the events
    schema, or special-cases particular functions — `JSONHas` is just one events-only expression among many.

    A hoisted reference carries the projected column's real nullability (see the module docstring), so a non-nullable
    value stays unwrapped and can serve as a join key, while a nullable property key still wraps correctly.

    Sets `blocked` if a referenced leaf is an unresolvable column, so the caller declines."""

    def __init__(
        self,
        target_table: ast.TableType | ast.TableAliasType,
        subquery_ref: ast.SelectQueryAliasType,
        context: HogQLContext,
    ):
        super().__init__(clear_types=False)
        self.target_table = target_table
        self.subquery_ref = subquery_ref
        # Pushdown always builds the ref over a SelectQueryType (never a set query); narrow it for column bookkeeping.
        assert isinstance(subquery_ref.select_query_type, ast.SelectQueryType)
        self.subquery_type = subquery_ref.select_query_type
        self.context = context
        self.projections: dict[str, ast.Expr] = {}
        self.column_types: dict[str, ast.Type] = {}
        self.blocked = False
        self._counter = 0
        self._structures: dict[str, ast.Expr] = {}

    def visit(self, node: ast.AST | None) -> ast.AST:
        # Aliases are transparent: recurse so the inner subexpression is hoisted while the alias — and the output
        # name it carries — stays in the outer query.
        if not isinstance(node, ast.Expr) or isinstance(node, ast.Alias):
            return super().visit(node)

        # The maximal events-only subexpression — a direct column, a property read, or an events-only join key — is
        # projected whole into the subquery and read back as one column. A join key needs no special handling; its
        # nullability rides the projected column's type.
        if self._is_hoistable(node):
            name = self._intern(node)
            if name is not None:
                return ast.Field(chain=[name], type=ast.FieldType(name=name, table_type=self.subquery_ref))

        return super().visit(node)

    def visit_alias(self, node: ast.Alias) -> ast.Alias:
        # The resolver wraps a bare column reference in an alias whose `FieldAliasType` carries the events column's
        # `FieldType` again. Hoisting only the inner expression would leave that wrapper stale, and downstream
        # consumers that resolve through it (`resolve_field_type`) would treat the outer reference as still reading
        # the real events table. Re-point the wrapper at the rewritten expression's type (mirrors lowering's
        # `visit_alias`).
        new_node = cast(ast.Alias, super().visit_alias(node))
        unwrapped: ast.Type | None = new_node.type
        while isinstance(unwrapped, ast.FieldAliasType):
            unwrapped = unwrapped.type
        if (
            isinstance(new_node.type, ast.FieldAliasType)
            and self._is_target_field(unwrapped)
            and new_node.expr.type is not None
        ):
            new_node.type = ast.FieldAliasType(alias=new_node.type.alias, type=new_node.expr.type)
        return new_node

    def visit_select_query(self, node: ast.SelectQuery) -> ast.SelectQuery:
        # A nested subquery is its own scope: its events references resolve against its own FROM (even when that is
        # the same events table), so rewriting them to read the outer pre-filtering subquery would cross scopes.
        return cast(ast.SelectQuery, clone_expr(node, clear_types=False))

    def visit_select_set_query(self, node: ast.SelectSetQuery) -> ast.SelectSetQuery:
        return cast(ast.SelectSetQuery, clone_expr(node, clear_types=False))

    def _intern(self, expr: ast.Expr) -> str | None:
        """Record a subquery projection for `expr` and return the column name to reference it by. Structurally
        identical reads share one projection. The preferred name is *not* injective — `properties.a[1]` (array index)
        and `properties.a['1']` (object key) both prefer `properties__a__1`, and `properties.a.b` collides with
        `properties['a__b']` — so a structurally different read whose preferred name is already taken gets a fresh
        synthetic column instead; collapsing the two would silently return the first read's value for the second.
        Returns None (setting `blocked`) for an unresolvable column."""
        # Structural identity compares normalized type-stripped clones (type objects can be cyclic — table types
        # embed query types — so comparing nodes with types attached is unsafe; see `_StructuralNormalizer` for the
        # column-name normalization that disambiguates reads off different blobs).
        normalizer = _StructuralNormalizer(self)
        structure = cast(ast.Expr, normalizer.visit(expr))
        if normalizer.failed:
            self.blocked = True
            return None
        for existing_name, existing_structure in self._structures.items():
            if existing_structure == structure:
                return existing_name
        name = self._preferred_name(expr)
        if name is None:
            self.blocked = True
            return None
        if name in self.projections:
            name = self._synthetic_name()
        value_type: ast.Type = expr.type or ast.UnknownType()
        self.projections[name] = clone_expr(expr, clear_types=False)
        self._structures[name] = structure
        self.column_types[name] = value_type
        self.subquery_type.columns[name] = value_type
        return name

    def _preferred_name(self, node: ast.Expr) -> str | None:
        # A property read's name is its source blob column joined with its key path, so `properties.x` and the person
        # blob's `person_properties.x` hoist to separate columns instead of colliding on the bare key `x` (which would
        # read the wrong blob for one of them). A direct column uses its database name; any other events-only
        # subexpression a synthetic internal name (its outer output name rides its alias).
        if isinstance(node, ast.PropertyAccess):
            blob = self._database_column_name(node.expr.type) if isinstance(node.expr.type, ast.FieldType) else None
            if blob is None:
                return None
            return "__".join([blob, *(str(key) for key in node.keys)])
        if isinstance(node, ast.Field) and isinstance(node.type, ast.FieldType):
            return self._database_column_name(node.type)
        return self._synthetic_name()

    def _synthetic_name(self) -> str:
        name = f"__pd_expr_{self._counter}"
        self._counter += 1
        return name

    def _is_target_field(self, node_type: ast.Type | None) -> bool:
        return isinstance(node_type, ast.FieldType) and self._matches_target_table(node_type.table_type)

    def _is_hoistable(self, node: ast.Expr) -> bool:
        """True if `node` depends only on the target events table (its columns / property reads) plus constants — no
        joined-table, lazy, or other foreign reference and no nested subquery — and touches the target at least once
        (so we never project a pure constant)."""
        scan = _EventsOnlyScan(self)
        scan.visit(node)
        return scan.target_refs > 0 and scan.foreign_refs == 0 and not scan.has_subquery

    def _database_column_name(self, field_type: ast.FieldType) -> str | None:
        try:
            resolved = field_type.resolve_database_field(self.context)
            if isinstance(resolved, DatabaseField):
                return resolved.name
            return None
        except Exception as err:
            # Fail-safe: an unresolvable column blocks pushdown rather than risking a wrong subquery; debug-logged so
            # a resolver regression silently disabling pushdown stays visible.
            logger.debug("events_predicate_pushdown_field_resolution_failed", error=str(err))
            return None

    def _matches_target_table(self, table_type: ast.Type | None) -> bool:
        # Match the specific FROM table, not the EventsTable schema object: a self-join (`events a JOIN events b`)
        # shares one schema object across both sides, so rewriting by object identity would collapse `b`'s columns
        # onto the subquery too. Discriminate by alias (object identity is unreliable — the pipeline's CloningVisitors
        # may have re-instantiated the types since the FROM was captured). Only POE virtual layers are peeled.
        unwrapped: ast.Type | None = table_type
        while isinstance(unwrapped, ast.VirtualTableType):
            unwrapped = unwrapped.table_type

        target = self.target_table
        if isinstance(target, ast.TableAliasType):
            return (
                isinstance(unwrapped, ast.TableAliasType)
                and unwrapped.alias == target.alias
                and isinstance(unwrapped.table_type, ast.TableType)
                and isinstance(target.table_type, ast.TableType)
                and unwrapped.table_type.table is target.table_type.table
            )
        # Unaliased FROM: match the bare events TableType only, never a column reached through some join alias.
        return isinstance(unwrapped, ast.TableType) and unwrapped.table is target.table


class _ShortCircuitBlockerFinder(TraversingVisitor):
    """Finds aggregate or window functions, which consume the whole result before a LIMIT applies. Does not
    recurse into subqueries: only this query level's own expressions matter for its own LIMIT."""

    def __init__(self):
        super().__init__()
        self.found = False

    def visit(self, node):
        if not self.found:
            super().visit(node)

    def visit_select_query(self, node: ast.SelectQuery):
        pass

    def visit_window_function(self, node: ast.WindowFunction):
        self.found = True

    def visit_call(self, node: ast.Call):
        if find_hogql_aggregation(node.name):
            self.found = True
        else:
            super().visit_call(node)


class EventsPredicatePushdownTransform(TraversingVisitor):
    """Pushes events WHERE/PREWHERE predicates into a pre-filtering subquery:
    `FROM events` -> `FROM (SELECT <needed cols> FROM events WHERE <predicates>) AS events`.

    Runs after logical lowering (so property reads are PropertyAccess) and before the ClickHouse physical passes,
    applying bottom-up so nested `FROM events` subqueries benefit too."""

    # Join types across which moving an events PREDICATE is result-safe (they preserve the events/left side). This is
    # broader than the all-rows-preserved check (`_all_joins_preserve_every_row`, LEFT only): INNER / CROSS are
    # predicate-safe but can drop an events row, so they pass here yet are rejected when deciding whether to also push
    # the LIMIT (`_safe_inner_limit`).
    _SAFE_JOIN_TYPES = {"JOIN", "INNER JOIN", "LEFT JOIN", "LEFT OUTER JOIN", "CROSS JOIN"}

    def __init__(
        self,
        context: HogQLContext,
        top_level_select_ids: set[int] | None = None,
    ):
        super().__init__()
        self.context = context
        self.top_level_select_ids = top_level_select_ids or set()

    def visit_select_query(self, node: ast.SelectQuery):
        super().visit_select_query(node)  # bottom-up: visit subqueries first

        if self._should_apply_pushdown(node):
            try:
                decline_reason = self._apply_pushdown(node)
            except Exception as err:
                # Pure optimization: any unexpected failure must leave the query untouched, not break it.
                # _apply_pushdown mutates node only after every check passes, so a raise leaves it unchanged.
                logger.warning("events_predicate_pushdown_unexpected_error", error=str(err), exc_info=True)
                return
            if decline_reason is not None:
                logger.debug("events_predicate_pushdown_declined", reason=decline_reason)

    def _apply_pushdown(self, node: ast.SelectQuery) -> str | None:
        """Apply predicate pushdown to an eligible query. Returns a decline reason, or None if applied."""
        assert node.select_from is not None

        # The hoister rewrites events references in the select list, residual predicates, HAVING/QUALIFY, and join
        # constraints — but the printer also prints column-CTE bodies and WINDOW clauses. An events reference there
        # would survive un-rewritten and point at a column the pre-filtering subquery doesn't project (ClickHouse:
        # unknown identifier), so decline those shapes outright.
        if node.ctes:
            return "has_ctes"
        if node.window_exprs:
            return "has_window_exprs"

        joined_aliases = self._collect_joined_aliases(node)
        if not joined_aliases:
            return "no_safe_joined_aliases"

        events_table_type = node.select_from.type
        if not isinstance(events_table_type, (ast.TableType, ast.TableAliasType)):
            return "from_not_table_type"

        # Classify a WHERE field that resolves to an alias by what the alias references (e.g. `f(session.x) AS
        # event` must not be pushed by name).
        select_aliases = {expr.alias: expr.expr for expr in node.select if isinstance(expr, ast.Alias)}

        # Split without mutating node yet, so any bail below leaves the original predicates intact.
        extractor = EventsPredicatePushdownExtractor(
            joined_table_aliases=joined_aliases,
            events_table_type=events_table_type,
            select_aliases=select_aliases,
        )

        inner_from_where: ast.Expr | None = None
        inner_from_prewhere: ast.Expr | None = None
        new_where = node.where
        new_prewhere = node.prewhere

        if node.where is not None:
            inner_from_where, new_where = extractor.get_pushdown_predicates(node.where)
        if node.prewhere is not None:
            inner_from_prewhere, new_prewhere = extractor.get_pushdown_predicates(node.prewhere)

        # PREWHERE is valid only on a physical scan, not a subquery. A fully-pushable PREWHERE moves into the
        # inner scan; a residual one would have to stay on the outer subquery (invalid), so bail.
        if new_prewhere is not None:
            return "prewhere_not_fully_pushable"

        if inner_from_where is None and inner_from_prewhere is None:
            return "no_pushable_predicates"

        inner_where = self._prepare_inner_predicate(inner_from_where, select_aliases)
        inner_prewhere = self._prepare_inner_predicate(inner_from_prewhere, select_aliases)

        # The optimization only pays off when a LIMIT can short-circuit the events read. Predicates + an inner
        # LIMIT beat the flat query for every column type; predicates-only regresses for the raw blob, and
        # ORDER BY blocks the inner LIMIT. So push the inner LIMIT when result-equivalent, else decline.
        inner_limit = self._safe_inner_limit(node, new_where, new_prewhere)
        if inner_limit is None:
            return "no_short_circuitable_limit"

        # Hoist the events leaves the outer query still references into the pre-filtering subquery, rewriting each
        # outer reference to read the subquery column. Build the subquery's type/ref first so the rewritten
        # references can point at it; nothing on `node` is mutated until every check below passes.
        new_alias = node.select_from.alias or "events"
        subquery_type = ast.SelectQueryType(columns={}, tables={new_alias: events_table_type})
        subquery_ref = ast.SelectQueryAliasType(alias=new_alias, select_query_type=subquery_type)
        hoister = EventsSubexprHoister(events_table_type, subquery_ref, self.context)

        new_select = [cast(ast.Expr, hoister.visit(column)) for column in node.select]
        new_where = cast(ast.Expr, hoister.visit(new_where)) if new_where is not None else None
        new_having = cast(ast.Expr, hoister.visit(node.having)) if node.having is not None else None
        new_qualify = cast(ast.Expr, hoister.visit(node.qualify)) if node.qualify is not None else None
        rewritten_join_constraints: list[tuple[ast.JoinExpr, ast.Expr]] = []
        join = node.select_from.next_join
        while join is not None:
            if join.constraint is not None and join.constraint.expr is not None:
                rewritten_join_constraints.append((join, cast(ast.Expr, hoister.visit(join.constraint.expr))))
            join = join.next_join

        if hoister.blocked:
            return "non_direct_outer_reference"
        if not hoister.projections:
            return "no_collectable_columns"

        events_subquery = self._build_subquery(
            hoister, events_table_type, inner_where, inner_prewhere, alias=node.select_from.alias, limit=inner_limit
        )
        if events_subquery is None:
            return "subquery_build_failed"

        # Commit: install the rewritten outer expressions and swap the events table for the subquery.
        node.select = new_select
        node.where = new_where
        node.having = new_having
        node.qualify = new_qualify
        for join_expr, rewritten in rewritten_join_constraints:
            assert join_expr.constraint is not None
            join_expr.constraint.expr = rewritten
        node.prewhere = new_prewhere
        node.select_from.table = events_subquery
        node.select_from.alias = new_alias
        node.select_from.type = subquery_ref
        return None

    def _should_apply_pushdown(self, node: ast.SelectQuery) -> bool:
        """Eligible when the query selects FROM events directly (no SAMPLE), has a WHERE/PREWHERE, has joins,
        has an effective LIMIT, and does not aggregate / DISTINCT / window (those read the whole set regardless
        of the LIMIT, so the pre-filter would be pure overhead)."""
        return (
            events_pushdown_enabled(self.context.modifiers)
            and node.select_from is not None
            and node.select_from.sample is None
            and self._from_is_events_table(node.select_from)
            and (node.where is not None or node.prewhere is not None)
            and node.select_from.next_join is not None
            and self._has_effective_limit(node)
            and not self._forces_full_event_read(node)
        )

    def _has_effective_limit(self, node: ast.SelectQuery) -> bool:
        """A top-level select counts (the printer injects a cap <= MAX_SELECT_RETURNED_ROWS); a nested select
        counts only with an explicit LIMIT. Contexts that disable the cap (limit_top_select=False) decline."""
        if not self.context.limit_top_select:
            return False
        return id(node) in self.top_level_select_ids or node.limit is not None

    def _forces_full_event_read(self, node: ast.SelectQuery) -> bool:
        """True if the query consumes the whole filtered event set before its LIMIT applies. GROUP BY, DISTINCT,
        and aggregate / window functions (incl. in ORDER BY / HAVING / QUALIFY) block the short-circuit; a plain
        `ORDER BY <column>` does not."""
        if node.group_by or node.distinct:
            return True
        finder = _ShortCircuitBlockerFinder()
        for expr in (*node.select, node.having, node.qualify, *(node.order_by or [])):
            if expr is not None:
                finder.visit(expr)
        return finder.found

    def _all_joins_preserve_every_row(self, node: ast.SelectQuery) -> bool:
        """True if every events row yields >= 1 output row (all joins LEFT [OUTER]); an INNER / CROSS join could drop one."""
        join = node.select_from.next_join if node.select_from is not None else None
        while join is not None:
            if join.join_type not in ("LEFT JOIN", "LEFT OUTER JOIN"):
                return False
            join = join.next_join
        return True

    def _safe_inner_limit(
        self, node: ast.SelectQuery, residual_where: ast.Expr | None, residual_prewhere: ast.Expr | None
    ) -> ast.Constant | None:
        """The LIMIT to push into the events subquery, or None if pushing it would change results.

        Safe only when nothing after the events scan can drop or reorder rows: no ORDER BY / LIMIT BY / ARRAY
        JOIN / WITH TIES / percent, no residual outer predicate, all joins LEFT. Then the first `offset + limit`
        events cover the outer slice. The pushed value is the explicit LIMIT capped at (or, when absent,
        replaced by) the context cap the printer applies to a top-level select, so the inner scan never reads
        rows the capped outer slice can't emit.
        """
        if (
            node.order_by is not None
            or node.limit_by is not None
            or node.array_join_list is not None
            or node.limit_with_ties
            or node.limit_percent
            # A non-aggregate HAVING / QUALIFY drops rows after the join, exactly like a residual predicate: the
            # first `offset + limit` events no longer cover the outer slice, so a pushed LIMIT could under-produce.
            or node.having is not None
            or node.qualify is not None
        ):
            return None
        if residual_where is not None or residual_prewhere is not None:
            return None
        if not self._all_joins_preserve_every_row(node):
            return None
        offset = 0
        if node.offset is not None:
            if not isinstance(node.offset, ast.Constant) or not isinstance(node.offset.value, int):
                return None
            offset = node.offset.value
        # Derive the cap from limit_context (not a hardcoded MAX_SELECT_RETURNED_ROWS) so larger-cap contexts
        # (EXPORT / HEATMAPS / RETENTION) aren't under-capped, which would drop rows.
        cap = (
            get_max_limit_for_context(self.context.limit_context or LimitContext.QUERY)
            if self._is_top_level(node)
            else None
        )
        if isinstance(node.limit, ast.Constant) and isinstance(node.limit.value, int):
            limit_value = min(node.limit.value, cap) if cap is not None else node.limit.value
            return ast.Constant(value=limit_value + offset)
        # No explicit LIMIT: only a top-level select is safe (the printer injects its cap as the outer LIMIT).
        if cap is not None:
            return ast.Constant(value=cap + offset)
        return None

    def _is_top_level(self, node: ast.SelectQuery) -> bool:
        return id(node) in self.top_level_select_ids

    def _from_is_events_table(self, join_expr: ast.JoinExpr) -> bool:
        """True when the FROM resolves directly to the physical events table (not a subquery). Checking the
        resolved type also matches the qualified `FROM posthog.events`, which a chain comparison misses."""
        table_type: ast.Type | None = join_expr.type
        while isinstance(table_type, (ast.TableAliasType, ast.VirtualTableType)):
            table_type = table_type.table_type
        return isinstance(table_type, ast.TableType) and isinstance(table_type.table, EventsTable)

    def _collect_joined_aliases(self, node: ast.SelectQuery) -> set[str]:
        """Aliases from the JOIN chain, or an empty set if any join uses an unsafe type (causing the caller to bail)."""
        aliases: set[str] = set()
        join = node.select_from.next_join if node.select_from else None
        while join is not None:
            # A missing join_type is unreachable today but treated as unsafe rather than safe.
            if join.join_type is None or join.join_type not in self._SAFE_JOIN_TYPES:
                return set()
            if join.alias:
                aliases.add(join.alias)
            join = join.next_join
        return aliases

    def _prepare_inner_predicate(self, expr: ast.Expr | None, select_aliases: dict[str, ast.Expr]) -> ast.Expr | None:
        """Ready a pushed predicate for the inner subquery (inline SELECT-alias refs, clone), or None if there is none."""
        if expr is None:
            return None
        expr = SelectAliasInliner(select_aliases).visit(expr)
        return clone_expr(expr)

    def _build_subquery(
        self,
        hoister: EventsSubexprHoister,
        events_table_type: ast.TableType | ast.TableAliasType,
        where_clause: ast.Expr | None,
        prewhere_clause: ast.Expr | None,
        alias: str | None,
        limit: ast.Constant | None,
    ) -> ast.SelectQuery | None:
        """Build `SELECT <hoisted projections> FROM events WHERE <pushed predicates> LIMIT n`.

        The hoisted projections and the pushed predicates already reference the original events table type, so the
        subquery reuses it directly as its FROM — no schema mimicry, no synthetic materialized columns. The ClickHouse
        physical pass rewrites the `PropertyAccess` projections to their materialized columns afterwards."""
        base_table_type: ast.Type = events_table_type
        if isinstance(base_table_type, ast.TableAliasType):
            base_table_type = base_table_type.table_type
        if not isinstance(base_table_type, ast.TableType):
            return None

        events_field = ast.Field(chain=[base_table_type.table.to_printed_hogql()], type=base_table_type)
        select_from = ast.JoinExpr(table=events_field, alias=alias, type=events_table_type)

        select_fields: list[ast.Expr] = [
            ast.Alias(
                alias=name,
                expr=hoister.projections[name],
                type=ast.FieldAliasType(alias=name, type=hoister.column_types[name]),
            )
            for name in sorted(hoister.projections)
        ]

        return ast.SelectQuery(
            select=select_fields,
            select_from=select_from,
            where=where_clause,
            prewhere=prewhere_clause,
            limit=limit,
            type=hoister.subquery_type,
        )
