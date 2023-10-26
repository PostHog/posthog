from datetime import date, datetime
from typing import List, Optional, Any, cast
from uuid import UUID

from posthog.hogql import ast
from posthog.hogql.ast import FieldTraverserType, ConstantType
from posthog.hogql.functions import HOGQL_POSTHOG_FUNCTIONS, cohort
from posthog.hogql.context import HogQLContext
from posthog.hogql.database.models import (
    StringJSONDatabaseField,
    FunctionCallTable,
    LazyTable,
    SavedQuery,
)
from posthog.hogql.errors import ResolverException
from posthog.hogql.functions.mapping import validate_function_args
from posthog.hogql.functions.sparkline import sparkline
from posthog.hogql.parser import parse_select
from posthog.hogql.resolver_utils import convert_hogqlx_tag, lookup_cte_by_name, lookup_field_by_name
from posthog.hogql.visitor import CloningVisitor, clone_expr
from posthog.models.utils import UUIDT
from posthog.hogql.database.schema.events import EventsTable
from posthog.hogql.database.s3_table import S3Table

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


def resolve_types(
    node: ast.Expr,
    context: HogQLContext,
    scopes: Optional[List[ast.SelectQueryType]] = None,
) -> ast.Expr:
    return Resolver(scopes=scopes, context=context).visit(node)


class Resolver(CloningVisitor):
    """The Resolver visits an AST and 1) resolves all fields, 2) assigns types to nodes, 3) expands all CTEs."""

    def __init__(self, context: HogQLContext, scopes: Optional[List[ast.SelectQueryType]] = None):
        super().__init__()
        # Each SELECT query creates a new scope (type). Store all of them in a list as we traverse the tree.
        self.scopes: List[ast.SelectQueryType] = scopes or []
        self.current_view_depth: int = 0
        self.context = context
        self.database = context.database
        self.cte_counter = 0

    def visit(self, node: ast.Expr) -> ast.Expr:
        if isinstance(node, ast.Expr) and node.type is not None:
            raise ResolverException(
                f"Type already resolved for {type(node).__name__} ({type(node.type).__name__}). Can't run again."
            )
        if self.cte_counter > 50:
            raise ResolverException("Too many CTE expansions (50+). Probably a CTE loop.")
        return super().visit(node)

    def visit_select_union_query(self, node: ast.SelectUnionQuery):
        node = super().visit_select_union_query(node)
        node.type = ast.SelectUnionQueryType(types=[expr.type for expr in node.select_queries])
        return node

    def visit_select_query(self, node: ast.SelectQuery):
        """Visit each SELECT query or subquery."""

        # This "SelectQueryType" is also a new scope for variables in the SELECT query.
        # We will add fields to it when we encounter them. This is used to resolve fields later.
        node_type = ast.SelectQueryType()

        # First step: add all the "WITH" CTEs onto the "scope" if there are any
        if node.ctes:
            node_type.ctes = node.ctes

        # Append the "scope" onto the stack early, so that nodes we "self.visit" below can access it.
        self.scopes.append(node_type)

        # Clone the select query, piece by piece
        new_node = ast.SelectQuery(
            start=node.start,
            end=node.end,
            type=node_type,
            # CTEs have been expanded (moved to the type for now), so remove from the printable "WITH" clause
            ctes=None,
            # "select" needs a default value, so [] it is
            select=[],
        )

        # Visit the FROM clauses first. This resolves all table aliases onto self.scopes[-1]
        new_node.select_from = self.visit(node.select_from)
        new_node.array_join_op = node.array_join_op
        if node.array_join_list:
            new_node.array_join_list = [self.visit(expr) for expr in node.array_join_list]

        # Visit all the "SELECT a,b,c" columns. Mark each for export in "columns".
        for expr in node.select or []:
            new_expr = self.visit(expr)

            # if it's an asterisk, carry on in a subroutine
            if isinstance(new_expr.type, ast.AsteriskType):
                self._expand_asterisk_columns(new_node, new_expr.type)
                continue

            # not an asterisk
            if isinstance(new_expr.type, ast.FieldAliasType):
                node_type.columns[new_expr.type.alias] = new_expr.type
            elif isinstance(new_expr.type, ast.FieldType):
                node_type.columns[new_expr.type.name] = new_expr.type
            elif isinstance(new_expr, ast.Alias):
                node_type.columns[new_expr.alias] = new_expr.type

            # add the column to the new select query
            new_node.select.append(new_expr)

        # :TRICKY: Make sure to clone and visit _all_ SelectQuery nodes.
        new_node.where = self.visit(node.where)
        new_node.prewhere = self.visit(node.prewhere)
        new_node.having = self.visit(node.having)
        if node.group_by:
            new_node.group_by = [self.visit(expr) for expr in node.group_by]
        if node.order_by:
            new_node.order_by = [self.visit(expr) for expr in node.order_by]
        if node.limit_by:
            new_node.limit_by = [self.visit(expr) for expr in node.limit_by]
        new_node.limit = self.visit(node.limit)
        new_node.limit_with_ties = node.limit_with_ties
        new_node.offset = self.visit(node.offset)
        new_node.distinct = node.distinct
        new_node.window_exprs = (
            {name: self.visit(expr) for name, expr in node.window_exprs.items()} if node.window_exprs else None
        )
        new_node.settings = node.settings.model_copy() if node.settings is not None else None

        self.scopes.pop()

        return new_node

    def _expand_asterisk_columns(self, select_query: ast.SelectQuery, asterisk: ast.AsteriskType):
        """Expand an asterisk. Mutates `select_query.select` and `select_query.type.columns` with the new fields"""
        if isinstance(asterisk.table_type, ast.BaseTableType):
            table = asterisk.table_type.resolve_database_table()
            database_fields = table.get_asterisk()
            for key in database_fields.keys():
                type = ast.FieldType(name=key, table_type=asterisk.table_type)
                select_query.select.append(ast.Field(chain=[key], type=type))
                select_query.type.columns[key] = type
        elif (
            isinstance(asterisk.table_type, ast.SelectUnionQueryType)
            or isinstance(asterisk.table_type, ast.SelectQueryType)
            or isinstance(asterisk.table_type, ast.SelectQueryAliasType)
        ):
            select = asterisk.table_type
            while isinstance(select, ast.SelectQueryAliasType):
                select = select.select_query_type
            if isinstance(select, ast.SelectUnionQueryType):
                select = select.types[0]
            if isinstance(select, ast.SelectQueryType):
                for name in select.columns.keys():
                    type = ast.FieldType(name=name, table_type=asterisk.table_type)
                    select_query.select.append(ast.Field(chain=[name], type=type))
                    select_query.type.columns[name] = type
            else:
                raise ResolverException("Can't expand asterisk (*) on subquery")
        else:
            raise ResolverException(f"Can't expand asterisk (*) on a type of type {type(asterisk.table_type).__name__}")

    def visit_join_expr(self, node: ast.JoinExpr):
        """Visit each FROM and JOIN table or subquery."""

        if len(self.scopes) == 0:
            raise ResolverException("Unexpected JoinExpr outside a SELECT query")

        scope = self.scopes[-1]

        if isinstance(node.table, ast.HogQLXTag):
            node.table = convert_hogqlx_tag(node.table, self.context.team_id)

        # If selecting from a CTE, expand and visit the new node
        if isinstance(node.table, ast.Field) and len(node.table.chain) == 1:
            table_name = node.table.chain[0]
            cte = lookup_cte_by_name(self.scopes, table_name)
            if cte:
                node = cast(ast.JoinExpr, clone_expr(node))
                node.table = clone_expr(cte.expr)
                node.alias = table_name

                self.cte_counter += 1
                response = self.visit(node)
                self.cte_counter -= 1
                return response

        if isinstance(node.table, ast.Field):
            table_name = node.table.chain[0]
            table_alias = node.alias or table_name
            if table_alias in scope.tables:
                raise ResolverException(f'Already have joined a table called "{table_alias}". Can\'t redefine.')

            if self.database.has_table(table_name):
                database_table = self.database.get_table(table_name)

                if isinstance(database_table, SavedQuery):
                    self.current_view_depth += 1

                    if self.current_view_depth > self.context.max_view_depth:
                        raise ResolverException("Nested views are not supported")

                    node.table = parse_select(str(database_table.query))
                    node.alias = table_alias or database_table.name
                    node = self.visit(node)

                    self.current_view_depth -= 1
                    return node

                if isinstance(database_table, LazyTable):
                    node_table_type = ast.LazyTableType(table=database_table)
                else:
                    node_table_type = ast.TableType(table=database_table)

                # Always add an alias for function call tables. This way `select table.* from table` is replaced with
                # `select table.* from something() as table`, and not with `select something().* from something()`.
                if table_alias != table_name or isinstance(database_table, FunctionCallTable):
                    node_type = ast.TableAliasType(alias=table_alias, table_type=node_table_type)
                else:
                    node_type = node_table_type
                scope.tables[table_alias] = node_type

                # :TRICKY: Make sure to clone and visit _all_ JoinExpr fields/nodes.
                node = cast(ast.JoinExpr, clone_expr(node))
                node.type = node_type
                node.table = cast(ast.Field, clone_expr(node.table))
                node.table.type = node_table_type
                if node.table_args is not None:
                    node.table_args = [self.visit(arg) for arg in node.table_args]
                node.next_join = self.visit(node.next_join)

                # Look ahead if current is events table and next is s3 table, global join must be used for distributed query on external data to work
                if isinstance(node.type, ast.TableAliasType):
                    is_global = isinstance(node.type.table_type.table, EventsTable) and self._is_next_s3(node.next_join)
                else:
                    is_global = isinstance(node.type.table, EventsTable) and self._is_next_s3(node.next_join)

                if is_global:
                    node.next_join.join_type = "GLOBAL JOIN"

                node.constraint = self.visit(node.constraint)
                node.sample = self.visit(node.sample)

                # In case we had a function call table, and had to add an alias where none was present, mark it here
                if isinstance(node_type, ast.TableAliasType) and node.alias is None:
                    node.alias = node_type.alias

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

            # :TRICKY: Make sure to clone and visit _all_ JoinExpr fields/nodes.
            node.next_join = self.visit(node.next_join)
            node.constraint = self.visit(node.constraint)
            node.sample = self.visit(node.sample)

            return node
        else:
            raise ResolverException(f"JoinExpr with table of type {type(node.table).__name__} not supported")

    def visit_hogqlx_tag(self, node: ast.HogQLXTag):
        return self.visit(convert_hogqlx_tag(node, self.context.team_id))

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
        node.type = ast.FieldAliasType(alias=node.alias, type=node.expr.type or ast.UnknownType())
        scope.aliases[node.alias] = node.type
        return node

    def visit_call(self, node: ast.Call):
        """Visit function calls."""

        if func_meta := HOGQL_POSTHOG_FUNCTIONS.get(node.name):
            validate_function_args(node.args, func_meta.min_args, func_meta.max_args, node.name)
            if node.name == "sparkline":
                return self.visit(sparkline(node=node, args=node.args))

        node = super().visit_call(node)
        arg_types: List[ast.ConstantType] = []
        for arg in node.args:
            if arg.type:
                arg_types.append(arg.type.resolve_constant_type() or ast.UnknownType())
            else:
                arg_types.append(ast.UnknownType())
        param_types: Optional[List[ast.ConstantType]] = None
        if node.params is not None:
            param_types = []
            for param in node.params:
                if param.type:
                    param_types.append(param.type.resolve_constant_type() or ast.UnknownType())
                else:
                    param_types.append(ast.UnknownType())
        node.type = ast.CallType(
            name=node.name,
            arg_types=arg_types,
            param_types=param_types,
            return_type=ast.UnknownType(),
        )
        return node

    def visit_lambda(self, node: ast.Lambda):
        """Visit each SELECT query or subquery."""

        # Each Lambda is a new scope in field name resolution.
        # This type keeps track of all lambda arguments that are in scope.
        node_type = ast.SelectQueryType(parent=self.scopes[-1] if len(self.scopes) > 0 else None)

        for arg in node.args:
            node_type.aliases[arg] = ast.FieldAliasType(alias=arg, type=ast.LambdaArgumentType(name=arg))

        self.scopes.append(node_type)

        new_node = cast(ast.Lambda, clone_expr(node))
        new_node.type = node_type
        new_node.expr = self.visit(new_node.expr)

        self.scopes.pop()

        return new_node

    def visit_field(self, node: ast.Field):
        """Visit a field such as ast.Field(chain=["e", "properties", "$browser"])"""
        if len(node.chain) == 0:
            raise ResolverException("Invalid field access with empty chain")

        node = super().visit_field(node)

        # Only look for fields in the last SELECT scope, instead of all previous select queries.
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

        # If it's a wildcard
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

        # Field in scope
        if not type:
            type = lookup_field_by_name(scope, name)

        if not type:
            cte = lookup_cte_by_name(self.scopes, name)
            if cte:
                if len(node.chain) > 1:
                    raise ResolverException(f"Cannot access fields on CTE {cte.name} yet")
                # SubQuery CTEs ("WITH a AS (SELECT 1)") can only be used in the "FROM table" part of a select query,
                # which is handled in visit_join_expr. Referring to it here means we want to access its value.
                if cte.cte_type == "subquery":
                    return ast.Field(chain=node.chain)
                self.cte_counter += 1
                response = self.visit(clone_expr(cte.expr))
                self.cte_counter -= 1
                return response

        if not type:
            raise ResolverException(f"Unable to resolve field: {name}")

        # Recursively resolve the rest of the chain until we can point to the deepest node.
        loop_type = type
        chain_to_parse = node.chain[1:]
        previous_types = []
        while True:
            if isinstance(loop_type, FieldTraverserType):
                chain_to_parse = loop_type.chain + chain_to_parse
                loop_type = loop_type.table_type
                continue
            previous_types.append(loop_type)
            if len(chain_to_parse) == 0:
                break
            next_chain = chain_to_parse.pop(0)
            if next_chain == "..":  # only support one level of ".."
                previous_types.pop()
                previous_types.pop()
                loop_type = previous_types[-1]
                next_chain = chain_to_parse.pop(0)

            loop_type = loop_type.get_child(next_chain)
            if loop_type is None:
                raise ResolverException(f"Cannot resolve type {'.'.join(node.chain)}. Unable to resolve {next_chain}.")
        node.type = loop_type

        if isinstance(node.type, ast.FieldType) and node.start is not None and node.end is not None:
            self.context.add_notice(
                start=node.start,
                end=node.end,
                message=f"Field '{node.type.name}' is of type '{node.type.resolve_constant_type().print_type()}'",
            )

        return node

    def visit_array_access(self, node: ast.ArrayAccess):
        node = super().visit_array_access(node)

        if (
            isinstance(node.array, ast.Field)
            and isinstance(node.property, ast.Constant)
            and (isinstance(node.property.value, str) or isinstance(node.property.value, int))
            and (
                (isinstance(node.array.type, ast.PropertyType))
                or (
                    isinstance(node.array.type, ast.FieldType)
                    and isinstance(
                        node.array.type.resolve_database_field(),
                        StringJSONDatabaseField,
                    )
                )
            )
        ):
            node.array.chain.append(node.property.value)
            node.array.type = node.array.type.get_child(node.property.value)
            return node.array

        return node

    def visit_tuple_access(self, node: ast.TupleAccess):
        node = super().visit_tuple_access(node)

        if isinstance(node.tuple, ast.Field) and (
            (isinstance(node.tuple.type, ast.PropertyType))
            or (
                isinstance(node.tuple.type, ast.FieldType)
                and isinstance(node.tuple.type.resolve_database_field(), StringJSONDatabaseField)
            )
        ):
            node.tuple.chain.append(node.index)
            node.tuple.type = node.tuple.type.get_child(node.index)
            return node.tuple

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
        if (
            (node.op == ast.CompareOperationOp.In or node.op == ast.CompareOperationOp.NotIn)
            and self._is_events_table(self.visit(node.left))
            and self._is_s3_cluster(self.visit(node.right))
        ):
            return self.visit(
                ast.CompareOperation(
                    op=ast.CompareOperationOp.GlobalIn
                    if node.op == ast.CompareOperationOp.In
                    else ast.CompareOperationOp.GlobalNotIn,
                    left=node.left,
                    right=node.right,
                )
            )

        if self.context.modifiers.inCohortVia != "leftjoin":
            if node.op == ast.CompareOperationOp.InCohort:
                return self.visit(
                    ast.CompareOperation(
                        op=ast.CompareOperationOp.In,
                        left=node.left,
                        right=cohort(node=node.right, args=[node.right], context=self.context),
                    )
                )
            elif node.op == ast.CompareOperationOp.NotInCohort:
                return self.visit(
                    ast.CompareOperation(
                        op=ast.CompareOperationOp.NotIn,
                        left=node.left,
                        right=cohort(node=node.right, args=[node.right], context=self.context),
                    )
                )

        node = super().visit_compare_operation(node)
        node.type = ast.BooleanType()
        return node

    def _is_events_table(self, node: ast.Expr) -> bool:
        if isinstance(node, ast.Field) and isinstance(node.type, ast.FieldType):
            if isinstance(node.type.table_type, ast.TableAliasType):
                return isinstance(node.type.table_type.table_type.table, EventsTable)
            if isinstance(node.type.table_type, ast.TableType):
                return isinstance(node.type.table_type.table, EventsTable)
        return False

    def _is_s3_cluster(self, node: ast.Expr) -> bool:
        if (
            isinstance(node, ast.SelectQuery)
            and node.select_from
            and isinstance(node.select_from.type, ast.BaseTableType)
        ):
            if isinstance(node.select_from.type, ast.TableAliasType):
                return isinstance(node.select_from.type.table_type.table, S3Table)
            elif isinstance(node.select_from.type, ast.TableType):
                return isinstance(node.select_from.type.table, S3Table)
        return False

    def _is_next_s3(self, node: Optional[ast.JoinExpr]):
        if node is None:
            return False
        if isinstance(node.type, ast.TableAliasType):
            return isinstance(node.type.table_type.table, S3Table)
        return False
