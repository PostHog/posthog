from typing import List, Optional

from posthog.hogql import ast
from posthog.hogql.database import database
from posthog.hogql.visitor import TraversingVisitor

# https://github.com/ClickHouse/ClickHouse/issues/23194 - "Describe how identifiers in SELECT queries are resolved"


def resolve_symbols(node: ast.Expr, scope: Optional[ast.SelectQuerySymbol] = None):
    Resolver(scope=scope).visit(node)


class ResolverException(ValueError):
    pass


class Resolver(TraversingVisitor):
    """The Resolver visits an AST and assigns Symbols to the nodes."""

    def __init__(self, scope: Optional[ast.SelectQuerySymbol] = None):
        # Each SELECT query creates a new scope. Store all of them in a list as we traverse the tree.
        self.scopes: List[ast.SelectQuerySymbol] = [scope] if scope else []

    def visit_select_query(self, node):
        """Visit each SELECT query or subquery."""
        if node.symbol is not None:
            return

        # This symbol keeps track of all joined tables and other field aliases that are in scope.
        node.symbol = ast.SelectQuerySymbol()

        # Each SELECT query is a new scope in field name resolution.
        self.scopes.append(node.symbol)

        # Visit all the FROM and JOIN clauses, and register the tables into the scope. See visit_join_expr below.
        if node.select_from:
            self.visit(node.select_from)

        # Visit all the SELECT 1,2,3 columns. Mark each for export in "columns" to make this work:
        # SELECT e.event, e.timestamp from (SELECT event, timestamp FROM events) AS e
        for expr in node.select or []:
            self.visit(expr)
            if isinstance(expr.symbol, ast.FieldAliasSymbol):
                node.symbol.columns[expr.symbol.name] = expr.symbol
            elif isinstance(expr.symbol, ast.FieldSymbol):
                node.symbol.columns[expr.symbol.name] = expr.symbol
            elif isinstance(expr, ast.Alias):
                node.symbol.columns[expr.alias] = expr.symbol

        if node.where:
            self.visit(node.where)
        if node.prewhere:
            self.visit(node.prewhere)
        if node.having:
            self.visit(node.having)
        for expr in node.group_by or []:
            self.visit(expr)
        for expr in node.order_by or []:
            self.visit(expr)
        for expr in node.limit_by or []:
            self.visit(expr)
        self.visit(node.limit)
        self.visit(node.offset)

        self.scopes.pop()

        return node.symbol

    def visit_join_expr(self, node):
        """Visit each FROM and JOIN table or subquery."""

        if node.symbol is not None:
            return
        if len(self.scopes) == 0:
            raise ResolverException("Unexpected JoinExpr outside a SELECT query")
        scope = self.scopes[-1]

        if isinstance(node.table, ast.Field):
            table_name = node.table.chain[0]
            table_alias = node.alias or table_name
            if table_alias in scope.tables:
                raise ResolverException(f'Already have joined a table called "{table_alias}". Can\'t redefine.')

            if database.has_table(table_name):
                node.table.symbol = ast.TableSymbol(table=database.get_table(table_name))
                if table_alias == table_name:
                    node.symbol = node.table.symbol
                else:
                    node.symbol = ast.TableAliasSymbol(name=table_alias, table=node.table.symbol)
                scope.tables[table_alias] = node.symbol
            else:
                raise ResolverException(f'Unknown table "{table_name}".')

        elif isinstance(node.table, ast.SelectQuery):
            node.table.symbol = self.visit(node.table)
            if node.alias is not None:
                if node.alias in scope.tables:
                    raise ResolverException(f'Already have joined a table called "{node.alias}". Can\'t redefine.')
                node.symbol = ast.SelectQueryAliasSymbol(name=node.alias, symbol=node.table.symbol)
                scope.tables[node.alias] = node.symbol
            else:
                node.symbol = node.table.symbol
                scope.anonymous_tables.append(node.symbol)

        else:
            raise ResolverException(f"JoinExpr with table of type {type(node.table).__name__} not supported")

        self.visit(node.constraint)
        self.visit(node.next_join)

    def visit_alias(self, node: ast.Alias):
        """Visit column aliases. SELECT 1, (select 3 as y) as x."""
        if node.symbol is not None:
            return

        if len(self.scopes) == 0:
            raise ResolverException("Aliases are allowed only within SELECT queries")
        scope = self.scopes[-1]
        if node.alias in scope.aliases:
            raise ResolverException(f"Cannot redefine an alias with the name: {node.alias}")
        if node.alias == "":
            raise ResolverException("Alias cannot be empty")

        self.visit(node.expr)
        if not node.expr.symbol:
            raise ResolverException(f"Cannot alias an expression without a symbol: {node.alias}")
        node.symbol = ast.FieldAliasSymbol(name=node.alias, symbol=node.expr.symbol)
        scope.aliases[node.alias] = node.symbol

    def visit_call(self, node: ast.Call):
        """Visit function calls."""
        if node.symbol is not None:
            return
        arg_symbols: List[ast.Symbol] = []
        for arg in node.args:
            self.visit(arg)
            if arg.symbol is not None:
                arg_symbols.append(arg.symbol)
        node.symbol = ast.CallSymbol(name=node.name, args=arg_symbols)

    def visit_field(self, node):
        """Visit a field such as ast.Field(chain=["e", "properties", "$browser"])"""
        if node.symbol is not None:
            return
        if len(node.chain) == 0:
            raise Exception("Invalid field access with empty chain")

        # Only look for fields in the last SELECT scope, instead of all previous scopes.
        # That's because ClickHouse does not support subqueries accessing "x.event". This is forbidden:
        # - "SELECT event, (select count() from events where event = x.event) as c FROM events x where event = '$pageview'",
        # But this is supported:
        # - "SELECT t.big_count FROM (select count() + 100 as big_count from events) as t JOIN events e ON (e.event = t.event)",
        scope = self.scopes[-1]

        symbol: Optional[ast.Symbol] = None
        name = node.chain[0]

        # If the field contains at least two parts, the first might be a table.
        if len(node.chain) > 1 and name in scope.tables:
            symbol = scope.tables[name]

        if name == "*" and len(node.chain) == 1:
            table_count = len(scope.anonymous_tables) + len(scope.tables)
            if table_count == 0:
                raise ResolverException("Cannot use '*' when there are no tables in the query")
            if table_count > 1:
                raise ResolverException("Cannot use '*' without table name when there are multiple tables in the query")
            table = scope.anonymous_tables[0] if len(scope.anonymous_tables) > 0 else list(scope.tables.values())[0]
            symbol = ast.AsteriskSymbol(table=table)

        if not symbol:
            symbol = lookup_field_by_name(scope, name)
        if not symbol:
            raise ResolverException(f"Unable to resolve field: {name}")

        # Recursively resolve the rest of the chain until we can point to the deepest node.
        loop_symbol = symbol
        for child_name in node.chain[1:]:
            loop_symbol = loop_symbol.get_child(child_name)
            if loop_symbol is None:
                raise ResolverException(
                    f"Cannot resolve symbol {'.'.join(node.chain)}. Unable to resolve {child_name} on {name}"
                )
        node.symbol = loop_symbol

    def visit_constant(self, node):
        """Visit a constant"""
        if node.symbol is not None:
            return
        node.symbol = ast.ConstantSymbol(value=node.value)


def lookup_field_by_name(scope: ast.SelectQuerySymbol, name: str) -> Optional[ast.Symbol]:
    """Looks for a field in the scope's list of aliases and children for each joined table."""
    if name in scope.aliases:
        return scope.aliases[name]
    else:
        named_tables = [table for table in scope.tables.values() if table.has_child(name)]
        anonymous_tables = [table for table in scope.anonymous_tables if table.has_child(name)]
        tables_with_field = named_tables + anonymous_tables

        if len(tables_with_field) > 1:
            raise ResolverException(f"Ambiguous query. Found multiple sources for field: {name}")
        elif len(tables_with_field) == 1:
            return tables_with_field[0].get_child(name)
        return None
