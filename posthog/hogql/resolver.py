from typing import List, Optional

from posthog.hogql import ast
from posthog.hogql.ast import FieldTraverserRef
from posthog.hogql.database import Database
from posthog.hogql.errors import ResolverException
from posthog.hogql.visitor import TraversingVisitor

# https://github.com/ClickHouse/ClickHouse/issues/23194 - "Describe how identifiers in SELECT queries are resolved"


def resolve_refs(node: ast.Expr, database: Database, scope: Optional[ast.SelectQueryRef] = None):
    Resolver(scope=scope, database=database).visit(node)


class Resolver(TraversingVisitor):
    """The Resolver visits an AST and assigns Refs to the nodes."""

    def __init__(self, database: Database, scope: Optional[ast.SelectQueryRef] = None):
        # Each SELECT query creates a new scope. Store all of them in a list as we traverse the tree.
        self.scopes: List[ast.SelectQueryRef] = [scope] if scope else []
        self.database = database

    def visit_select_union_query(self, node):
        for expr in node.select_queries:
            self.visit(expr)
        node.ref = ast.SelectUnionQueryRef(refs=[expr.ref for expr in node.select_queries])
        return node.ref

    def visit_select_query(self, node):
        """Visit each SELECT query or subquery."""
        if node.ref is not None:
            return

        # This ref keeps track of all joined tables and other field aliases that are in scope.
        node.ref = ast.SelectQueryRef()

        # Each SELECT query is a new scope in field name resolution.
        self.scopes.append(node.ref)

        # Visit all the FROM and JOIN clauses, and register the tables into the scope. See visit_join_expr below.
        if node.select_from:
            self.visit(node.select_from)

        # Visit all the SELECT 1,2,3 columns. Mark each for export in "columns" to make this work:
        # SELECT e.event, e.timestamp from (SELECT event, timestamp FROM events) AS e
        for expr in node.select or []:
            self.visit(expr)
            if isinstance(expr.ref, ast.FieldAliasRef):
                node.ref.columns[expr.ref.name] = expr.ref
            elif isinstance(expr.ref, ast.FieldRef):
                node.ref.columns[expr.ref.name] = expr.ref
            elif isinstance(expr, ast.Alias):
                node.ref.columns[expr.alias] = expr.ref

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

        return node.ref

    def visit_join_expr(self, node):
        """Visit each FROM and JOIN table or subquery."""

        if node.ref is not None:
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
                    node.table.ref = ast.LazyTableRef(table=database_table)
                else:
                    node.table.ref = ast.TableRef(table=database_table)

                if table_alias == table_name:
                    node.ref = node.table.ref
                else:
                    node.ref = ast.TableAliasRef(name=table_alias, table_ref=node.table.ref)
                scope.tables[table_alias] = node.ref
            else:
                raise ResolverException(f'Unknown table "{table_name}".')

        elif isinstance(node.table, ast.SelectQuery) or isinstance(node.table, ast.SelectUnionQuery):
            node.table.ref = self.visit(node.table)
            if node.alias is not None:
                if node.alias in scope.tables:
                    raise ResolverException(
                        f'Already have joined a table called "{node.alias}". Can\'t join another one with the same name.'
                    )
                node.ref = ast.SelectQueryAliasRef(name=node.alias, ref=node.table.ref)
                scope.tables[node.alias] = node.ref
            else:
                node.ref = node.table.ref
                scope.anonymous_tables.append(node.ref)

        else:
            raise ResolverException(f"JoinExpr with table of type {type(node.table).__name__} not supported")

        self.visit(node.constraint)
        self.visit(node.next_join)

    def visit_alias(self, node: ast.Alias):
        """Visit column aliases. SELECT 1, (select 3 as y) as x."""
        if node.ref is not None:
            return

        if len(self.scopes) == 0:
            raise ResolverException("Aliases are allowed only within SELECT queries")
        scope = self.scopes[-1]
        if node.alias in scope.aliases:
            raise ResolverException(f"Cannot redefine an alias with the name: {node.alias}")
        if node.alias == "":
            raise ResolverException("Alias cannot be empty")

        self.visit(node.expr)
        if not node.expr.ref:
            raise ResolverException(f"Cannot alias an expression without a ref: {node.alias}")
        node.ref = ast.FieldAliasRef(name=node.alias, ref=node.expr.ref)
        scope.aliases[node.alias] = node.ref

    def visit_call(self, node: ast.Call):
        """Visit function calls."""
        if node.ref is not None:
            return
        arg_refs: List[ast.Ref] = []
        for arg in node.args:
            self.visit(arg)
            if arg.ref is not None:
                arg_refs.append(arg.ref)
        node.ref = ast.CallRef(name=node.name, args=arg_refs)

    def visit_lambda(self, node: ast.Lambda):
        """Visit each SELECT query or subquery."""
        if node.ref is not None:
            return

        # Each Lambda is a new scope in field name resolution.
        # This ref keeps track of all lambda arguments that are in scope.
        node.ref = ast.SelectQueryRef()
        self.scopes.append(node.ref)

        for arg in node.args:
            node.ref.aliases[arg] = ast.FieldAliasRef(name=arg, ref=ast.LambdaArgumentRef(name=arg))

        self.visit(node.expr)
        self.scopes.pop()

        return node.ref

    def visit_field(self, node):
        """Visit a field such as ast.Field(chain=["e", "properties", "$browser"])"""
        if node.ref is not None:
            return
        if len(node.chain) == 0:
            raise ResolverException("Invalid field access with empty chain")

        # Only look for fields in the last SELECT scope, instead of all previous scopes.
        # That's because ClickHouse does not support subqueries accessing "x.event". This is forbidden:
        # - "SELECT event, (select count() from events where event = x.event) as c FROM events x where event = '$pageview'",
        # But this is supported:
        # - "SELECT t.big_count FROM (select count() + 100 as big_count from events) as t JOIN events e ON (e.event = t.event)",
        scope = self.scopes[-1]

        ref: Optional[ast.Ref] = None
        name = node.chain[0]

        # If the field contains at least two parts, the first might be a table.
        if len(node.chain) > 1 and name in scope.tables:
            ref = scope.tables[name]

        if name == "*" and len(node.chain) == 1:
            table_count = len(scope.anonymous_tables) + len(scope.tables)
            if table_count == 0:
                raise ResolverException("Cannot use '*' when there are no tables in the query")
            if table_count > 1:
                raise ResolverException("Cannot use '*' without table name when there are multiple tables in the query")
            table = scope.anonymous_tables[0] if len(scope.anonymous_tables) > 0 else list(scope.tables.values())[0]
            ref = ast.AsteriskRef(table=table)

        if not ref:
            ref = lookup_field_by_name(scope, name)
        if not ref:
            raise ResolverException(f"Unable to resolve field: {name}")

        # Recursively resolve the rest of the chain until we can point to the deepest node.
        loop_ref = ref
        chain_to_parse = node.chain[1:]
        while True:
            if isinstance(loop_ref, FieldTraverserRef):
                chain_to_parse = loop_ref.chain + chain_to_parse
                loop_ref = loop_ref.table
                continue
            if len(chain_to_parse) == 0:
                break
            next_chain = chain_to_parse.pop(0)
            loop_ref = loop_ref.get_child(next_chain)
            if loop_ref is None:
                raise ResolverException(f"Cannot resolve ref {'.'.join(node.chain)}. Unable to resolve {next_chain}.")
        node.ref = loop_ref

    def visit_constant(self, node):
        """Visit a constant"""
        if node.ref is not None:
            return
        node.ref = ast.ConstantRef(value=node.value)


def lookup_field_by_name(scope: ast.SelectQueryRef, name: str) -> Optional[ast.Ref]:
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
