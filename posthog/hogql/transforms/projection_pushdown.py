from collections import defaultdict
from dataclasses import field
from typing import cast

from posthog.hogql import ast
from posthog.hogql.base import _T_AST
from posthog.hogql.context import HogQLContext
from posthog.hogql.transforms.exported_properties import narrow_exported_properties
from posthog.hogql.visitor import TraversingVisitor

from posthog.dataclasses import frozen

SubqueryNode = ast.SelectQuery | ast.SelectSetQuery

# Demand flows top-down, but a CTE's reader can be visited after the CTE, so one pass can leave a column's readers
# incomplete. Each pass adds what the last one learned; the walk stops when a pass adds nothing. A query that still
# changes after this many passes is pruned with what was collected and not narrowed.
_MAX_COLLECTION_PASSES = 50


@frozen(frozen=False)
class ColumnReads:
    """How the readers of one subquery column use it. `whole` is set by any read of the column itself; `keys` are the
    first keys of `column.<key>` reads, with the reads themselves in `sites`, by the hidden alias the resolver wraps
    every field in."""

    whole: bool = False
    keys: set[str] = field(default_factory=set)
    sites: dict[int, tuple[ast.Alias, ast.Field]] = field(default_factory=dict)


class ProjectionPushdownOptimizer(TraversingVisitor):
    """
    Top-down projection pushdown optimizer that prunes unused asterisk-expanded columns from subqueries, and records
    how each subquery column is read so `exported_properties` can export only the keys read of a properties blob.

    Algorithm Overview:
    ──────────────────
    This optimizer makes several top-down passes through the query tree: the collecting passes only gather demands,
    repeated until a pass learns nothing new, and the final pass prunes with the complete demand set. A CTE can be
    consumed by nodes visited after it — notably sibling UNION branches — so pruning must wait for the full walk.

    Each pass runs these phases per query:

    Phase 1 - Register: Map subquery types to AST nodes for demand tracking
    Phase 2 - Collect: Gather column demands from WHERE/GROUP BY/ORDER BY/etc
    Phase 3 - Propagate: For demanded columns, visit their source to propagate to child queries
    Phase 4 - Recurse: Visit child subqueries (repeat phases 1-4)
    Phase 5 - Prune: Remove unreferenced asterisk columns from this query (final pass only)

    A column that a query exports as it is (`SELECT properties FROM sub`) is not a read of it: how the column is used
    is its own readers' business, so phase 3 hands their reads down to the child column instead.
    """

    def __init__(self, context: HogQLContext | None = None):
        super().__init__()
        self.context = context
        self.demands: dict[int, set[str]] = defaultdict(set)
        self.reads: dict[tuple[int, str], ColumnReads] = defaultdict(ColumnReads)
        self.subquery_map: dict[int, SubqueryNode] = {}
        # The select columns that export a child column as it is, by the child column they export
        self.passthrough_parents: dict[tuple[int, str], dict[tuple[int, str], tuple[SubqueryNode, str]]] = defaultdict(
            dict
        )
        self.roots: set[int] = set()
        self.recursive_cte_exprs: set[int] = set()
        self.converged: bool = False
        self.union_of: dict[int, ast.SelectSetQuery] = {}
        # Branches of a set query that compares rows (anything but UNION ALL)
        self.strict_set_branches: set[int] = set()
        # True during the collecting passes; gates pruning to the final one (see class docstring)
        self.collecting: bool = False
        self._alias_stack: list[ast.Alias] = []
        self._alias_references: set[int] = set()

    def optimize(self, node: SubqueryNode) -> SubqueryNode:
        self.roots = self._root_ids(node)
        self.collecting = True
        signature: object = None
        for _ in range(_MAX_COLLECTION_PASSES):
            self.visit(node)
            new_signature = self._demand_signature()
            if new_signature == signature:
                self.converged = True
                break
            signature = new_signature
        self.collecting = False
        return cast(SubqueryNode, self.visit(node))

    def _root_ids(self, node: SubqueryNode) -> set[int]:
        if isinstance(node, ast.SelectSetQuery):
            ids = {id(node)}
            for query in self.union_queries(node):
                ids |= self._root_ids(query)
            return ids
        return {id(node)}

    def _demand_signature(self) -> object:
        return (
            tuple(sorted((key, tuple(sorted(names))) for key, names in self.demands.items())),
            tuple(sorted((key, reads.whole, tuple(sorted(reads.keys))) for key, reads in self.reads.items())),
        )

    def visit_select_query(self, node: ast.SelectQuery) -> ast.SelectQuery:
        # Phase 1: Register subqueries and CTEs for demand tracking
        if node.ctes:
            self._register_ctes(node.ctes)
        if node.select_from:
            self._register_subqueries(node.select_from)

        # Phase 2: Collect column demands from query clauses
        enclosing_alias_references = self._alias_references
        self._alias_references = set()
        compares_rows = self.compares_rows(node)
        for expr in node.select:
            if compares_rows:
                self._read_whole(node, expr)
                continue
            if self._is_from_asterisk(expr):
                continue
            passthrough = self._passthrough_source(expr)
            if passthrough is None:
                self.visit(expr)
            else:
                self._demand_passthrough(node, expr, passthrough)

        if node.where:
            self.visit(node.where)
        if node.prewhere:
            self.visit(node.prewhere)
        if node.group_by:
            for expr in node.group_by:
                self.visit(expr)
        if node.having:
            self.visit(node.having)
        if node.qualify:
            self.visit(node.qualify)
        if node.order_by:
            for expr in node.order_by:
                self.visit(expr)
        if node.limit:
            self.visit(node.limit)
        if node.offset:
            self.visit(node.offset)
        if node.limit_by:
            self.visit(node.limit_by)
        if node.array_join_list:
            for expr in node.array_join_list:
                self.visit(expr)
        if node.window_exprs:
            for window_expr in node.window_exprs.values():
                self.visit(window_expr)

        if node.select_from:
            self._collect_join_constraint_column_demands(node.select_from)

        # A clause that names a select column by its alias (`ORDER BY p`) reads the column's value itself
        for expr in node.select:
            if expr.type is not None and id(expr.type) in self._alias_references:
                passthrough = self._passthrough_source(expr)
                if passthrough is not None:
                    child, child_name = passthrough
                    self.reads[(id(child), child_name)].whole = True
                else:
                    col_name = self._get_column_name(expr)
                    if col_name is not None:
                        self.reads[(id(node), col_name)].whole = True
        self._alias_references = enclosing_alias_references

        # Phase 3: Propagate parent demands down to child subqueries
        self._propagate_demands_to_children(node)

        # Phase 4: Recursively visit and optimize child subqueries and CTEs
        if node.ctes:
            self._visit_ctes(node.ctes)
        if node.select_from:
            self.visit(node.select_from)

        # Phase 5: Prune unreferenced asterisk columns from this query and CTEs (final pass only)
        if not self.collecting:
            self._prune_columns(node)
            if node.ctes:
                self._prune_cte_columns(node.ctes)

        return node

    def visit_select_set_query(self, node: ast.SelectSetQuery) -> ast.SelectSetQuery:
        """
        Handle UNION/INTERSECT/EXCEPT queries.

        All branches must have identical column structure, so we:
        1. Propagate parent demands to all branches uniformly
        2. Visit each branch to apply pruning
        """
        strict = any(not set_node.set_operator.startswith("UNION ALL") for set_node in node.subsequent_select_queries)
        for query in self.union_queries(node):
            self.union_of[id(query)] = node
            if strict:
                self.strict_set_branches.add(id(query))

        # Propagate parent demands to all branches uniformly
        self._propagate_demands_to_union_branches(node)

        # Visit each branch
        self.visit(node.initial_select_query)
        for set_node in node.subsequent_select_queries:
            self.visit(set_node.select_query)

        return node

    def union_queries(self, node: ast.SelectSetQuery) -> list[SubqueryNode]:
        return [node.initial_select_query, *(set_node.select_query for set_node in node.subsequent_select_queries)]

    def _is_from_asterisk(self, expr: ast.Expr) -> bool:
        """Check if an expression was expanded from asterisk"""
        if isinstance(expr, ast.Alias):
            expr = expr.expr  # whoops - we want to take the Field from the Alias
        if isinstance(expr, ast.Field):
            return expr.from_asterisk
        return False

    def _passthrough_source(self, expr: ast.Expr) -> tuple[SubqueryNode, str] | None:
        """The child query and column name behind a select column that exports a subquery or CTE column as it is."""
        source = self._unwrap_aliases(expr)
        if not isinstance(source, ast.Field) or not isinstance(source.type, ast.FieldType):
            return None
        child = self.child_for(source.type.table_type)
        if child is None:
            return None
        return child, source.type.name

    def _unwrap_aliases(self, expr: ast.Expr) -> ast.Expr:
        while isinstance(expr, ast.Alias):
            expr = expr.expr
        return expr

    def compares_rows(self, node: ast.SelectQuery) -> bool:
        """Whether the select's rows are compared whole, so every column's value counts"""
        return node.distinct or id(node) in self.strict_set_branches

    def _demand_passthrough(self, node: ast.SelectQuery, expr: ast.Expr, passthrough: tuple[SubqueryNode, str]) -> None:
        child, child_name = passthrough
        self.demands[id(child)].add(child_name)
        col_name = self._get_column_name(expr)
        if col_name is not None:
            self.passthrough_parents[(id(child), child_name)][(id(node), col_name)] = (node, col_name)

    def _propagate_demands_to_children(self, node: ast.SelectQuery) -> None:
        """
        Propagate parent demands to child subqueries.

        When a parent query demands a column from us, we need to visit that column's
        source expression to propagate the demand down to our child subqueries. A column
        exported as it is hands the parent's reads of it down to the child column.

        A query without parent demands is either the query's output, which needs every
        column as it is, or a subquery nobody reads a column of, which only has to keep
        its rows.
        """
        demanded_from_this = self.demands.get(id(node))
        if not demanded_from_this:
            if id(node) in self.roots or id(node) not in self._registered_ids():
                # The query's output, or a select inside an expression: every column is read as it is
                for expr in node.select:
                    self._read_whole(node, expr)
            elif not self.collecting:
                # Only the final pass knows that nobody reads the column; a reader may still turn up while collecting
                self._keep_unread_subquery_rows(node)
            return

        for col_name in demanded_from_this:
            for expr in node.select:
                if self._get_column_name(expr) != col_name:
                    continue
                passthrough = self._passthrough_source(expr)
                if passthrough is None:
                    self.visit(expr)
                    break
                child, child_name = passthrough
                self._demand_passthrough(node, expr, passthrough)
                parent_reads = self.reads.get((id(node), col_name))
                if parent_reads is not None:
                    child_reads = self.reads[(id(child), child_name)]
                    child_reads.whole = child_reads.whole or parent_reads.whole
                    child_reads.keys.update(parent_reads.keys)
                break

    def _keep_unread_subquery_rows(self, node: ast.SelectQuery) -> None:
        if self.compares_rows(node) or id(node) in self.union_of:
            # Every asterisk column stays: a row comparison counts them, and set query branches must line up
            for expr in node.select:
                if self._is_from_asterisk(expr):
                    self.visit(expr)
            return
        # Nobody reads a column, so the asterisk columns would only be computed and dropped. An explicit column keeps
        # the rows; without one, the cheapest asterisk column does, and a JSON blob is the most expensive to compute.
        explicit_columns = [expr for expr in node.select if not self._is_from_asterisk(expr)]
        asterisk_columns = [expr for expr in node.select if self._is_from_asterisk(expr)]
        if explicit_columns:
            col_name = self._get_column_name(explicit_columns[0])
            if col_name is not None:
                self.demands[id(node)].add(col_name)
            return
        if not asterisk_columns:
            return
        keep = next((expr for expr in asterisk_columns if not self._is_json_blob(expr)), asterisk_columns[0])
        col_name = self._get_column_name(keep)
        if col_name is not None:
            self.demands[id(node)].add(col_name)
        self._read_whole(node, keep)

    def _registered_ids(self) -> set[int]:
        return {id(query) for query in self.subquery_map.values()}

    def _read_whole(self, node: ast.SelectQuery, expr: ast.Expr) -> None:
        passthrough = self._passthrough_source(expr)
        if passthrough is None:
            self.visit(expr)
            return
        child, child_name = passthrough
        self._demand_passthrough(node, expr, passthrough)
        self.reads[(id(child), child_name)].whole = True

    def _is_json_blob(self, expr: ast.Expr) -> bool:
        source = self._unwrap_aliases(expr)
        if not isinstance(source, ast.Field) or source.type is None or self.context is None:
            return False
        try:
            return isinstance(source.type.resolve_constant_type(self.context), ast.StringJSONType)
        except Exception:
            return False

    def _propagate_demands_to_union_branches(self, node: ast.SelectSetQuery) -> None:
        """
        Propagate demands from parent to all UNION/INTERSECT/EXCEPT branches.

        Since all branches must have identical column structure, we propagate
        the same demands to all of them.
        """
        demanded_from_this = self.demands.get(id(node))
        if not demanded_from_this:
            return

        for query in self.union_queries(node):
            self.demands[id(query)].update(demanded_from_this)
            for col_name in demanded_from_this:
                parent_reads = self.reads.get((id(node), col_name))
                if parent_reads is None:
                    continue
                branch_reads = self.reads[(id(query), col_name)]
                branch_reads.whole = branch_reads.whole or parent_reads.whole
                branch_reads.keys.update(parent_reads.keys)

    def _register_subqueries(self, from_clause: ast.JoinExpr) -> None:
        """Register all subqueries in FROM clause before collecting demands"""
        if from_clause.type is None:
            return

        if isinstance(from_clause.table, ast.SelectQuery):
            self._register_subquery(from_clause.table, cast(ast.SelectQueryType, from_clause.type))
        elif isinstance(from_clause.table, ast.SelectSetQuery):
            self._register_union_subquery(from_clause.table, cast(ast.SelectSetQueryType, from_clause.type))

        if from_clause.next_join:
            self._register_subqueries(from_clause.next_join)

    def _register_subquery(
        self,
        subquery: ast.SelectQuery,
        type_annotation: ast.BaseTableType | ast.SelectSetQueryType | ast.SelectQueryType | ast.SelectQueryAliasType,
    ) -> None:
        """Map type to subquery node for demand tracking"""
        # Map both the type and the inner SelectQueryType if it's an alias
        self.subquery_map[id(type_annotation)] = subquery
        if isinstance(type_annotation, ast.SelectQueryAliasType) and type_annotation.select_query_type:
            self.subquery_map[id(type_annotation.select_query_type)] = subquery

    def _register_union_subquery(
        self,
        union_query: ast.SelectSetQuery,
        type_annotation: ast.BaseTableType | ast.SelectSetQueryType | ast.SelectQueryType | ast.SelectQueryAliasType,
    ) -> None:
        """Map type to union subquery node for demand tracking"""
        self.subquery_map[id(type_annotation)] = union_query

        # Also register with the inner SelectSetQueryType for both aliased and non-aliased cases
        if isinstance(type_annotation, ast.SelectQueryAliasType):
            # Aliased: register with the inner select_query_type
            if type_annotation.select_query_type:
                self.subquery_map[id(type_annotation.select_query_type)] = union_query
        elif isinstance(type_annotation, ast.SelectSetQueryType):
            # Non-aliased: the type_annotation IS the SelectSetQueryType, but we also need to
            # register with the first branch's type for field resolution
            if type_annotation.types:
                self.subquery_map[id(type_annotation.types[0])] = union_query

    def _get_subquery(self, table_type: ast.Type) -> SubqueryNode | None:
        """Retrieve subquery by type"""
        return self.subquery_map.get(id(table_type))

    def child_for(self, table_type: ast.Type) -> SubqueryNode | None:
        """The registered subquery or CTE query a field's table type refers to, if any"""
        if isinstance(table_type, ast.SelectQueryType | ast.SelectQueryAliasType | ast.SelectSetQueryType):
            return self._get_subquery(table_type)
        if isinstance(table_type, ast.CTETableType | ast.CTETableAliasType):
            # For CTE types, get the underlying SelectQueryType and demand from it
            cte_select_query_type = (
                table_type.cte_table_type.select_query_type
                if isinstance(table_type, ast.CTETableAliasType)
                else table_type.select_query_type
            )
            return self._get_subquery(cte_select_query_type)
        return None

    def visit_alias(self, node: ast.Alias) -> None:
        self._alias_stack.append(node)
        try:
            super().visit_alias(node)
        finally:
            self._alias_stack.pop()

    def visit_field(self, node: ast.Field) -> ast.Field:
        """Record demand when field references subquery or CTE column"""
        field_type = node.type
        if isinstance(field_type, ast.FieldAliasType):
            self._alias_references.add(id(field_type))
            return node

        # A property read (`col.some_key`) still demands its base blob column. Its node type is a
        # PropertyType wrapping the base FieldType, so unwrap to that base — otherwise the column is
        # never recorded as demanded and gets pruned from an asterisk-expanded subquery/CTE, leaving a
        # dangling reference that later blows up property lowering.
        property_type: ast.PropertyType | None = None
        if isinstance(field_type, ast.PropertyType):
            property_type = field_type
            field_type = field_type.field_type

        # Handle both FieldType and ExpressionFieldType
        if not isinstance(field_type, ast.FieldType | ast.ExpressionFieldType):
            return node

        child = self.child_for(field_type.table_type)
        if child is None:
            return node
        self.demands[id(child)].add(field_type.name)
        reads = self.reads[(id(child), field_type.name)]
        if self._is_key_read(property_type, node):
            assert property_type is not None
            reads.keys.add(cast(str, property_type.chain[0]))
            reads.sites[id(self._alias_stack[-1])] = (self._alias_stack[-1], node)
        else:
            reads.whole = True
        return node

    def _is_key_read(self, property_type: ast.PropertyType | None, node: ast.Field) -> bool:
        """A `column.<key>` read the resolver wrapped in a hidden alias, which `exported_properties` can re-point.
        A read of the JSON text itself, or of a position, needs the blob."""
        if property_type is None or property_type.as_json or not property_type.chain:
            return False
        if not isinstance(property_type.chain[0], str):
            return False
        return bool(self._alias_stack) and self._alias_stack[-1].expr is node

    def _collect_join_constraint_column_demands(self, from_clause: ast.JoinExpr) -> None:
        """Collect demands from JOIN constraints"""
        if from_clause.constraint and from_clause.constraint.expr:
            # Visit the constraint expression (not the JoinConstraint wrapper)
            self.visit(from_clause.constraint.expr)

        if from_clause.next_join:
            self._collect_join_constraint_column_demands(from_clause.next_join)

    def _prune_columns(self, node: ast.SelectQuery) -> None:
        """Prune asterisk-expanded columns that aren't demanded"""
        demanded = self.demands.get(id(node))
        if not demanded or self.compares_rows(node):
            return

        pruned_select = []
        for expr in node.select:
            if not self._is_from_asterisk(expr):
                # Keep explicitly written columns
                pruned_select.append(expr)
            else:
                # Keep demanded asterisk columns
                col_name = self._get_column_name(expr)
                if col_name and col_name in demanded:
                    pruned_select.append(expr)

        if pruned_select:
            # Collect the names of asterisk columns we're about to drop
            dropped_names: set[str] = set()
            for expr in node.select:
                if self._is_from_asterisk(expr) and expr not in pruned_select:
                    col_name = self._get_column_name(expr)
                    if col_name:
                        dropped_names.add(col_name)

            node.select = pruned_select
            # Remove dropped asterisk columns from SelectQueryType.columns.
            # Without this, stale LazyTableType references on pruned columns
            # leak through type traversal (e.g. CTETableType → SelectQueryType.columns)
            # and cause KeyErrors in the lazy table resolver.
            if dropped_names and isinstance(node.type, ast.SelectQueryType):
                node.type.columns = {k: v for k, v in node.type.columns.items() if k not in dropped_names}

    def _get_column_name(self, expr: ast.Expr) -> str | None:
        """Extract column name from expression"""
        if isinstance(expr, ast.Field):
            return str(expr.chain[-1]) if expr.chain else None
        elif isinstance(expr, ast.Alias):
            return expr.alias
        return None

    def _register_ctes(self, ctes: dict[str, ast.CTE]) -> None:
        """Register all CTEs for demand tracking"""
        for cte in ctes.values():
            if isinstance(cte.expr, ast.SelectQuery | ast.SelectSetQuery):
                # Map the CTE's SelectQueryType to its expr for demand tracking
                if cte.expr.type:
                    self.subquery_map[id(cte.expr.type)] = cte.expr
                if cte.recursive:
                    self.recursive_cte_exprs.add(id(cte.expr))

    def _visit_ctes(self, ctes: dict[str, ast.CTE]) -> None:
        """Visit and optimize CTEs. A CTE can only read the ones defined before it, so the last one goes first and
        its demands reach the earlier ones in the same pass."""
        for cte in reversed(list(ctes.values())):
            if isinstance(cte.expr, ast.SelectQuery | ast.SelectSetQuery):
                self.visit(cte.expr)

    def _prune_cte_columns(self, ctes: dict[str, ast.CTE]) -> None:
        """Prune asterisk-expanded columns from CTEs that aren't demanded"""
        for cte in ctes.values():
            if isinstance(cte.expr, ast.SelectQuery):
                self._prune_columns(cte.expr)


def pushdown_projections(node: _T_AST, context: HogQLContext, *, narrow_properties: bool = False) -> _T_AST:
    """Prune unused columns from asterisk expansions in subqueries. With `narrow_properties`, a subquery that exports
    the events `properties` blob exports only the keys its readers read (see `exported_properties`)."""
    if not isinstance(node, (ast.SelectQuery, ast.SelectSetQuery)):
        return node
    optimizer = ProjectionPushdownOptimizer(context)
    result = optimizer.optimize(node)
    if narrow_properties and optimizer.converged:
        narrow_exported_properties(optimizer, context)
    return cast(_T_AST, result)
