from typing import List, Optional

from posthog.hogql import ast
from posthog.hogql.ast import FieldTraverserPointer
from posthog.hogql.database import database
from posthog.hogql.visitor import TraversingVisitor

# https://github.com/ClickHouse/ClickHouse/issues/23194 - "Describe how identifiers in SELECT queries are resolved"


def resolve_pointers(node: ast.Expr, scope: Optional[ast.SelectQueryPointer] = None):
    Resolver(scope=scope).visit(node)


class ResolverException(ValueError):
    pass


class Resolver(TraversingVisitor):
    """The Resolver visits an AST and assigns Pointers to the nodes."""

    def __init__(self, scope: Optional[ast.SelectQueryPointer] = None):
        # Each SELECT query creates a new scope. Store all of them in a list as we traverse the tree.
        self.scopes: List[ast.SelectQueryPointer] = [scope] if scope else []

    def visit_select_query(self, node):
        """Visit each SELECT query or subquery."""
        if node.pointer is not None:
            return

        # This pointer keeps track of all joined tables and other field aliases that are in scope.
        node.pointer = ast.SelectQueryPointer()

        # Each SELECT query is a new scope in field name resolution.
        self.scopes.append(node.pointer)

        # Visit all the FROM and JOIN clauses, and register the tables into the scope. See visit_join_expr below.
        if node.select_from:
            self.visit(node.select_from)

        # Visit all the SELECT 1,2,3 columns. Mark each for export in "columns" to make this work:
        # SELECT e.event, e.timestamp from (SELECT event, timestamp FROM events) AS e
        for expr in node.select or []:
            self.visit(expr)
            if isinstance(expr.pointer, ast.FieldAliasPointer):
                node.pointer.columns[expr.pointer.name] = expr.pointer
            elif isinstance(expr.pointer, ast.FieldPointer):
                node.pointer.columns[expr.pointer.name] = expr.pointer
            elif isinstance(expr, ast.Alias):
                node.pointer.columns[expr.alias] = expr.pointer

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

        return node.pointer

    def visit_join_expr(self, node):
        """Visit each FROM and JOIN table or subquery."""

        if node.pointer is not None:
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
                node.table.pointer = ast.TablePointer(table=database.get_table(table_name))
                if table_alias == table_name:
                    node.pointer = node.table.pointer
                else:
                    node.pointer = ast.TableAliasPointer(name=table_alias, table_pointer=node.table.pointer)
                scope.tables[table_alias] = node.pointer
            else:
                raise ResolverException(f'Unknown table "{table_name}".')

        elif isinstance(node.table, ast.SelectQuery):
            node.table.pointer = self.visit(node.table)
            if node.alias is not None:
                if node.alias in scope.tables:
                    raise ResolverException(f'Already have joined a table called "{node.alias}". Can\'t redefine.')
                node.pointer = ast.SelectQueryAliasPointer(name=node.alias, pointer=node.table.pointer)
                scope.tables[node.alias] = node.pointer
            else:
                node.pointer = node.table.pointer
                scope.anonymous_tables.append(node.pointer)

        else:
            raise ResolverException(f"JoinExpr with table of type {type(node.table).__name__} not supported")

        self.visit(node.constraint)
        self.visit(node.next_join)

    def visit_alias(self, node: ast.Alias):
        """Visit column aliases. SELECT 1, (select 3 as y) as x."""
        if node.pointer is not None:
            return

        if len(self.scopes) == 0:
            raise ResolverException("Aliases are allowed only within SELECT queries")
        scope = self.scopes[-1]
        if node.alias in scope.aliases:
            raise ResolverException(f"Cannot redefine an alias with the name: {node.alias}")
        if node.alias == "":
            raise ResolverException("Alias cannot be empty")

        self.visit(node.expr)
        if not node.expr.pointer:
            raise ResolverException(f"Cannot alias an expression without a pointer: {node.alias}")
        node.pointer = ast.FieldAliasPointer(name=node.alias, pointer=node.expr.pointer)
        scope.aliases[node.alias] = node.pointer

    def visit_call(self, node: ast.Call):
        """Visit function calls."""
        if node.pointer is not None:
            return
        arg_pointers: List[ast.Pointer] = []
        for arg in node.args:
            self.visit(arg)
            if arg.pointer is not None:
                arg_pointers.append(arg.pointer)
        node.pointer = ast.CallPointer(name=node.name, args=arg_pointers)

    def visit_field(self, node):
        """Visit a field such as ast.Field(chain=["e", "properties", "$browser"])"""
        if node.pointer is not None:
            return
        if len(node.chain) == 0:
            raise Exception("Invalid field access with empty chain")

        # Only look for fields in the last SELECT scope, instead of all previous scopes.
        # That's because ClickHouse does not support subqueries accessing "x.event". This is forbidden:
        # - "SELECT event, (select count() from events where event = x.event) as c FROM events x where event = '$pageview'",
        # But this is supported:
        # - "SELECT t.big_count FROM (select count() + 100 as big_count from events) as t JOIN events e ON (e.event = t.event)",
        scope = self.scopes[-1]

        pointer: Optional[ast.Pointer] = None
        name = node.chain[0]

        # If the field contains at least two parts, the first might be a table.
        if len(node.chain) > 1 and name in scope.tables:
            pointer = scope.tables[name]

        if name == "*" and len(node.chain) == 1:
            table_count = len(scope.anonymous_tables) + len(scope.tables)
            if table_count == 0:
                raise ResolverException("Cannot use '*' when there are no tables in the query")
            if table_count > 1:
                raise ResolverException("Cannot use '*' without table name when there are multiple tables in the query")
            table = scope.anonymous_tables[0] if len(scope.anonymous_tables) > 0 else list(scope.tables.values())[0]
            pointer = ast.AsteriskPointer(table=table)

        if not pointer:
            pointer = lookup_field_by_name(scope, name)
        if not pointer:
            raise ResolverException(f"Unable to resolve field: {name}")

        # Recursively resolve the rest of the chain until we can point to the deepest node.
        loop_pointer = pointer
        chain_to_parse = node.chain[1:]
        while True:
            if isinstance(loop_pointer, FieldTraverserPointer):
                chain_to_parse = loop_pointer.chain + chain_to_parse
                loop_pointer = loop_pointer.table
                continue
            if len(chain_to_parse) == 0:
                break
            next_chain = chain_to_parse.pop(0)
            loop_pointer = loop_pointer.get_child(next_chain)
            if loop_pointer is None:
                raise ResolverException(
                    f"Cannot resolve pointer {'.'.join(node.chain)}. Unable to resolve {next_chain}."
                )
        node.pointer = loop_pointer

    def visit_constant(self, node):
        """Visit a constant"""
        if node.pointer is not None:
            return
        node.pointer = ast.ConstantPointer(value=node.value)


def lookup_field_by_name(scope: ast.SelectQueryPointer, name: str) -> Optional[ast.Pointer]:
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
