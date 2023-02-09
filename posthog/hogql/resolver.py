from typing import List, Optional

from posthog.hogql import ast
from posthog.hogql.visitor import TraversingVisitor


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
        if node.alias in last_select.symbols:
            raise ResolverException(f"Found multiple expressions with the same alias: {node.alias}")
        if node.alias == "":
            raise ResolverException("Alias cannot be empty")

        self.visit(node.expr)

        node.symbol = ast.AliasSymbol(name=node.alias, symbol=node.expr.symbol)
        last_select.symbols[node.alias] = node.symbol

    def visit_field(self, node):
        if node.symbol is not None:
            return
        if len(node.chain) == 0:
            raise Exception("Invalid field access with empty chain")

        # resolve the first part of the chain
        name = node.chain[0]
        symbol: Optional[ast.Symbol] = None
        for scope in reversed(self.scopes):
            if name in scope.tables and len(node.chain) > 1:
                # CH assumes you're selecting a field, unless it's with a "." in the field, then check for tables
                symbol = scope.tables[name]
                break
            elif name in scope.symbols:
                symbol = scope.symbols[name]
                break
            else:
                fields_on_tables_in_scope = [table for table in scope.tables.values() if table.has_child(name)]
                if len(fields_on_tables_in_scope) > 1:
                    raise ResolverException(
                        f"Found multiple joined tables with field \"{name}\": {', '.join([symbol.name for symbol in fields_on_tables_in_scope])}. Please specify which table you're selecting from."
                    )
                elif len(fields_on_tables_in_scope) == 1:
                    symbol = fields_on_tables_in_scope[0].get_child(name)
                    break

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
        if node.alias in last_select.tables:
            raise ResolverException(f"Table alias with the same name as another table: {node.alias}")

        if isinstance(node.table, ast.Field):
            if node.table.chain == ["events"]:
                if node.alias is None:
                    node.alias = node.table.chain[0]
                symbol = ast.TableSymbol(name=node.alias, table_name="events")
            else:
                raise ResolverException(f"Cannot resolve table {node.table.chain[0]}")

        elif isinstance(node.table, ast.SelectQuery):
            symbol = self.visit(node.table)
            symbol.name = node.alias

        else:
            raise ResolverException(f"JoinExpr with table of type {type(node.table).__name__} not supported")

        node.table.symbol = symbol
        last_select.tables[node.alias] = symbol

        self.visit(node.join_expr)

    def visit_select_query(self, node):
        if node.symbol is not None:
            return

        node.symbol = ast.SelectQuerySymbol(name="", symbols={}, tables={})
        self.scopes.append(node.symbol)

        if node.select_from:
            self.visit(node.select_from)
        if node.select:
            for expr in node.select:
                self.visit(expr)
        if node.where:
            self.visit(node.where)
        if node.prewhere:
            self.visit(node.prewhere)
        if node.having:
            self.visit(node.having)

        self.scopes.pop()

        return node.symbol
