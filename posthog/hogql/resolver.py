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

    def visit_alias(self, node: ast.Alias):
        if node.symbol is not None:
            return

        if len(self.scopes) == 0:
            raise ResolverException("Aliases are allowed only within SELECT queries")
        last_select = self.scopes[-1]
        if node.alias in last_select.aliases:
            raise ResolverException(f"Found multiple expressions with the same alias: {node.alias}")
        if node.alias == "":
            raise ResolverException("Alias cannot be empty")

        self.visit(node.expr)

        node.symbol = ast.ColumnAliasSymbol(name=node.alias, symbol=unwrap_column_alias_symbol(node.expr.symbol))
        last_select.aliases[node.alias] = node.symbol

    def visit_field(self, node):
        if node.symbol is not None:
            return
        if len(node.chain) == 0:
            raise Exception("Invalid field access with empty chain")

        # resolve the first part of the chain
        name = node.chain[0]
        symbol: Optional[ast.Symbol] = None

        # to keep things simple, we only allow selecting fields from within this (select x) scope
        scope = self.scopes[-1]

        if len(node.chain) > 1 and name in scope.tables:
            # CH assumes you're selecting a field, unless it's with a "." in the field, then check for tables
            symbol = scope.tables[name]
        elif name in scope.aliases:
            symbol = scope.aliases[name]
        else:
            fields_on_tables_in_scope = [table for table in scope.tables.values() if table.has_child(name)]
            if len(fields_on_tables_in_scope) > 1:
                raise ResolverException(
                    f'Found multiple joined tables with field "{name}". Please where you\'re selecting from.'
                )
            elif len(fields_on_tables_in_scope) == 1:
                symbol = fields_on_tables_in_scope[0].get_child(name)

        if not symbol:
            raise ResolverException(f'Cannot resolve symbol: "{name}"')

        # recursively resolve the rest of the chain
        for name in node.chain[1:]:
            symbol = symbol.get_child(name)
            if symbol is None:
                raise ResolverException(f"Cannot resolve symbol {', '.join(node.chain)}. Unable to resolve {name}")

        node.symbol = symbol

    def visit_join_expr(self, node):
        if node.symbol is not None:
            return
        if len(self.scopes) == 0:
            raise ResolverException("Unexpected JoinExpr outside a SELECT query")
        last_select = self.scopes[-1]

        if isinstance(node.table, ast.Field):
            if node.alias is None:
                node.alias = node.table.chain[0]
            if node.alias in last_select.tables:
                raise ResolverException(f"Table alias with the same name as another table: {node.alias}")

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

        last_select.tables[node.alias] = node.symbol

        self.visit(node.join_expr)

    def visit_select_query(self, node):
        if node.symbol is not None:
            return

        node.symbol = ast.SelectQuerySymbol(aliases={}, columns={}, tables={})
        self.scopes.append(node.symbol)

        if node.select_from:
            self.visit(node.select_from)
        if node.select:
            for expr in node.select:
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


def unwrap_column_alias_symbol(symbol: ast.Symbol) -> ast.Symbol:
    i = 0
    while isinstance(symbol, ast.ColumnAliasSymbol):
        symbol = symbol.symbol
        i += 1
        if i > 100:
            raise ResolverException("ColumnAliasSymbol recursion too deep!")
    return symbol
