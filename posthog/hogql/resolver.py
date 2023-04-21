from datetime import date, datetime
from typing import List, Optional, Any, cast
from uuid import UUID

from posthog.hogql import ast
from posthog.hogql.ast import FieldTraverserType, ConstantType
from posthog.hogql.database import Database
from posthog.hogql.errors import ResolverException
from posthog.hogql.visitor import CloningVisitor, clone_expr
from posthog.models.utils import UUIDT


# https://github.com/ClickHouse/ClickHouse/issues/23194 - "Describe how identifiers in SELECT queries are resolved"


def resolve_constant_data_type(constant: Any) -> ConstantType:
    if constant is None:
        return ast.UnknownType()
    if isinstance(constant, bool):
        return ast.BooleanType()
    if isinstance(constant, int):
        return ast.IntegerType()
    if isinstance(constant, float):
        return ast.FloatType()
    if isinstance(constant, str):
        return ast.StringType()
    if isinstance(constant, list):
        unique_types = set(str(resolve_constant_data_type(item)) for item in constant)
        return ast.ArrayType(
            item_type=resolve_constant_data_type(constant[0]) if len(unique_types) == 1 else ast.UnknownType()
        )
    if isinstance(constant, tuple):
        return ast.TupleType(item_types=[resolve_constant_data_type(item) for item in constant])
    if isinstance(constant, datetime) or type(constant).__name__ == "FakeDatetime":
        return ast.DateTimeType()
    if isinstance(constant, date) or type(constant).__name__ == "FakeDate":
        return ast.DateType()
    if isinstance(constant, UUID) or isinstance(constant, UUIDT):
        return ast.UUIDType()
    raise ResolverException(f"Unsupported constant type: {type(constant)}")


def resolve_types(node: ast.Expr, database: Database, stack: Optional[List[ast.SelectQuery]] = None) -> ast.Expr:
    scopes = [node.type for node in stack] if stack else None
    return Resolver(scopes=scopes, database=database).visit(node)


class Resolver(CloningVisitor):
    """The Resolver visits an AST and 1) resolves all fields, 2) assigns types to nodes, 3) expands all macros"""

    def __init__(self, database: Database, scopes: Optional[List[ast.SelectQueryType]] = None):
        super().__init__()
        # Each SELECT query creates a new scope (type). Store all of them in a list as we traverse the tree.
        self.scopes: List[ast.SelectQueryType] = scopes or []
        self.database = database

    def visit(self, node: ast.Expr) -> ast.Expr:
        if isinstance(node, ast.Expr) and node.type is not None:
            raise ResolverException(
                f"Type already resolved for {type(node).__name__} ({type(node.type).__name__}). Can't run again."
            )
        return super().visit(node)

    def visit_select_union_query(self, node: ast.SelectUnionQuery):
        node = super().visit_select_union_query(node)
        node.type = ast.SelectUnionQueryType(types=[expr.type for expr in node.select_queries])
        return node

    def visit_select_query(self, node: ast.SelectQuery):
        """Visit each SELECT query or subquery."""
        # This type keeps track of all joined tables and other field aliases that are in scope.
        nodeType = ast.SelectQueryType()

        # Each SELECT query is a new scope in field name resolution.
        self.scopes.append(nodeType)

        node = super().visit_select_query(node)
        node.type = nodeType

        # Visit all the SELECT 1,2,3 columns. Mark each for export in "columns" to make this work:
        # SELECT e.event, e.timestamp from (SELECT event, timestamp FROM events) AS e
        for expr in node.select or []:
            if isinstance(expr.type, ast.FieldAliasType):
                nodeType.columns[expr.type.alias] = expr.type
            elif isinstance(expr.type, ast.FieldType):
                nodeType.columns[expr.type.name] = expr.type
            elif isinstance(expr, ast.Alias):
                nodeType.columns[expr.alias] = expr.type

        self.scopes.pop()

        return node

    def visit_join_expr(self, node: ast.JoinExpr):
        """Visit each FROM and JOIN table or subquery."""

        if len(self.scopes) == 0:
            raise ResolverException("Unexpected JoinExpr outside a SELECT query")

        scope = self.scopes[-1]

        if isinstance(node.table, ast.Field):
            table_name = node.table.chain[0]
            table_alias = node.alias or table_name
            if table_alias in scope.tables:
                raise ResolverException(f'Already have joined a table called "{table_alias}". Can\'t redefine.')

            if self.database.has_table(table_name):
                database_table = self.database.get_table(table_name)
                if isinstance(database_table, ast.LazyTable):
                    nodeTableType = ast.LazyTableType(table=database_table)
                else:
                    nodeTableType = ast.TableType(table=database_table)

                if table_alias == table_name:
                    nodeType = nodeTableType
                else:
                    nodeType = ast.TableAliasType(alias=table_alias, table_type=nodeTableType)
                scope.tables[table_alias] = nodeType

                # :TRICKY: Make sure to visit _all_ expr nodes. Otherwise, the printer may complain about resolved types.
                node = cast(ast.JoinExpr, clone_expr(node))
                node.type = nodeType
                node.table = cast(ast.Field, clone_expr(node.table))
                node.table.type = nodeTableType
                node.next_join = self.visit(node.next_join)
                node.constraint = self.visit(node.constraint)
                node.sample = self.visit(node.sample)
                return node

            else:
                raise ResolverException(f'Unknown table "{table_name}".')

        elif isinstance(node.table, ast.SelectQuery) or isinstance(node.table, ast.SelectUnionQuery):
            node = cast(ast.JoinExpr, clone_expr(node))

            node.table = super().visit(node.table)
            if node.alias is not None:
                if node.alias in scope.tables:
                    raise ResolverException(
                        f'Already have joined a table called "{node.alias}". Can\'t join another one with the same name.'
                    )
                node.type = ast.SelectQueryAliasType(alias=node.alias, select_query_type=node.table.type)
                scope.tables[node.alias] = node.type
            else:
                node.type = node.table.type
                scope.anonymous_tables.append(node.type)

            # :TRICKY: Make sure to visit _all_ expr nodes. Otherwise, the printer may complain about resolved types.
            node.next_join = self.visit(node.next_join)
            node.constraint = self.visit(node.constraint)
            node.sample = self.visit(node.sample)

            return node
        else:
            raise ResolverException(f"JoinExpr with table of type {type(node.table).__name__} not supported")

    def visit_alias(self, node: ast.Alias):
        """Visit column aliases. SELECT 1, (select 3 as y) as x."""
        if len(self.scopes) == 0:
            raise ResolverException("Aliases are allowed only within SELECT queries")

        scope = self.scopes[-1]
        if node.alias in scope.aliases:
            raise ResolverException(f"Cannot redefine an alias with the name: {node.alias}")
        if node.alias == "":
            raise ResolverException("Alias cannot be empty")

        node = super().visit_alias(node)

        if not node.expr.type:
            raise ResolverException(f"Cannot alias an expression without a type: {node.alias}")

        node.type = ast.FieldAliasType(alias=node.alias, type=node.expr.type)
        scope.aliases[node.alias] = node.type
        return node

    def visit_call(self, node: ast.Call):
        """Visit function calls."""

        node = super().visit_call(node)
        arg_types: List[ast.ConstantType] = []
        for arg in node.args:
            if arg.type:
                arg_types.append(arg.type.resolve_constant_type() or ast.UnknownType())
            else:
                arg_types.append(ast.UnknownType())
        node.type = ast.CallType(name=node.name, arg_types=arg_types, return_type=ast.UnknownType())
        return node

    def visit_lambda(self, node: ast.Lambda):
        """Visit each SELECT query or subquery."""

        # Each Lambda is a new scope in field name resolution.
        # This type keeps track of all lambda arguments that are in scope.
        nodeType = ast.SelectQueryType()
        for arg in node.args:
            nodeType.aliases[arg] = ast.FieldAliasType(alias=arg, type=ast.LambdaArgumentType(name=arg))

        self.scopes.append(nodeType)
        node = super().visit_lambda(node)
        node.type = nodeType
        self.scopes.pop()

        return node

    def visit_field(self, node: ast.Field):
        """Visit a field such as ast.Field(chain=["e", "properties", "$browser"])"""
        if len(node.chain) == 0:
            raise ResolverException("Invalid field access with empty chain")

        node = super().visit_field(node)

        # Only look for fields in the last SELECT scope, instead of all previous scopes.
        # That's because ClickHouse does not support subqueries accessing "x.event". This is forbidden:
        # - "SELECT event, (select count() from events where event = x.event) as c FROM events x where event = '$pageview'",
        # But this is supported:
        # - "SELECT t.big_count FROM (select count() + 100 as big_count from events) as t JOIN events e ON (e.event = t.event)",
        scope = self.scopes[-1]

        type: Optional[ast.Type] = None
        name = node.chain[0]

        # If the field contains at least two parts, the first might be a table.
        if len(node.chain) > 1 and name in scope.tables:
            type = scope.tables[name]

        if name == "*" and len(node.chain) == 1:
            table_count = len(scope.anonymous_tables) + len(scope.tables)
            if table_count == 0:
                raise ResolverException("Cannot use '*' when there are no tables in the query")
            if table_count > 1:
                raise ResolverException("Cannot use '*' without table name when there are multiple tables in the query")
            table_type = (
                scope.anonymous_tables[0] if len(scope.anonymous_tables) > 0 else list(scope.tables.values())[0]
            )
            type = ast.AsteriskType(table_type=table_type)

        if not type:
            type = lookup_field_by_name(scope, name)
        if not type:
            raise ResolverException(f"Unable to resolve field: {name}")

        # Recursively resolve the rest of the chain until we can point to the deepest node.
        loop_type = type
        chain_to_parse = node.chain[1:]
        while True:
            if isinstance(loop_type, FieldTraverserType):
                chain_to_parse = loop_type.chain + chain_to_parse
                loop_type = loop_type.table_type
                continue
            if len(chain_to_parse) == 0:
                break
            next_chain = chain_to_parse.pop(0)
            loop_type = loop_type.get_child(next_chain)
            if loop_type is None:
                raise ResolverException(f"Cannot resolve type {'.'.join(node.chain)}. Unable to resolve {next_chain}.")
        node.type = loop_type
        return node

    def visit_constant(self, node: ast.Constant):
        node = super().visit_constant(node)
        node.type = resolve_constant_data_type(node.value)
        return node

    def visit_and(self, node: ast.And):
        node = super().visit_and(node)
        node.type = ast.BooleanType()
        return node

    def visit_or(self, node: ast.Or):
        node = super().visit_or(node)
        node.type = ast.BooleanType()
        return node

    def visit_not(self, node: ast.Not):
        node = super().visit_not(node)
        node.type = ast.BooleanType()
        return node

    def visit_compare_operation(self, node: ast.CompareOperation):
        node = super().visit_compare_operation(node)
        node.type = ast.BooleanType()
        return node


def lookup_field_by_name(scope: ast.SelectQueryType, name: str) -> Optional[ast.Type]:
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
