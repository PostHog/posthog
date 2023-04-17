from datetime import date, datetime
from typing import List, Optional, Any
from uuid import UUID

from posthog.hogql import ast
from posthog.hogql.ast import FieldTraverserType, ConstantType
from posthog.hogql.database import Database
from posthog.hogql.errors import ResolverException
from posthog.hogql.visitor import TraversingVisitor
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
        unique_types = set(resolve_constant_data_type(item) for item in constant)
        return ast.ArrayType(item_type=unique_types.pop() if len(unique_types) == 1 else ast.UnknownType())
    if isinstance(constant, tuple):
        return ast.TupleType(item_types=[resolve_constant_data_type(item) for item in constant])
    if isinstance(constant, datetime) or type(constant).__name__ == "FakeDatetime":
        return ast.DateTimeType()
    if isinstance(constant, date) or type(constant).__name__ == "FakeDate":
        return ast.DateType()
    if isinstance(constant, UUID) or isinstance(constant, UUIDT):
        return ast.UUIDType()
    raise ResolverException(f"Unsupported constant type: {type(constant)}")


def resolve_types(node: ast.Expr, database: Database, scope: Optional[ast.SelectQueryType] = None):
    Resolver(scope=scope, database=database).visit(node)


class Resolver(TraversingVisitor):
    """The Resolver visits an AST and assigns Types to the nodes."""

    def __init__(self, database: Database, scope: Optional[ast.SelectQueryType] = None):
        # Each SELECT query creates a new scope. Store all of them in a list as we traverse the tree.
        self.scopes: List[ast.SelectQueryType] = [scope] if scope else []
        self.database = database

    def visit_select_union_query(self, node):
        for expr in node.select_queries:
            self.visit(expr)
        node.type = ast.SelectUnionQueryType(types=[expr.type for expr in node.select_queries])
        return node.type

    def visit_select_query(self, node):
        """Visit each SELECT query or subquery."""
        if node.type is not None:
            return

        # This type keeps track of all joined tables and other field aliases that are in scope.
        node.type = ast.SelectQueryType()

        # Each SELECT query is a new scope in field name resolution.
        self.scopes.append(node.type)

        # Visit all the FROM and JOIN clauses, and register the tables into the scope. See visit_join_expr below.
        if node.select_from:
            self.visit(node.select_from)

        # Visit all the SELECT 1,2,3 columns. Mark each for export in "columns" to make this work:
        # SELECT e.event, e.timestamp from (SELECT event, timestamp FROM events) AS e
        for expr in node.select or []:
            self.visit(expr)
            if isinstance(expr.type, ast.FieldAliasType):
                node.type.columns[expr.type.alias] = expr.type
            elif isinstance(expr.type, ast.FieldType):
                node.type.columns[expr.type.name] = expr.type
            elif isinstance(expr, ast.Alias):
                node.type.columns[expr.alias] = expr.type

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

        return node.type

    def visit_join_expr(self, node):
        """Visit each FROM and JOIN table or subquery."""

        if node.type is not None:
            return
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
                    node.table.type = ast.LazyTableType(table=database_table)
                else:
                    node.table.type = ast.TableType(table=database_table)

                if table_alias == table_name:
                    node.type = node.table.type
                else:
                    node.type = ast.TableAliasType(alias=table_alias, table_type=node.table.type)
                scope.tables[table_alias] = node.type
            else:
                raise ResolverException(f'Unknown table "{table_name}".')

        elif isinstance(node.table, ast.SelectQuery) or isinstance(node.table, ast.SelectUnionQuery):
            node.table.type = self.visit(node.table)
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

        else:
            raise ResolverException(f"JoinExpr with table of type {type(node.table).__name__} not supported")

        self.visit(node.constraint)
        self.visit(node.next_join)

    def visit_alias(self, node: ast.Alias):
        """Visit column aliases. SELECT 1, (select 3 as y) as x."""
        if node.type is not None:
            return

        if len(self.scopes) == 0:
            raise ResolverException("Aliases are allowed only within SELECT queries")
        scope = self.scopes[-1]
        if node.alias in scope.aliases:
            raise ResolverException(f"Cannot redefine an alias with the name: {node.alias}")
        if node.alias == "":
            raise ResolverException("Alias cannot be empty")

        self.visit(node.expr)
        if not node.expr.type:
            raise ResolverException(f"Cannot alias an expression without a type: {node.alias}")
        node.type = ast.FieldAliasType(alias=node.alias, type=node.expr.type)
        scope.aliases[node.alias] = node.type

    def visit_call(self, node: ast.Call):
        """Visit function calls."""
        if node.type is not None:
            return
        arg_types: List[ast.Type] = []
        for arg in node.args:
            self.visit(arg)
            if arg.type is not None:
                arg_types.append(arg.type)
        node.type = ast.CallType(name=node.name, args=arg_types)

    def visit_lambda(self, node: ast.Lambda):
        """Visit each SELECT query or subquery."""
        if node.type is not None:
            return

        # Each Lambda is a new scope in field name resolution.
        # This type keeps track of all lambda arguments that are in scope.
        node.type = ast.SelectQueryType()
        self.scopes.append(node.type)

        for arg in node.args:
            node.type.aliases[arg] = ast.FieldAliasType(alias=arg, type=ast.LambdaArgumentType(name=arg))

        self.visit(node.expr)
        self.scopes.pop()

        return node.type

    def visit_field(self, node):
        """Visit a field such as ast.Field(chain=["e", "properties", "$browser"])"""
        if node.type is not None:
            return
        if len(node.chain) == 0:
            raise ResolverException("Invalid field access with empty chain")

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

    def visit_constant(self, node):
        if node.type is not None:
            return

        super().visit_constant(node)
        node.type = resolve_constant_data_type(node.value)

    def visit_and(self, node: ast.And):
        if node.type is not None:
            return

        super().visit_and(node)
        node.type = ast.BooleanType()

    def visit_or(self, node: ast.Or):
        if node.type is not None:
            return

        super().visit_or(node)
        node.type = ast.BooleanType()

    def visit_not(self, node: ast.Not):
        if node.type is not None:
            return

        super().visit_not(node)
        node.type = ast.BooleanType()

    def visit_compare_operation(self, node: ast.CompareOperation):
        if node.type is not None:
            return

        super().visit_compare_operation(node)
        node.type = ast.BooleanType()


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
