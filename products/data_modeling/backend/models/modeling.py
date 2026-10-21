import time
from typing import ClassVar

from django.db import models

from prometheus_client import Counter, Histogram

from posthog.hogql import ast
from posthog.hogql.constants import HogQLDialect
from posthog.hogql.context import HogQLContext
from posthog.hogql.database.database import Database
from posthog.hogql.database.models import SavedQuery
from posthog.hogql.errors import QueryError
from posthog.hogql.parser import parse_select
from posthog.hogql.resolver import Resolver, ResolverFactory
from posthog.hogql.visitor import TraversingVisitor

from posthog.models.team import Team

from products.data_modeling.backend.facade.system_tables import DATA_MODELING_ALLOWED_SYSTEM_TABLES

LabelPath = list[str]


DEFAULT_RESOLUTION_MAX_VIEW_DEPTH = 100
DEFAULT_RESOLUTION_DEADLINE_SECONDS = 60.0


class BoundedResolverError(QueryError):
    """Base class for bounded HogQL view-dependency resolution failures.

    Inherits from QueryError so callers that catch the public HogQL exception
    hierarchy (DRF handlers, workflow error mappers) keep treating cycle/depth/
    timeout failures as user-facing 4xx errors rather than 500s. `initial_view`
    names the saved query whose resolution was in progress when the failure
    occurred — set by the resolver so callers can attribute and log the failure
    without having to plumb context through themselves.
    """

    status_label: ClassVar[str] = "error"

    def __init__(self, message: str, initial_view: str | None = None):
        super().__init__(message)
        self.initial_view = initial_view


class ResolutionCycleError(BoundedResolverError):
    """A view references itself through other views.

    `view_name` is the inner view at which the cycle was detected (the one
    already on the resolution stack). `initial_view` is the saved query the
    caller asked to resolve.
    """

    status_label: ClassVar[str] = "cycle"

    def __init__(self, view_name: str, initial_view: str | None = None):
        message = f"Circular dependency detected in view '{view_name}'"
        if initial_view and initial_view != view_name:
            message += f" while resolving '{initial_view}'"
        super().__init__(message, initial_view=initial_view)
        self.view_name = view_name


class ResolutionDepthExceededError(BoundedResolverError):
    """View resolution would exceed the configured nesting depth."""

    status_label: ClassVar[str] = "depth_exceeded"

    def __init__(self, depth: int, max_depth: int, initial_view: str | None = None):
        message = f"View resolution depth {depth} exceeded max {max_depth}"
        if initial_view:
            message += f" while resolving '{initial_view}'"
        super().__init__(message, initial_view=initial_view)
        self.depth = depth
        self.max_depth = max_depth


class ResolutionTimeoutError(BoundedResolverError):
    """View resolution exceeded its wall-clock deadline."""

    status_label: ClassVar[str] = "timeout"

    def __init__(self, elapsed_seconds: float, deadline_seconds: float, initial_view: str | None = None):
        message = f"View resolution exceeded deadline ({elapsed_seconds:.2f}s > {deadline_seconds:.2f}s)"
        if initial_view:
            message += f" while resolving '{initial_view}'"
        super().__init__(message, initial_view=initial_view)
        self.elapsed_seconds = elapsed_seconds
        self.deadline_seconds = deadline_seconds


# `source` separates the two jobs the resolver does, which fail differently and are read
# differently: a `materialization` failure fails a customer's model on a scheduled run, while
# `lineage` resolves a query's parents at save time to maintain DAG edges and view metadata.
# Lineage runs orders of magnitude more often, so unlabelled they share one series and the
# rarer, costlier one becomes unreadable. Anything under `other` is a caller added without
# saying which of the two it is.
RESOLUTION_SOURCE_MATERIALIZATION = "materialization"
RESOLUTION_SOURCE_LINEAGE = "lineage"
RESOLUTION_SOURCE_OTHER = "other"

DAG_RESOLUTION_TOTAL = Counter(
    "data_modeling_dag_resolution_total",
    "Total HogQL view-dependency resolutions performed, by calling path and terminal status.",
    labelnames=["source", "status"],  # ok | cycle | depth_exceeded | timeout | error
)
DAG_RESOLUTION_DURATION_SECONDS = Histogram(
    "data_modeling_dag_resolution_duration_seconds",
    "Wall-clock time spent resolving HogQL view dependencies, by calling path.",
    labelnames=["source"],
    buckets=(0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0, 30.0),
)
DAG_RESOLUTION_VIEW_DEPTH = Histogram(
    "data_modeling_dag_resolution_view_depth",
    "Maximum nested view depth observed on successful HogQL dependency resolution, by calling path.",
    labelnames=["source"],
    buckets=(1, 2, 4, 8, 16, 25, 50, 100),
)
DAG_RESOLUTION_DEADLINE_VIOLATIONS = Counter(
    "data_modeling_dag_resolution_deadline_violations_total",
    "Resolutions where the deadline elapsed; in soft mode this is observed without raising.",
    labelnames=["source"],
)


class BoundedResolver(Resolver):
    """A resolver bounded by view-depth, cycle detection, and a wall-clock deadline.

    Extends the base Resolver to (a) refuse re-entry into a view already on the
    resolution stack, (b) cap the nested view depth, and (c) abort if total
    wall-clock time exceeds a deadline. These guards protect callers from
    pathological views that would otherwise consume a worker indefinitely.

    When `enforce_bounds=False`, depth and deadline violations emit metrics but
    do not raise. Cycle detection still raises unconditionally — without it the
    resolver would loop forever and the deadline check would never run.

    The deadline is checked on every `visit()` call, not only at view boundaries,
    so expensive non-join work between views is also interruptible. Metrics
    (`DAG_RESOLUTION_*`) are emitted from the outermost `visit()` invocation, so
    every construction-then-visit usage gets a single counter increment.

    `deadline_anchor` is an optional monotonic timestamp that lets multiple
    BoundedResolver instances share a deadline clock. `prepare_ast_for_printing`
    invokes nested resolve_types/resolve_lazy_tables calls each of which builds
    a fresh BoundedResolver via the factory — without a shared anchor, each
    instance would get its own deadline_seconds budget and the bound would
    compound. The factory in `bounded_resolver_factory_for_view` seeds one
    anchor and passes it to every resolver it produces, so the deadline binds
    end-to-end across the whole query. When omitted, the resolver falls back
    to its own `start_time`, so standalone construction still works.
    """

    def __init__(
        self,
        *args,
        initial_view_name: str | None = None,
        max_view_depth: int = DEFAULT_RESOLUTION_MAX_VIEW_DEPTH,
        deadline_seconds: float | None = DEFAULT_RESOLUTION_DEADLINE_SECONDS,
        enforce_bounds: bool = True,
        deadline_anchor: float | None = None,
        source: str = RESOLUTION_SOURCE_OTHER,
        **kwargs,
    ):
        super().__init__(*args, **kwargs)
        self.source = source
        self.initial_view_name = initial_view_name
        # views whose bodies are currently being visited; seeded with the current view name so
        # it counts as "visited" for cycle detection
        self.resolving_views: set[str] = {initial_view_name} if initial_view_name else set()
        # set by visit_join_expr, consumed by the body visit it triggers (cycle detection needs
        # the name during resolution, before the id map below is populated)
        self._pending_view_name: str | None = None
        # id(resolved union body) -> the view it was inlined from. The base resolver stamps
        # `view_name` on SelectQuery bodies but not SelectSetQuery, so union-bodied views would
        # otherwise lose their identity; get_parents reads this to record the view as the parent
        # instead of descending into its own sources
        self.union_view_name_by_id: dict[int, str] = {}
        self.max_view_depth = max_view_depth
        self.deadline_seconds = deadline_seconds
        self.enforce_bounds = enforce_bounds
        self.deadline_anchor = deadline_anchor
        # local clock — for per-resolver metric duration, distinct from deadline_anchor which
        # may span multiple resolvers from the same factory
        self.start_time: float | None = None
        self.max_view_depth_observed = 0
        self.deadline_violated = False

    def visit(self, node: ast.AST | None):
        if self.start_time is not None:
            self._check_deadline()
            return super().visit(node)

        # outermost call owns metric emission
        start_time = time.monotonic()
        self.start_time = start_time
        self._check_deadline()
        status: str = "ok"
        try:
            return super().visit(node)
        except BoundedResolverError as e:
            status = e.status_label
            raise
        except Exception:
            status = "error"
            raise
        finally:
            DAG_RESOLUTION_TOTAL.labels(source=self.source, status=status).inc()
            DAG_RESOLUTION_DURATION_SECONDS.labels(source=self.source).observe(time.monotonic() - start_time)
            if status == "ok":
                DAG_RESOLUTION_VIEW_DEPTH.labels(source=self.source).observe(self.max_view_depth_observed)
            if self.deadline_violated:
                DAG_RESOLUTION_DEADLINE_VIOLATIONS.labels(source=self.source).inc()

    def _check_deadline(self) -> None:
        if self.deadline_seconds is None:
            return
        anchor = self.deadline_anchor if self.deadline_anchor is not None else self.start_time
        if anchor is None:
            return
        elapsed = time.monotonic() - anchor
        if elapsed <= self.deadline_seconds:
            return
        if self.enforce_bounds:
            raise ResolutionTimeoutError(elapsed, self.deadline_seconds, initial_view=self.initial_view_name)
        # soft mode: record and keep walking — caller opted into observe-only deadlines
        self.deadline_violated = True

    def visit_join_expr(self, node: ast.JoinExpr):
        """Override to add cycle detection and depth limiting for view tables."""
        # CTEs are handled entirely by the parent class, but for views we track visited for cycle detection
        if (
            isinstance(node.table, ast.Field)
            and self.database is not None
            # CTEs shadow database tables (the parent checks self.ctes before any table lookup),
            # so a name bound in the current WITH scope is never a view reference; without this
            # skip, a view whose body defines a same-named CTE reads as a cycle with itself
            and self.ctes.get(".".join(str(n) for n in node.table.chain)) is None
        ):
            try:
                database_table = self.database.get_table([str(n) for n in node.table.chain])
            except QueryError:
                pass  # falls through to the parent class
            else:
                if isinstance(database_table, SavedQuery):
                    view_name = database_table.name
                    if view_name in self.resolving_views:
                        # cycles always raise — observe-only mode would loop forever
                        raise ResolutionCycleError(view_name, initial_view=self.initial_view_name)
                    # current_view_depth is incremented by Resolver.visit_join_expr inside super(); look ahead by one
                    next_depth = self.current_view_depth + 1
                    if next_depth > self.max_view_depth:
                        if self.enforce_bounds:
                            raise ResolutionDepthExceededError(
                                next_depth, self.max_view_depth, initial_view=self.initial_view_name
                            )
                        # soft mode: still expand, but record the overshoot via max_view_depth_observed
                    if next_depth > self.max_view_depth_observed:
                        self.max_view_depth_observed = next_depth
                    # Hand the name to the body visit rather than marking it resolving here: the
                    # base resolver walks node.next_join from inside visit_join_expr, so anything
                    # marked around super() stays marked while later tables in the same FROM
                    # resolve, and siblings would read as cycles.
                    previous_pending = self._pending_view_name
                    self._pending_view_name = view_name
                    try:
                        result = super().visit_join_expr(node)
                    finally:
                        self._pending_view_name = previous_pending
                    # a union body carries no view_name on the resolved tree; record its identity
                    # so get_parents can recover the view name it was inlined from
                    if isinstance(result, ast.JoinExpr) and isinstance(result.table, ast.SelectSetQuery):
                        self.union_view_name_by_id[id(result.table)] = view_name
                    return result

        return super().visit_join_expr(node)

    def _enter_view_body(self, stamped_view_name: str | None) -> str | None:
        """Mark the view whose body is about to be visited, returning the name to pop after.

        The base resolver inlines a view by replacing the table with its parsed body and
        visiting that body before it walks `next_join`, so the body visit — not the JoinExpr
        subtree — is what "on the current path" means for cycle detection. It stamps
        `view_name` on `ast.SelectQuery` bodies only, so union-bodied views rely on the name
        `visit_join_expr` left in `_pending_view_name`.
        """
        view_name = stamped_view_name or self._pending_view_name
        self._pending_view_name = None
        if view_name is not None:
            self.resolving_views.add(view_name)
        return view_name

    def visit_select_query(self, node: ast.SelectQuery):
        view_name = self._enter_view_body(node.view_name)
        try:
            return super().visit_select_query(node)
        finally:
            if view_name is not None:
                self.resolving_views.discard(view_name)

    def visit_select_set_query(self, node: ast.SelectSetQuery):
        view_name = self._enter_view_body(None)
        try:
            return super().visit_select_set_query(node)
        finally:
            if view_name is not None:
                self.resolving_views.discard(view_name)


def bounded_resolver_factory_for_view(
    view_name: str | None,
    *,
    deadline_anchor: float | None = None,
    max_view_depth: int = DEFAULT_RESOLUTION_MAX_VIEW_DEPTH,
    deadline_seconds: float | None = DEFAULT_RESOLUTION_DEADLINE_SECONDS,
    enforce_bounds: bool = True,
    source: str = RESOLUTION_SOURCE_MATERIALIZATION,
) -> ResolverFactory:
    """Build a ResolverFactory bound to a specific saved-query view.

    The returned factory matches the signature expected by `prepare_ast_for_printing`
    and `resolve_types`: it accepts (context, dialect, scopes) and returns a
    BoundedResolver pre-seeded with the view name so cycle detection works.

    `prepare_ast_for_printing` forwards the factory through `resolve_lazy_tables`,
    `resolve_in_cohorts`, and `resolve_in_cohorts_conjoined`, so subqueries built
    mid-transform also resolve through BoundedResolver. All resolvers produced
    by one factory call share a `deadline_anchor`, so `deadline_seconds` is the
    total wall-clock budget for the whole `prepare_ast_for_printing` pass, not
    a per-call budget. Callers may pass an explicit `deadline_anchor` to anchor
    the clock to an earlier event (e.g. a test fixture); when omitted the
    factory seeds it with the current monotonic time.
    """
    anchor = deadline_anchor if deadline_anchor is not None else time.monotonic()

    def factory(
        context: HogQLContext,
        dialect: HogQLDialect,
        scopes: list[ast.SelectQueryType] | None,
    ) -> Resolver:
        return BoundedResolver(
            scopes=scopes,
            context=context,
            dialect=dialect,
            initial_view_name=view_name,
            max_view_depth=max_view_depth,
            deadline_seconds=deadline_seconds,
            enforce_bounds=enforce_bounds,
            deadline_anchor=anchor,
            source=source,
        )

    return factory


class LabelTreeField(models.Field):
    """A Django model field for a PostgreSQL label tree.

    We represent label trees in Python as a list of strings, each item
    in the list being one of the labels of the underlying ltree.
    """

    description = "A PostgreSQL label tree field provided by the ltree extension"

    def db_type(self, connection):
        return "ltree"

    def from_db_value(self, value, expression, connection) -> None | LabelPath:
        if value is None:
            return value

        return value.split(".")

    def to_python(self, value) -> None | LabelPath:
        if value is None:
            return value

        if isinstance(value, list):
            return value

        return value.split(".")

    def get_prep_value(self, value: LabelPath) -> str:
        return ".".join(value)


# enclosing WITH clauses, innermost first — a name resolves against the closest one
CteScope = tuple[dict[str, ast.CTE], ...]


def _scope_for_union_branches(select_set: ast.SelectSetQuery, scope: CteScope) -> CteScope:
    """Extend `scope` with the WITH that precedes a union.

    A leading WITH covers every branch of the union, but HogQL parses it onto the first
    branch's `ctes`. The branches are walked independently, so hoist it first or later
    branches resolve their CTE references as though they were tables.
    """
    leading: ast.SelectQuery | ast.SelectSetQuery = select_set.initial_select_query
    while isinstance(leading, ast.SelectSetQuery):
        leading = leading.initial_select_query

    if leading.ctes:
        return (leading.ctes, *scope)
    return scope


def _lookup_cte(name: str, scope: CteScope) -> ast.CTE | None:
    for ctes in scope:
        cte = ctes.get(name)
        if cte is not None:
            return cte
    return None


def _select_queries_with_scope(
    select: ast.SelectQuery | ast.SelectSetQuery, scope: CteScope
) -> list[tuple[ast.SelectQuery, CteScope]]:
    """Flatten a query into (leaf SelectQuery, CTE scope) pairs, threading scope per branch.

    A union's leading WITH must scope only that union's own branches. Computing one scope
    for the whole container and applying it to every flattened leaf loses the WITH that a
    *nested* union carries in a non-initial branch. Recursing branch by branch keeps each
    nested union's WITH bound to its own branches, at any depth or position.
    """
    if isinstance(select, ast.SelectQuery):
        return [(select, scope)]

    branch_scope = _scope_for_union_branches(select, scope)
    result = _select_queries_with_scope(select.initial_select_query, branch_scope)
    for node in select.subsequent_select_queries:
        result.extend(_select_queries_with_scope(node.select_query, branch_scope))
    return result


class _SubqueryCollector(TraversingVisitor):
    """Collect the subqueries a FROM-chain walk never reaches.

    Stops at every nested select rather than descending into it, so the caller can feed
    each one back through its own loop with the CTE scope that query can see. Skips a
    join's table and a CTE's body for the same reason: both already have an owner.
    """

    def __init__(self, root: ast.SelectQuery) -> None:
        self._root = root
        self.selects: list[ast.SelectQuery | ast.SelectSetQuery] = []

    def visit_select_query(self, node: ast.SelectQuery) -> None:
        if node is self._root:
            super().visit_select_query(node)
            return
        self.selects.append(node)

    def visit_select_set_query(self, node: ast.SelectSetQuery) -> None:
        self.selects.append(node)

    def visit_join_expr(self, node: ast.JoinExpr) -> None:
        # the FROM-chain walk already reaches node.table, but nothing else reaches an ON
        # constraint or a table function's arguments
        self.visit(node.constraint)
        for arg in node.table_args or []:
            self.visit(arg)
        self.visit(node.next_join)

    def visit_cte(self, node: ast.CTE) -> None:
        # a CTE body is expanded where it is referenced, so that an unreferenced one stays
        # out of the parent set
        pass


def _subqueries_outside_from(query: ast.SelectQuery) -> list[ast.SelectQuery | ast.SelectSetQuery]:
    collector = _SubqueryCollector(query)
    collector.visit(query)
    return collector.selects


def get_parents_from_model_query(
    team: Team, model_name: str, model_query: str, database: Database | None = None
) -> set[str]:
    """Get parents from a given query.

    The parents of a query are every name it reads: the `FROM` clause, and any subquery
    that sits elsewhere — a `WHERE`, a `HAVING`, the select list, a join's `ON`.
    Uses BoundedResolver to detect circular dependencies, cap nested view
    depth, and enforce a wall-clock deadline on view references. Resolver-level
    metrics (`DAG_RESOLUTION_*`) are emitted from the resolver itself, so this
    function does not need its own try/except/metric cascade.

    Args:
        team: The team context for database resolution.
        model_name: The name of the saved query being parsed; used as the
            initial view so cycles back to it are detected.
        model_query: The HogQL query string to parse.
        database: An optional prebuilt database to reuse for dependency resolution.
    """
    hogql_query = parse_select(model_query)
    context = HogQLContext(
        team_id=team.pk,
        team=team,
        enable_select_queries=True,
    )
    context.database = database
    if context.database is None:
        # Internal DAG parsing (no user); bypass warehouse HogQL access control so parent-table
        # resolution sees every referenced table/view.
        context.database = Database.create_for(
            context.team_id,
            modifiers=context.modifiers,
            team=context.team,
            bypass_warehouse_access_control=True,
            allowed_system_tables=DATA_MODELING_ALLOWED_SYSTEM_TABLES,
        )

    resolver = BoundedResolver(
        context=context, dialect="hogql", initial_view_name=model_name, source=RESOLUTION_SOURCE_LINEAGE
    )
    prepared_ast = resolver.visit(hogql_query)

    if prepared_ast is None:
        return set()

    # each query is walked with the CTE scopes it can actually see, so a name defined in
    # one query's WITH never resolves a reference in an unrelated one
    queries: list[tuple[ast.SelectQuery, CteScope]] = _select_queries_with_scope(prepared_ast, ())

    parents: set[str] = set()

    # track by object id so that a recursive CTE (same object) is only
    # expanded once, while an inner CTE that shadows an outer name (different
    # object) is still expanded. The AST holds a strong reference for the
    # lifetime of this function, so the id() identity is stable.
    expanded_ctes: set[int] = set()

    def record_or_queue(select: ast.SelectQuery | ast.SelectSetQuery, scope: CteScope) -> None:
        """Record a view by name, or queue an anonymous query to be walked.

        A saved-query view is itself the parent, so descending past it would report its
        sources instead of it. A SelectQuery view carries its name; a union body doesn't,
        so recover that one from the resolver's id map.
        """
        if isinstance(select, ast.SelectQuery):
            view_name = select.view_name
        else:
            view_name = resolver.union_view_name_by_id.get(id(select))

        if view_name is not None:
            parents.add(view_name)
        else:
            queries.extend(_select_queries_with_scope(select, scope))

    while queries:
        query, scope = queries.pop()

        if query.ctes:
            scope = (query.ctes, *scope)

        for subquery in _subqueries_outside_from(query):
            record_or_queue(subquery, scope)

        # a FROM clause is a next_join chain; PIVOT/UNPIVOT over a join nests another chain,
        # so keep a stack of chains still to walk
        pending_joins: list[ast.JoinExpr | None] = [query.select_from]

        while pending_joins:
            join = pending_joins.pop()

            while join is not None:
                # every table in the FROM is a parent, so keep walking next_join past
                # subqueries and expanded views rather than stopping at the first one
                table: ast.Expr | None = join.table

                # PIVOT/UNPIVOT wrap a real source — a table, a subquery, or a whole join — so
                # unwrap to it; the source is the parent, not the pivot
                while isinstance(table, ast.PivotExpr | ast.UnpivotExpr):
                    table = table.table

                if isinstance(table, ast.JoinExpr):
                    # a pivot over a join result: walk that inner chain too
                    pending_joins.append(table)
                    join = join.next_join
                    continue
                elif isinstance(table, ast.SelectQuery | ast.SelectSetQuery):
                    record_or_queue(table, scope)
                    join = join.next_join
                    continue
                elif isinstance(table, ast.ValuesQuery):
                    # inline literal rows, no parent
                    join = join.next_join
                    continue

                if join.table_args is not None:
                    # Table functions like numbers(), s3(), etc. are not real parents
                    join = join.next_join
                    continue
                elif isinstance(table, ast.Placeholder):
                    parent_name = table.field
                elif isinstance(table, ast.Field):
                    parent_name = ".".join(str(s) for s in table.chain)
                else:
                    raise ValueError(f"No handler for {table.__class__.__name__} in get_parents_from_model_query")

                if isinstance(parent_name, str):
                    cte = _lookup_cte(parent_name, scope)
                    if cte is None:
                        parents.add(parent_name)
                    elif id(cte) not in expanded_ctes:
                        expanded_ctes.add(id(cte))
                        if isinstance(cte.expr, ast.SelectQuery | ast.SelectSetQuery):
                            queries.extend(_select_queries_with_scope(cte.expr, scope))

                join = join.next_join

    return parents


class UnknownParentError(Exception):
    """Exception raised when the parent for a model is not found."""

    def __init__(self, parent: str, query: str):
        super().__init__(
            f"The parent name {parent} does not correspond to an existing PostHog table, Data Warehouse Table, or Data Warehouse Saved Query."
        )
        self.query = query
