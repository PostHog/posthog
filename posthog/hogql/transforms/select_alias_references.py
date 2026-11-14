"""Replaces each reference to a SELECT alias with a copy of the aliased expression.

HogQL lets a query name an expression once and use that name later in the same SELECT list, in WHERE, and in the
clauses after it. The name wins over a table column of the same name. ClickHouse resolves names the same way, so the
ClickHouse printer prints a reference as it is. The other SQL engines either reject such a reference or read the table
column of the same name, so for them the printed query must not depend on how the engine resolves an alias.
"""

from collections import Counter
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import replace
from typing import TypeVar

from posthog.hogql import ast
from posthog.hogql.constants import HogQLDialect
from posthog.hogql.context import HogQLContext
from posthog.hogql.database.schema.util.where_clause_extractor import is_nondeterministic_function
from posthog.hogql.errors import QueryError
from posthog.hogql.functions.mapping import find_hogql_aggregation
from posthog.hogql.visitor import CloningVisitor, TraversingVisitor

_T_AST = TypeVar("_T_AST", bound=ast.AST | None)

# Trino has its own lowering of alias references, and ClickHouse needs none.
ALIAS_INLINING_DIALECTS: frozenset[HogQLDialect] = frozenset({"postgres", "redshift", "mysql", "duckdb", "snowflake"})

# These engines resolve a reused alias themselves. A reference that is unsafe to copy stays a name there, so a query
# that the engine runs correctly on its own keeps running.
_NATIVE_ALIAS_REUSE_DIALECTS: frozenset[HogQLDialect] = frozenset({"duckdb", "snowflake", "redshift"})

# An alias that refers to an earlier alias twice doubles the copied expression at every link of such a chain.
MAX_INLINED_ALIAS_NODES = 50_000

# The clauses that filter or group the source rows, where no engine accepts an aggregate or a window function.
_SOURCE_ROW_CLAUSES = frozenset({"WHERE", "PREWHERE", "GROUP BY", "JOIN"})
# HAVING filters the groups, which exist before a window function runs.
_NO_WINDOW_CLAUSES = _SOURCE_ROW_CLAUSES | {"HAVING"}

_SUBQUERY_ADVICE = "Select it in a subquery and use it in the outer query."


class _SelectAliases(TraversingVisitor):
    """The aliases one SELECT query defines, keyed by the alias type that the resolver shares between an alias and
    every field that refers to it. A lambda argument or an ARRAY JOIN alias of the same name has another type."""

    def __init__(self, select: ast.SelectQuery) -> None:
        super().__init__()
        self.by_type: dict[int, ast.Alias] = {}
        self.output_positions: dict[int, int] = {}
        self.output_names: Counter[str] = Counter()
        self.selects_star = False
        self.scope = select.type
        self._uncopyable_calls: dict[int, str | None] = {}

        for position, column in enumerate(select.select, start=1):
            if isinstance(column, ast.Alias) and not column.hidden:
                self.output_names[column.alias] += 1
                if type(column.type) is ast.FieldAliasType:
                    self.output_positions[id(column.type)] = position
            elif isinstance(column, ast.Field):
                self.selects_star = self.selects_star or column.chain[-1] == "*"
                if isinstance(column.type, ast.FieldAliasType):
                    self.output_names[column.type.alias] += 1
        super().visit_select_query(select)

    def visit_alias(self, node: ast.Alias) -> None:
        if not node.hidden and type(node.type) is ast.FieldAliasType:
            self.by_type[id(node.type)] = node
        super().visit_alias(node)

    def visit_field(self, node: ast.Field) -> None:
        """A field holds no alias. The base visitor would walk its type, which is the whole scope of the query."""

    def visit_select_query(self, node: ast.SelectQuery) -> None:
        """A nested query has its own aliases."""

    def defines(self, node: ast.Alias) -> bool:
        return not node.hidden and id(node.type) in self.by_type

    def referenced(self, node: ast.Field) -> ast.Alias | None:
        if not isinstance(node.type, ast.FieldAliasType):
            return None
        return self.by_type.get(id(node.type))

    def uncopyable_call(self, alias: ast.Alias) -> str | None:
        """The name of a call that makes a copy of the alias differ from the alias, if it holds one."""
        key = id(alias.type)
        if key not in self._uncopyable_calls:
            finder = _UncopyableCallFinder(self)
            finder.visit(alias.expr)
            self._uncopyable_calls[key] = finder.found
        return self._uncopyable_calls[key]


class _UncopyableCallFinder(TraversingVisitor):
    def __init__(self, aliases: _SelectAliases) -> None:
        super().__init__()
        self.aliases = aliases
        self.found: str | None = None

    def visit_call(self, node: ast.Call) -> None:
        if self.found is not None:
            return
        if is_nondeterministic_function(node.name) or node.name.lower() == "arrayjoin":
            self.found = node.name
            return
        super().visit_call(node)

    def visit_field(self, node: ast.Field) -> None:
        alias = self.aliases.referenced(node)
        if alias is not None and self.found is None:
            self.found = self.aliases.uncopyable_call(alias)


class SelectAliasReferenceInliner(CloningVisitor):
    def __init__(self, context: HogQLContext, dialect: HogQLDialect) -> None:
        super().__init__(clear_types=False)
        self.context = context
        self.dialect = dialect
        self.aliases: _SelectAliases | None = None
        self.clause: str | None = None
        # The aliases under expansion with the field that refers to each, starting at the field in the query text.
        self.expanding: list[tuple[ast.Alias, ast.Field]] = []
        self.in_aggregate = False
        self.inlined_nodes = 0

    def visit(self, node: _T_AST) -> _T_AST:
        if self.expanding and node is not None:
            self.inlined_nodes += 1
            if self.inlined_nodes > MAX_INLINED_ALIAS_NODES:
                raise QueryError(
                    "The column aliases of this query expand into too many expressions. "
                    "Refer to fewer aliases from other aliases, or compute them in a subquery."
                )
        return super().visit(node)

    def visit_select_query(self, node: ast.SelectQuery) -> ast.SelectQuery:
        outer = (self.aliases, self.clause, self.expanding, self.in_aggregate)
        self.aliases, self.clause, self.expanding, self.in_aggregate = _SelectAliases(node), None, [], False
        try:
            return replace(
                node,
                ctes={name: self.visit(cte) for name, cte in node.ctes.items()} if node.ctes else None,
                select_from=self._visit_clause("JOIN", node.select_from),
                select=[self._visit_select_column(column) for column in node.select],
                array_join_list=([self.visit(expr) for expr in node.array_join_list] if node.array_join_list else None),
                where=self._visit_clause("WHERE", node.where),
                prewhere=self._visit_clause("PREWHERE", node.prewhere),
                having=self._visit_clause("HAVING", node.having),
                qualify=self.visit(node.qualify),
                group_by=(
                    [self._visit_group_key(key, node.group_by_mode) for key in node.group_by] if node.group_by else None
                ),
                order_by=[self._visit_order(order) for order in node.order_by] if node.order_by else None,
                interpolate=([self.visit(expr) for expr in node.interpolate] if node.interpolate is not None else None),
                limit_by=self.visit(node.limit_by),
                limit=self.visit(node.limit),
                offset=self.visit(node.offset),
                window_exprs=(
                    {name: self.visit(expr) for name, expr in node.window_exprs.items()} if node.window_exprs else None
                ),
            )
        finally:
            self.aliases, self.clause, self.expanding, self.in_aggregate = outer

    def visit_alias(self, node: ast.Alias) -> ast.Expr:
        if self.aliases is not None and self.aliases.defines(node):
            # None of these engines can define an alias inside an expression, and every reference holds a copy.
            return self.visit(node.expr)
        return super().visit_alias(node)

    def visit_field(self, node: ast.Field) -> ast.Expr:
        alias = self.aliases.referenced(node) if self.aliases is not None else None
        if alias is None:
            return super().visit_field(node)
        return self._inline(node, alias)

    def visit_call(self, node: ast.Call) -> ast.Expr:
        if find_hogql_aggregation(node.name) is None:
            return super().visit_call(node)
        if self.expanding:
            if self.in_aggregate:
                raise self._misplaced("an aggregate function", "another aggregate function")
            if self.clause in _SOURCE_ROW_CLAUSES:
                advice = "Filter on it in HAVING instead." if self.clause in {"WHERE", "PREWHERE"} else None
                raise self._misplaced("an aggregate function", self.clause, advice)
        was_in_aggregate, self.in_aggregate = self.in_aggregate, True
        try:
            return super().visit_call(node)
        finally:
            self.in_aggregate = was_in_aggregate

    def visit_window_function(self, node: ast.WindowFunction) -> ast.Expr:
        if self.expanding and self.clause in _NO_WINDOW_CLAUSES:
            raise self._misplaced("a window function", self.clause, _SUBQUERY_ADVICE)
        return super().visit_window_function(node)

    def _visit_select_column(self, column: ast.Expr) -> ast.Expr:
        if self.aliases is None:
            return self.visit(column)
        if isinstance(column, ast.Alias) and self.aliases.defines(column):
            return replace(column, expr=self.visit(column.expr))
        if isinstance(column, ast.Field) and (alias := self.aliases.referenced(column)) is not None:
            inlined = self._inline(column, alias)
            if isinstance(inlined, ast.Field) and inlined.type is column.type:
                return inlined
            # A bare copy would lose the name of the column in the result.
            return ast.Alias(
                alias=alias.alias,
                expr=inlined,
                type=ast.FieldAliasType(alias=alias.alias, type=inlined.type or ast.UnknownType()),
                start=column.start,
                end=column.end,
            )
        return self.visit(column)

    def _visit_group_key(self, key: ast.Expr, group_by_mode: str | None) -> ast.Expr:
        with self._clause("GROUP BY"):
            aliases = self.aliases
            if (
                aliases is not None
                and group_by_mode is None
                and not aliases.selects_star
                and isinstance(key, ast.Field)
                and (alias := aliases.referenced(key)) is not None
                and (position := aliases.output_positions.get(id(alias.type))) is not None
            ):
                # The copy is discarded. It exists to reject an alias that GROUP BY cannot use.
                self._expand(alias, key)
                # These engines look for a bare GROUP BY name among the table columns before the SELECT aliases, and a
                # copy of the expression binds its own query parameters, which does not match the SELECT column on an
                # engine that binds on the server. The position of the column has neither problem.
                return ast.Constant(value=position, type=ast.IntegerType(nullable=False))
            return self.visit(key)

    def _visit_order(self, order: ast.OrderExpr) -> ast.OrderExpr:
        aliases = self.aliases
        if (
            aliases is not None
            and isinstance(order.expr, ast.Field)
            and (alias := aliases.referenced(order.expr)) is not None
            and id(alias.type) in aliases.output_positions
            and aliases.output_names[alias.alias] == 1
        ):
            # Every one of these engines looks for a bare ORDER BY name among the SELECT aliases first.
            return replace(order, expr=super().visit_field(order.expr), with_fill=self.visit(order.with_fill))
        with self._clause("ORDER BY"):
            return self.visit(order)

    def _visit_clause(self, clause: str, node: _T_AST) -> _T_AST:
        with self._clause(clause):
            return self.visit(node)

    @contextmanager
    def _clause(self, clause: str) -> Iterator[None]:
        outer, self.clause = self.clause, clause
        try:
            yield
        finally:
            self.clause = outer

    def _inline(self, node: ast.Field, alias: ast.Alias) -> ast.Expr:
        assert self.aliases is not None
        call = self.aliases.uncopyable_call(alias)
        if call is None:
            return self._expand(alias, node)
        is_select_column = id(alias.type) in self.aliases.output_positions
        if is_select_column and self.dialect in _NATIVE_ALIAS_REUSE_DIALECTS:
            return super().visit_field(node)
        reason = "returns more than one row" if call.lower() == "arrayjoin" else "returns a new value each time it runs"
        named, reference = self.expanding[0] if self.expanding else (alias, node)
        raise QueryError(
            f'Alias "{named.alias}" calls {call}(), which {reason}, '
            f"so the query can't use the alias a second time. {_SUBQUERY_ADVICE}",
            node=reference,
        )

    def _expand(self, alias: ast.Alias, reference: ast.Field) -> ast.Expr:
        self.expanding.append((alias, reference))
        try:
            return self.visit(alias.expr)
        finally:
            self.expanding.pop()

    def _misplaced(self, held: str, place: str, advice: str | None = None) -> QueryError:
        named, reference = self.expanding[0]
        name = named.alias
        message = f'Alias "{name}" holds {held}, so {place} can\'t use it.'
        if advice:
            message += f" {advice}"
        column = self._shadowed_column(name)
        if column:
            message += f" To use the column instead, write {column}."
        return QueryError(message, node=reference)

    def _shadowed_column(self, name: str) -> str | None:
        scope = self.aliases.scope if self.aliases is not None else None
        if scope is None:
            return None
        for table_name, table_type in scope.tables.items():
            if table_type.has_child(name, self.context):
                return f"{table_name}.{name}"
        return None


def inline_select_alias_references(node: _T_AST, context: HogQLContext, dialect: HogQLDialect) -> _T_AST:
    if dialect not in ALIAS_INLINING_DIALECTS:
        return node
    with context.timings.measure("inline_select_alias_references"):
        return SelectAliasReferenceInliner(context, dialect).visit(node)
