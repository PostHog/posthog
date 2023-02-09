from typing import List, Optional

from posthog.hogql import ast
from posthog.hogql.visitor import TraversingVisitor

# https://github.com/ClickHouse/ClickHouse/issues/23194 - "Describe how identifiers in SELECT queries are resolved"


def resolve_symbols(node: ast.SelectQuery):
    Resolver().visit(node)


class ResolverException(ValueError):
    pass


class Resolver(TraversingVisitor):
    def __init__(self):
        self.scopes: List[ast.SelectQuerySymbol] = []

    def visit_select_query(self, node):
        """Visit each SELECT query or subquery."""

        if node.symbol is not None:
            return

        # Create a new lexical scope each time we enter a SELECT query.
        node.symbol = ast.SelectQuerySymbol(aliases={}, columns={}, tables={})
        # Keep those scopes stacked in a list as we traverse the tree.
        self.scopes.append(node.symbol)

        # Visit all the FROM and JOIN tables (JoinExpr nodes)
        if node.select_from:
            self.visit(node.select_from)

        # Visit all the SELECT columns.
        # Then mark them for export in "columns". This means they will be available outside of this query via:
        # SELECT e.event, e.timestamp from (SELECT event, timestamp FROM events) AS e
        for expr in node.select or []:
            self.visit(expr)
            if isinstance(expr.symbol, ast.ColumnAliasSymbol):
                node.symbol.columns[expr.symbol.name] = expr.symbol
            elif isinstance(expr, ast.Alias):
                node.symbol.columns[expr.alias] = expr.symbol
            elif isinstance(expr.symbol, ast.FieldSymbol):
                node.symbol.columns[expr.symbol.name] = expr.symbol

        if node.where:
            self.visit(node.where)
        if node.prewhere:
            self.visit(node.prewhere)
        if node.having:
            self.visit(node.having)

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
            if node.alias is None:
                # Make sure there is a way to call the field in the scope.
                node.alias = node.table.chain[0]
            if node.alias in scope.tables:
                raise ResolverException(f'Already have a joined table called "{node.alias}", can\'t redefine.')

            # Only joining the events table is supported
            if node.table.chain == ["events"]:
                node.table.symbol = ast.TableSymbol(table_name="events")
                if node.alias == node.table.symbol.table_name:
                    node.symbol = node.table.symbol
                else:
                    node.symbol = ast.TableAliasSymbol(name=node.alias, symbol=node.table.symbol)
            else:
                raise ResolverException(f"Cannot resolve table {node.table.chain[0]}")

        elif isinstance(node.table, ast.SelectQuery):
            node.table.symbol = self.visit(node.table)
            if node.alias is None:
                node.symbol = node.table.symbol
            else:
                node.symbol = ast.TableAliasSymbol(name=node.alias, symbol=node.table.symbol)

        else:
            raise ResolverException(f"JoinExpr with table of type {type(node.table).__name__} not supported")

        scope.tables[node.alias] = node.symbol

        self.visit(node.join_expr)

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
        node.symbol = ast.ColumnAliasSymbol(name=node.alias, symbol=unwrap_column_alias_symbol(node.expr.symbol))
        scope.aliases[node.alias] = node.symbol

    def visit_field(self, node):
        """Visit a field such as ast.Field(chain=["e", "properties", "$browser"])"""
        if node.symbol is not None:
            return
        if len(node.chain) == 0:
            raise Exception("Invalid field access with empty chain")

        # ClickHouse does not support subqueries accessing "x.event" like this:
        # "SELECT event, (select count() from events where event = x.event) as c FROM events x where event = '$pageview'",
        #
        # But this is supported:
        # "SELECT t.big_count FROM (select count() + 100 as big_count from events) as t",
        #
        # Thus only look into the current scope, for columns and aliases.
        scope = self.scopes[-1]
        symbol: Optional[ast.Symbol] = None
        name = node.chain[0]

        if len(node.chain) > 1 and name in scope.tables:
            # If the field has a chain of at least one (e.g "e", "event"), the first part could refer to a table.
            symbol = scope.tables[name]
        elif name in scope.columns:
            symbol = scope.columns[name]
        elif name in scope.aliases:
            symbol = scope.aliases[name]
        else:
            # Look through all FROM/JOIN tables, if they export a field by this name.
            fields_in_scope = [table.get_child(name) for table in scope.tables.values() if table.has_child(name)]
            if len(fields_in_scope) > 1:
                raise ResolverException(f'Ambiguous query. Found multiple sources for field "{name}".')
            elif len(fields_in_scope) == 1:
                symbol = fields_in_scope[0]

        if not symbol:
            raise ResolverException(f'Cannot resolve symbol: "{name}"')

        # Recursively resolve the rest of the chain until we can point to the deepest node.
        for child_name in node.chain[1:]:
            symbol = symbol.get_child(child_name)
            if symbol is None:
                raise ResolverException(
                    f"Cannot resolve symbol {'.'.join(node.chain)}. Unable to resolve {child_name} on {name}"
                )

        node.symbol = symbol


def unwrap_column_alias_symbol(symbol: ast.Symbol) -> ast.Symbol:
    i = 0
    while isinstance(symbol, ast.ColumnAliasSymbol):
        symbol = symbol.symbol
        i += 1
        if i > 100:
            raise ResolverException("ColumnAliasSymbol recursion too deep!")
    return symbol
