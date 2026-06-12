"""Lazy table and lazy join expansion.

Replaces references to lazy tables (`persons`, `sessions`, …) and lazy joins (`events.pdi`, `events.person`, …) with
real subqueries and JOINs, in a resolve → expand → re-resolve loop:

    while the tree contains lazy references (bounded, typically one round):
        collect demand   — read-only walk of the typed tree: which lazy tables/joins are used, which fields on each
        expand           — mutate the AST: build each subquery from its recipe, splice in JOINs, rewrite the
                           referencing field chains to point at the new subquery columns
        re-resolve       — clear all types and run the resolver on the expanded tree

The loop converges because expansion rewrites every referencing chain (e.g. `events.pdi.person_id` becomes
`events__pdi.person_id`), so the next resolution binds those fields to the spliced subqueries instead of
re-discovering the lazy join. Types are never patched by hand: the resolver is the only thing that assigns them.
A recipe's output may itself contain lazy references (chained joins, join constraints against other lazy tables);
those are ordinary lazy references in the next iteration.

Column naming inside built subqueries keeps the historical conventions — property chains joined with `___`
(`properties___$browser`) and join-key projections prefixed with the table name (`events__pdi___person_id`) — so the
printed SQL is identical to what the previous implementation (`lazy_tables.py`) produced.
"""

import dataclasses
from typing import TYPE_CHECKING, Optional, cast

if TYPE_CHECKING:
    from posthog.hogql.transforms.property_types import PropertySwapper

from posthog.hogql import ast
from posthog.hogql.base import _T_AST
from posthog.hogql.constants import HogQLDialect
from posthog.hogql.context import HogQLContext
from posthog.hogql.database.models import LazyJoinToAdd, LazyTableToAdd
from posthog.hogql.errors import ResolutionError
from posthog.hogql.resolver import ResolverFactory, resolve_types
from posthog.hogql.resolver_utils import get_long_table_name
from posthog.hogql.visitor import CloningVisitor, TraversingVisitor, clone_expr

MAX_EXPANSION_ITERATIONS = 10


@dataclasses.dataclass
class ConstraintOverride:
    alias: str
    table_name: str
    chain_to_replace: list[str | int]


@dataclasses.dataclass
class FieldRewrite:
    """Rewrite one referencing ast.Field to point at an expanded subquery column. A non-empty `tail` keeps a
    property path on the rewritten chain — used when only the JSON blob is demanded and the property is extracted
    in place (the within_non_hogql_query mode)."""

    field: ast.Field
    table_name: str
    column_name: str
    tail: list[str | int] = dataclasses.field(default_factory=list)


@dataclasses.dataclass
class _CollectedRef:
    """One lazy field reference found in the tree: the AST node, the type it routes through, and an optional
    property tail to keep on the rewritten chain."""

    node: ast.Field
    ref: "ast.FieldType | ast.PropertyType"
    tail: list[str | int] = dataclasses.field(default_factory=list)


@dataclasses.dataclass
class ScopeDemand:
    """Everything one SELECT scope needs expanded, plus how to rewrite its references afterwards."""

    select: ast.SelectQuery
    select_type: ast.SelectQueryType
    tables_to_add: dict[str, LazyTableToAdd] = dataclasses.field(default_factory=dict)
    joins_to_add: dict[str, LazyJoinToAdd] = dataclasses.field(default_factory=dict)
    field_rewrites: list[FieldRewrite] = dataclasses.field(default_factory=list)
    constraint_overrides: dict[str, list[ConstraintOverride]] = dataclasses.field(default_factory=dict)
    tables_to_wrap: set[str] = dataclasses.field(default_factory=set)

    def is_empty(self) -> bool:
        return not self.tables_to_add and not self.joins_to_add and not self.field_rewrites


class HiddenAliasCollapser(TraversingVisitor):
    """Collapses hidden aliases nested by re-resolution back to the single-wrap shape.

    The resolver wraps every field it resolves in a hidden alias carrying the column's user-visible name, so each
    expansion iteration adds one more layer. Downstream passes (the property swapper's comparison handling, the
    events predicate pushdown) match on the single-wrap shape; the outermost alias keeps its name — it's the one
    carrying the original column name."""

    def visit_alias(self, node: ast.Alias):
        if node.hidden:
            while isinstance(node.expr, ast.Alias) and node.expr.hidden:
                node.expr = node.expr.expr
            if isinstance(node.type, ast.FieldAliasType) and node.expr.type is not None:
                node.type = ast.FieldAliasType(alias=node.alias, type=node.expr.type)
        super().visit_alias(node)


class BareFieldQualifier(TraversingVisitor):
    """Qualifies bare single-name field chains with their resolved table before re-resolution.

    Splicing a join can make a bare name ambiguous (`distinct_id` once `events__override` exists). The field is
    already bound, so qualifying it preserves semantics; printing goes through types, so output is unchanged.
    Nested SELECTs are separate scopes and are skipped — they qualify themselves when they expand.
    """

    def __init__(self, select_type: ast.SelectQueryType) -> None:
        super().__init__()
        self.select_type = select_type
        self._root_visited = False

    def visit_select_query(self, node: ast.SelectQuery):
        if self._root_visited:
            return
        self._root_visited = True
        super().visit_select_query(node)

    def visit_field(self, node: ast.Field):
        if len(node.chain) != 1 or not isinstance(node.type, ast.FieldType):
            return
        table_type = node.type.table_type
        if isinstance(table_type, ast.VirtualTableType):
            return  # virtual-table fields keep their bare names; expansion rewrites them separately
        try:
            table_name = get_long_table_name(self.select_type, table_type)
        except ResolutionError:
            return
        if table_name and table_name in self.select_type.tables:
            node.chain = [table_name, node.chain[0]]


class FieldChainReplacer(TraversingVisitor):
    def __init__(self, overrides: list[ConstraintOverride]) -> None:
        super().__init__()
        self.overrides = overrides

    def visit_field(self, node: ast.Field):
        for constraint in self.overrides:
            if node.chain == constraint.chain_to_replace:
                node.chain = [constraint.table_name, constraint.alias]


class FieldFinder(TraversingVisitor):
    def __init__(self) -> None:
        super().__init__()
        self.field_chains: list[list[str | int]] = []

    def visit_field(self, node: ast.Field):
        self.field_chains.append(node.chain)


def find_field_chains(node: ast.AST | None) -> list[list[str | int]]:
    if node is None:
        return []
    finder = FieldFinder()
    finder.visit(node)
    return finder.field_chains


def references_table(node: ast.AST | None, table_alias: str) -> bool:
    return any(chain and chain[0] == table_alias for chain in find_field_chains(node))


def collect_fields_from_table(node: ast.AST, table_alias: str) -> set[str]:
    return {
        chain[1]
        for chain in find_field_chains(node)
        if len(chain) >= 2 and chain[0] == table_alias and isinstance(chain[1], str)
    }


def collect_bare_fields(node: ast.AST) -> set[str]:
    return {chain[0] for chain in find_field_chains(node) if len(chain) == 1 and isinstance(chain[0], str)}


def _unwrap_to_base_table_type(table_type: ast.Type) -> ast.Type:
    while isinstance(table_type, (ast.TableAliasType, ast.ColumnAliasedTableType, ast.VirtualTableType)):
        table_type = table_type.table_type
    return table_type


class LazyDemandCollector(TraversingVisitor):
    """Read-only pass over a typed tree. Produces one ScopeDemand per SELECT scope that uses lazy tables/joins.

    Mirrors the collection semantics of the old transform: properties are demanded before plain fields (so the
    narrowest reads come first in built subqueries), and a lazy from-table with no requested fields still gets
    expanded (``select count() from persons``).
    """

    def __init__(self, context: HogQLContext, stack: Optional[list[ast.SelectQuery]]) -> None:
        super().__init__()
        self.context = context
        # When printing with a stack of outer queries, fields bound to outer-scope lazy tables are collected into a
        # phantom scope and ignored — the outer query was already expanded.
        self.collectors: list[list[_CollectedRef]] = [[]] if stack else []
        self.demands: list[ScopeDemand] = []

    def visit_field(self, node: ast.Field):
        node_type = node.type
        if isinstance(node_type, ast.PropertyType):
            base = _unwrap_to_base_table_type(node_type.field_type.table_type)
            if isinstance(base, (ast.LazyJoinType, ast.LazyTableType)):
                if self.context.within_non_hogql_query:
                    # In a non-HogQL query, demand the whole blob field; the property is extracted in place, so
                    # the rewritten chain keeps the property path as a tail.
                    self._collect(node, node_type.field_type, tail=list(node_type.chain))
                else:
                    self._collect(node, node_type)
            return
        if isinstance(node_type, ast.FieldType):
            base = _unwrap_to_base_table_type(node_type.table_type)
            if isinstance(base, (ast.LazyJoinType, ast.LazyTableType)):
                self._collect(node, node_type)
            return
        # Other types (FieldAliasType references etc.) don't demand anything themselves; the aliased
        # expression's own field node is collected when visited.

    def _collect(
        self,
        node: ast.Field,
        field_or_property: ast.FieldType | ast.PropertyType,
        tail: list[str | int] | None = None,
    ) -> None:
        if len(self.collectors) == 0:
            raise ResolutionError("Can't access a lazy field when not in a SelectQuery context")
        self.collectors[-1].append(_CollectedRef(node=node, ref=field_or_property, tail=tail or []))

    def visit_cte(self, node: ast.CTE):
        self.visit(node.expr)

    def visit_select_query(self, node: ast.SelectQuery):
        select_type = node.type
        if not select_type:
            raise ResolutionError("Select query must have a type")

        if node.ctes:
            for cte in node.ctes.values():
                self.visit_cte(cte)

        collector: list[_CollectedRef] = []
        self.collectors.append(collector)
        super().visit_select_query(node)
        self.collectors.pop()

        demand = self._build_scope_demand(node, select_type, collector)
        if demand is not None:
            self.demands.append(demand)

    def _build_scope_demand(
        self,
        node: ast.SelectQuery,
        select_type: ast.SelectQueryType,
        collector: list[_CollectedRef],
    ) -> ScopeDemand | None:
        demand = ScopeDemand(select=node, select_type=select_type)

        # Properties before fields: the narrowest reads define the built subquery's projections first.
        ordered = [c for c in collector if isinstance(c.ref, ast.PropertyType)] + [
            c for c in collector if isinstance(c.ref, ast.FieldType)
        ]

        # Lazy from-tables with no requested fields still need expanding (`select count() from persons`).
        join = node.select_from
        while join:
            if join.table is not None and isinstance(join.table.type, ast.LazyTableType):
                if not any(self._field_belongs_to(c.ref, join.table.type) for c in ordered):
                    table_name = join.alias or get_long_table_name(select_type, join.table.type)
                    demand.tables_to_add[table_name] = LazyTableToAdd(
                        fields_accessed={}, lazy_table=join.table.type.table
                    )
            join = join.next_join

        for collected in ordered:
            self._add_demand_for_field(demand, select_type, collected)

        if demand.is_empty():
            return None

        # Join-key closure: when a join's source or target is itself being expanded, the join key must be
        # projected out of that expansion under a collision-prefixed alias, and the recipe's constraint
        # rewritten to use it.
        def create_override(table_name: str, field_chain: list[str | int]) -> None:
            alias = f"{table_name}___{'___'.join(str(x) for x in field_chain)}"
            if table_name in demand.tables_to_add:
                demand.tables_to_add[table_name].fields_accessed[alias] = field_chain
            else:
                demand.joins_to_add[table_name].fields_accessed[alias] = field_chain
            demand.constraint_overrides.setdefault(table_name, []).append(
                ConstraintOverride(alias=alias, table_name=table_name, chain_to_replace=[table_name, *field_chain])
            )

        for new_join in demand.joins_to_add.values():
            if new_join.from_table in demand.joins_to_add or new_join.from_table in demand.tables_to_add:
                create_override(new_join.from_table, new_join.lazy_join.from_field)
            if new_join.lazy_join.to_field is not None and (
                new_join.to_table in demand.joins_to_add or new_join.to_table in demand.tables_to_add
            ):
                create_override(new_join.to_table, new_join.lazy_join.to_field)

        demand.tables_to_wrap = self._find_tables_needing_wrap(node, demand.joins_to_add)
        return demand

    @staticmethod
    def _field_belongs_to(field_or_property: ast.FieldType | ast.PropertyType, table_type: ast.LazyTableType) -> bool:
        f = field_or_property.field_type if isinstance(field_or_property, ast.PropertyType) else field_or_property
        t = f.table_type
        if isinstance(t, (ast.TableAliasType, ast.ColumnAliasedTableType, ast.VirtualTableType)):
            return t.table_type == table_type
        return t == table_type

    def _add_demand_for_field(
        self,
        demand: ScopeDemand,
        select_type: ast.SelectQueryType,
        collected: _CollectedRef,
    ) -> None:
        if isinstance(collected.ref, ast.PropertyType):
            property: ast.PropertyType | None = collected.ref
            field = collected.ref.field_type
        else:
            property = None
            field = collected.ref

        # Walk down the chain of lazy tables under this field, collecting each hop.
        table_types: list[ast.LazyJoinType | ast.LazyTableType | ast.TableAliasType | ast.ColumnAliasedTableType] = []
        table_type: ast.Type = field.table_type
        while True:
            if isinstance(table_type, ast.VirtualTableType):
                table_type = table_type.table_type
                continue
            if isinstance(table_type, ast.LazyJoinType):
                table_types.append(table_type)
                table_type = table_type.table_type
                continue
            if isinstance(table_type, (ast.TableAliasType, ast.ColumnAliasedTableType)):
                table_types.append(table_type)
                break
            if isinstance(table_type, ast.LazyTableType):
                table_types.append(table_type)
                break
            break

        # Create joins/tables for each hop, outermost-first; record the projection on the hop that owns the field.
        for hop in reversed(table_types):
            if isinstance(hop, (ast.TableAliasType, ast.ColumnAliasedTableType)):
                inner = hop.table_type
                if isinstance(inner, ast.LazyJoinType):
                    self._demand_join(demand, select_type, hop, inner, collected, field, property, alias_of=hop)
                elif isinstance(inner, ast.LazyTableType):
                    self._demand_table(demand, select_type, hop, inner, collected, field, property)
            elif isinstance(hop, ast.LazyJoinType):
                self._demand_join(demand, select_type, hop, hop, collected, field, property, alias_of=None)
            elif isinstance(hop, ast.LazyTableType):
                self._demand_table(demand, select_type, hop, hop, collected, field, property)

    def _projection_for(self, field: ast.FieldType, property: ast.PropertyType | None) -> tuple[str, list[str | int]]:
        """The (column name, source chain) a built subquery projects for this field/property."""
        chain: list[str | int] = []
        if isinstance(field.table_type, ast.VirtualTableType):
            chain.append(field.table_type.field)
        chain.append(field.name)
        if property is not None:
            chain.extend(property.chain)
            return "___".join(str(x) for x in chain), chain
        return field.name, chain

    def _hop_owns_field(self, hop: ast.Type, field: ast.FieldType) -> bool:
        return hop == field.table_type or (
            isinstance(field.table_type, ast.VirtualTableType) and hop == field.table_type.table_type
        )

    def _demand_join(
        self,
        demand: ScopeDemand,
        select_type: ast.SelectQueryType,
        name_type: ast.Type,
        lazy_join_type: ast.LazyJoinType,
        collected: _CollectedRef,
        field: ast.FieldType,
        property: ast.PropertyType | None,
        alias_of: ast.Type | None,
    ) -> None:
        if isinstance(lazy_join_type.table_type, ast.VirtualTableType):
            from_table = get_long_table_name(select_type, lazy_join_type.table_type.table_type)
        else:
            from_table = get_long_table_name(select_type, lazy_join_type.table_type)
        to_table = get_long_table_name(select_type, name_type)

        # A previous iteration may have already spliced this join (e.g. a recipe constraint referencing a lazy
        # join the outer query also used). Rewrite the reference to the existing join, don't add another.
        if isinstance(select_type.tables.get(to_table), ast.SelectQueryAliasType):
            owner = alias_of if alias_of is not None else lazy_join_type
            if self._hop_owns_field(owner, field):
                column_name, _ = self._projection_for(field, property)
                demand.field_rewrites.append(
                    FieldRewrite(
                        field=collected.node, table_name=to_table, column_name=column_name, tail=collected.tail
                    )
                )
            return

        if to_table not in demand.joins_to_add:
            demand.joins_to_add[to_table] = LazyJoinToAdd(
                fields_accessed={},
                lazy_join=lazy_join_type.lazy_join,
                from_table=from_table,
                to_table=to_table,
                lazy_join_type=lazy_join_type,
            )
        new_join = demand.joins_to_add[to_table]

        owner = alias_of if alias_of is not None else lazy_join_type
        if self._hop_owns_field(owner, field):
            column_name, chain = self._projection_for(field, property)
            new_join.fields_accessed[column_name] = chain
            demand.field_rewrites.append(
                FieldRewrite(field=collected.node, table_name=to_table, column_name=column_name, tail=collected.tail)
            )

    def _demand_table(
        self,
        demand: ScopeDemand,
        select_type: ast.SelectQueryType,
        name_type: ast.Type,
        lazy_table_type: ast.LazyTableType,
        collected: _CollectedRef,
        field: ast.FieldType,
        property: ast.PropertyType | None,
    ) -> None:
        table_name = get_long_table_name(select_type, name_type)
        if table_name not in demand.tables_to_add:
            demand.tables_to_add[table_name] = LazyTableToAdd(
                fields_accessed={}, lazy_table=cast(ast.LazyTable, lazy_table_type.table)
            )
        new_table = demand.tables_to_add[table_name]

        owner = name_type if not isinstance(name_type, ast.LazyTableType) else lazy_table_type
        if self._hop_owns_field(owner, field):
            column_name, chain = self._projection_for(field, property)
            new_table.fields_accessed[column_name] = chain
            demand.field_rewrites.append(
                FieldRewrite(field=collected.node, table_name=table_name, column_name=column_name, tail=collected.tail)
            )

    def _find_tables_needing_wrap(self, node: ast.SelectQuery, joins_to_add: dict[str, LazyJoinToAdd]) -> set[str]:
        """Tables whose explicit JOIN constraint references one of their own lazy joins. Expanding such a join in
        the outer query would forward-reference it from the constraint, so the table is wrapped in a subquery that
        projects the lazy reference instead; the next iteration expands it inside that subquery."""
        tables_to_wrap: set[str] = set()
        join_ptr = node.select_from
        while join_ptr:
            if join_ptr.constraint is not None and isinstance(join_ptr.table, ast.Field):
                table_alias = join_ptr.alias or str(join_ptr.table.chain[0])
                for join_to_add in joins_to_add.values():
                    if join_to_add.from_table == table_alias:
                        lazy_field_name = join_to_add.lazy_join_type.field if join_to_add.lazy_join_type else None
                        if lazy_field_name and references_table(join_ptr.constraint, lazy_field_name):
                            tables_to_wrap.add(table_alias)
                            break
            join_ptr = join_ptr.next_join
        return tables_to_wrap


def collect_lazy_demand(
    node: ast.AST, context: HogQLContext, stack: Optional[list[ast.SelectQuery]]
) -> list[ScopeDemand]:
    collector = LazyDemandCollector(context=context, stack=stack)
    collector.visit(node)
    return collector.demands


def _expand_scope(
    demand: ScopeDemand,
    context: HogQLContext,
    dialect: HogQLDialect,
    resolver_factory: ResolverFactory | None,
) -> None:
    """Mutate one SELECT scope: splice in the built subqueries/joins and rewrite the referencing field chains.

    Built subtrees are resolved against the scope before splicing — not to keep their types (the caller clears and
    re-resolves the whole tree afterwards), but because join placement depends on the constraint's *resolved* shape:
    expression fields (e.g. events.person_id under person-id overrides) only reveal which tables a constraint
    depends on once expanded. Resolving here also registers the new aliases on the scope, which is what lets the
    next iteration's collector distinguish "this join already exists" from "this join must be added".
    """
    node = demand.select
    select_type = demand.select_type
    group_swapper = _group_property_swapper(context)

    # The ClickHouse printer derives an alias for an unaliased Call select item from its HogQL rendering, which
    # prints field chains as written. Rewriting (or qualifying) chains would change that derivation, so freeze the
    # alias now, from the pre-rewrite tree.
    _freeze_call_aliases(node, context)

    # New joins can make bare field names ambiguous on re-resolution; qualify them with their bound table first.
    if demand.joins_to_add:
        BareFieldQualifier(select_type).visit(node)

    # Wrap tables whose explicit join constraints reference their own lazy joins, and rewrite those constraint
    # fields to read the projection out of the wrap. The lazy reference now lives inside the wrap's SELECT and is
    # expanded on the next iteration.
    for table_alias in demand.tables_to_wrap:
        _wrap_table(demand, table_alias)
    if demand.tables_to_wrap:
        demand.joins_to_add = {
            k: v for k, v in demand.joins_to_add.items() if v.from_table not in demand.tables_to_wrap
        }
        rewritten_tables = {r.table_name for r in demand.field_rewrites}
        # Rewrites targeting joins dropped in favor of a wrap were handled by the wrap's constraint rewriting.
        demand.field_rewrites = [
            r
            for r in demand.field_rewrites
            if r.table_name in demand.joins_to_add or r.table_name in demand.tables_to_add
        ]
        del rewritten_tables

    # Build and splice lazy table subqueries (the FROM side).
    for table_name, table_to_add in demand.tables_to_add.items():
        subquery = table_to_add.lazy_table.lazy_select(table_to_add, context, node=node)
        subquery = cast(ast.SelectQuery, clone_expr(subquery, clear_locations=True))
        subquery = cast(
            ast.SelectQuery, resolve_types(subquery, context, dialect, [select_type], resolver_factory=resolver_factory)
        )
        if group_swapper is not None:
            subquery = group_swapper.visit(subquery)
        assert subquery.type is not None
        old_table_type = select_type.tables.get(table_name)
        select_type.tables[table_name] = ast.SelectQueryAliasType(alias=table_name, select_query_type=subquery.type)

        join_ptr = node.select_from
        while join_ptr:
            if join_ptr.table is not None and (
                join_ptr.table.type == old_table_type
                or (
                    isinstance(old_table_type, (ast.TableAliasType, ast.ColumnAliasedTableType))
                    and join_ptr.table.type == old_table_type.table_type
                )
            ):
                join_ptr.table = subquery
                join_ptr.type = select_type.tables[table_name]
                join_ptr.alias = table_name
                break
            join_ptr = join_ptr.next_join

    # Build and splice lazy join subqueries.
    for to_table, join_scope in demand.joins_to_add.items():
        join_to_add: ast.JoinExpr = join_scope.lazy_join.resolve_join_to_add(join_scope, context, node)
        overrides = [
            *demand.constraint_overrides.get(join_scope.to_table, []),
            *demand.constraint_overrides.get(join_scope.from_table, []),
        ]
        if overrides:
            FieldChainReplacer(overrides).visit(join_to_add)
        join_to_add = cast(ast.JoinExpr, clone_expr(join_to_add, clear_locations=True, clear_types=True))
        join_to_add = cast(
            ast.JoinExpr, resolve_types(join_to_add, context, dialect, [select_type], resolver_factory=resolver_factory)
        )
        if group_swapper is not None:
            join_to_add = group_swapper.visit(join_to_add)
        if join_to_add.type is not None:
            select_type.tables[to_table] = join_to_add.type

        _splice_join(node, demand, join_scope, join_to_add)

    # Rewrite the referencing fields to read the projected columns off the new subqueries.
    for rewrite in demand.field_rewrites:
        rewrite.field.chain = [rewrite.table_name, rewrite.column_name, *rewrite.tail]
        rewrite.field.type = None


def _freeze_call_aliases(node: ast.SelectQuery, context: HogQLContext) -> None:
    from posthog.hogql.escape_sql import safe_identifier  # noqa: PLC0415 — circular import via the printer package
    from posthog.hogql.printer.hogql import HogQLPrinter  # noqa: PLC0415 — circular import via the printer package

    for i, expr in enumerate(node.select):
        if isinstance(expr, ast.Call):
            alias = safe_identifier(HogQLPrinter(context=context).visit(expr))
            node.select[i] = ast.Alias(alias=alias, expr=expr, hidden=True)


def _splice_join(
    node: ast.SelectQuery, demand: ScopeDemand, join_scope: LazyJoinToAdd, join_to_add: ast.JoinExpr
) -> None:
    """Insert the built join after its source table, but after any existing join its constraint depends on."""
    constraint_field_chains = find_field_chains(join_to_add.constraint)

    select_from_alias: str | int | None = None
    if node.select_from and node.select_from.alias:
        select_from_alias = node.select_from.alias
    elif node.select_from and node.select_from.table and isinstance(node.select_from.table, ast.Field):
        select_from_alias = node.select_from.table.chain[0]

    constraint_tables: list[str | int] = []
    for field_chain in constraint_field_chains:
        if field_chain[0] == select_from_alias:
            continue
        added = False
        for constraint_table_join in demand.joins_to_add.values():
            if constraint_table_join.lazy_join_type and field_chain[0] == constraint_table_join.lazy_join_type.field:
                constraint_tables.append(constraint_table_join.to_table)
                added = True
                break
        if not added:
            constraint_tables.append(field_chain[0])

    join_ptr = node.select_from
    while join_ptr:
        if join_scope.from_table == join_ptr.alias or (
            isinstance(join_ptr.table, ast.Field) and join_scope.from_table == join_ptr.table.chain[0]
        ):
            if join_ptr.next_join and join_ptr.next_join.alias in constraint_tables:
                if join_ptr.next_join.next_join:
                    join_to_add.next_join = join_ptr.next_join.next_join
                join_ptr.next_join.next_join = join_to_add
            else:
                join_to_add.next_join = join_ptr.next_join
                join_ptr.next_join = join_to_add
            return
        if join_ptr.next_join:
            join_ptr = join_ptr.next_join
        else:
            break
    if join_ptr:
        join_ptr.next_join = join_to_add
    elif node.select_from:
        node.select_from.next_join = join_to_add
    else:
        node.select_from = join_to_add


def _get_lazy_join_type_from_field(node: ast.Field) -> ast.LazyJoinType | None:
    if not isinstance(node.type, ast.FieldType):
        return None
    table_type = node.type.table_type
    while isinstance(table_type, ast.VirtualTableType):
        table_type = table_type.table_type
    return table_type if isinstance(table_type, ast.LazyJoinType) else None


def _get_table_alias_for_lazy_join(lazy_join_type: ast.LazyJoinType) -> str | None:
    table_type: ast.Type | None = lazy_join_type.table_type
    while table_type:
        if isinstance(table_type, (ast.TableAliasType, ast.ColumnAliasedTableType)):
            return table_type.alias
        if isinstance(table_type, ast.TableType):
            return table_type.table.to_printed_hogql()
        if isinstance(table_type, (ast.VirtualTableType, ast.LazyJoinType)):
            table_type = table_type.table_type
        else:
            break
    return None


class _LazyJoinFieldFinder(TraversingVisitor):
    """Finds fields routed through one of the given lazy joins (matched by object identity within this pass)."""

    def __init__(self, lazy_join_type_ids: set[int]) -> None:
        super().__init__()
        self.lazy_join_type_ids = lazy_join_type_ids
        self.found: list[ast.Field] = []

    def visit_field(self, node: ast.Field):
        lazy_join_type = _get_lazy_join_type_from_field(node)
        if lazy_join_type and id(lazy_join_type) in self.lazy_join_type_ids:
            self.found.append(node)


class _LazyJoinTypeCollector(TraversingVisitor):
    """Collects identities of LazyJoinTypes referenced by a constraint, filtered to those anchored at one table."""

    def __init__(self, lazy_join_names: set[str], table_alias: str) -> None:
        super().__init__()
        self.lazy_join_names = lazy_join_names
        self.table_alias = table_alias
        self.lazy_join_type_ids: set[int] = set()

    def visit_field(self, node: ast.Field):
        if node.chain and node.chain[0] in self.lazy_join_names:
            lazy_join_type = _get_lazy_join_type_from_field(node)
            if lazy_join_type and _get_table_alias_for_lazy_join(lazy_join_type) == self.table_alias:
                self.lazy_join_type_ids.add(id(lazy_join_type))


class _LazyJoinExpressionReplacer(CloningVisitor):
    """Replaces `if(...)` calls whose then-branch reads through the wrapped table's lazy join with a single column
    reference into the wrap — the wrap projects the same expression under that column name (an events-style
    `person_id` expression field, re-expanded when the wrap's contents resolve)."""

    def __init__(self, table_alias: str, lazy_join_type_ids: set[int]) -> None:
        super().__init__(clear_types=False, clear_locations=False)
        self.table_alias = table_alias
        self.lazy_join_type_ids = lazy_join_type_ids

    def visit_call(self, node: ast.Call):
        if node.name == "if" and len(node.args) >= 2:
            finder = _LazyJoinFieldFinder(self.lazy_join_type_ids)
            finder.visit(node.args[1])
            for field in finder.found:
                assert len(field.chain) == 2, f"Expected lazy join field chain of length 2, got {field.chain}"
                return ast.Field(chain=[self.table_alias, str(field.chain[1])])
        return super().visit_call(node)


def _wrap_table(demand: ScopeDemand, table_alias: str) -> None:
    """Replace a real table with `(SELECT <used fields> FROM table) AS alias`. The projected fields include
    expression fields and join keys whose definitions read through the table's own lazy joins; the next iteration
    expands those inside the wrap, where no forward reference is possible."""
    node = demand.select

    join_ptr = node.select_from
    while join_ptr:
        current_alias = join_ptr.alias or (
            str(join_ptr.table.chain[0]) if isinstance(join_ptr.table, ast.Field) else None
        )
        if current_alias == table_alias and isinstance(join_ptr.table, ast.Field):
            break
        join_ptr = join_ptr.next_join
    assert join_ptr is not None and isinstance(join_ptr.table, ast.Field), f"Table {table_alias} not found"

    used_fields = collect_fields_from_table(node, table_alias)
    for join_to_add in demand.joins_to_add.values():
        if join_to_add.from_table == table_alias:
            used_fields.update(str(f) for f in join_to_add.lazy_join.from_field)
            used_fields.update(join_to_add.fields_accessed.keys())
    if join_ptr.constraint:
        used_fields.update(collect_bare_fields(join_ptr.constraint))

    select_fields: list[ast.Expr] = [
        ast.Alias(alias=field, expr=ast.Field(chain=[table_alias, field])) for field in sorted(used_fields)
    ]
    subquery = ast.SelectQuery(
        select=select_fields,
        select_from=ast.JoinExpr(table=ast.Field(chain=list(join_ptr.table.chain)), alias=table_alias),
    )
    join_ptr.table = subquery
    join_ptr.alias = table_alias
    join_ptr.type = None

    if join_ptr.constraint:
        lazy_join_field_names = {
            v.lazy_join_type.field
            for v in demand.joins_to_add.values()
            if v.from_table == table_alias and v.lazy_join_type
        }
        collector = _LazyJoinTypeCollector(lazy_join_field_names, table_alias)
        collector.visit(join_ptr.constraint)
        join_ptr.constraint = cast(
            ast.JoinConstraint,
            _LazyJoinExpressionReplacer(table_alias, collector.lazy_join_type_ids).visit(join_ptr.constraint),
        )


def _group_property_swapper(context: HogQLContext) -> Optional["PropertySwapper"]:
    """Group/S3 property casts must be applied to recipe-built subtrees before their lazy references are rewritten
    away — group identity only exists pre-expansion. Mirrors the pipeline's pre-expansion group swap pass."""
    if context.property_swapper is None:
        return None
    from posthog.hogql.transforms.property_types import PropertySwapper  # noqa: PLC0415 — circular import

    return PropertySwapper(
        timezone=context.property_swapper.timezone,
        group_properties=context.property_swapper.group_properties,
        event_properties={},
        person_properties={},
        context=context,
        setTimeZones=False,
    )


def expand_lazy_references(
    node: _T_AST,
    dialect: HogQLDialect,
    stack: Optional[list[ast.SelectQuery]],
    context: HogQLContext,
    resolver_factory: ResolverFactory | None = None,
) -> _T_AST:
    """Expand all lazy tables and lazy joins in `node`. Returns the (re-resolved) expanded tree."""
    scopes = [s.type for s in stack if s.type is not None] if stack else None

    for _iteration in range(MAX_EXPANSION_ITERATIONS):
        demands = collect_lazy_demand(node, context, stack)
        if not demands:
            return node

        for demand in demands:
            _expand_scope(demand, context, dialect, resolver_factory)

        # The resolver requires an untyped tree and re-derives everything; it also re-emits diagnostics for nodes
        # that carry source locations, so roll those back to avoid duplicates from re-resolution.
        node = clone_expr(node, clear_types=True)
        notices, warnings, errors = len(context.notices), len(context.warnings), len(context.errors)
        node = resolve_types(node, context, dialect, scopes, resolver_factory=resolver_factory)
        del context.notices[notices:], context.warnings[warnings:], context.errors[errors:]
        HiddenAliasCollapser().visit(node)

    raise ResolutionError(f"Lazy table expansion did not terminate after {MAX_EXPANSION_ITERATIONS} iterations")
