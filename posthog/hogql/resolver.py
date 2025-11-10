import dataclasses
from datetime import date, datetime
from typing import Any, Literal, Optional, cast
from uuid import UUID

from posthog.hogql import ast
from posthog.hogql.ast import ConstantType, FieldTraverserType
from posthog.hogql.base import _T_AST
from posthog.hogql.context import HogQLContext
from posthog.hogql.database.models import FunctionCallTable, LazyTable, SavedQuery, StringJSONDatabaseField
from posthog.hogql.database.s3_table import S3Table
from posthog.hogql.database.schema.events import EventsTable
from posthog.hogql.database.schema.persons import PersonsTable
from posthog.hogql.errors import ImpossibleASTError, QueryError, ResolutionError
from posthog.hogql.escape_sql import safe_identifier
from posthog.hogql.functions import find_hogql_posthog_function
from posthog.hogql.functions.action import matches_action
from posthog.hogql.functions.cohort import cohort_query_node
from posthog.hogql.functions.core import compare_types, validate_function_args
from posthog.hogql.functions.explain_csp_report import explain_csp_report
from posthog.hogql.functions.mapping import HOGQL_CLICKHOUSE_FUNCTIONS
from posthog.hogql.functions.recording_button import recording_button
from posthog.hogql.functions.sparkline import sparkline
from posthog.hogql.hogqlx import HOGQLX_COMPONENTS, HOGQLX_TAGS, convert_to_hx
from posthog.hogql.parser import parse_select
from posthog.hogql.resolver_utils import expand_hogqlx_query, lookup_field_by_name, lookup_table_by_name
from posthog.hogql.visitor import CloningVisitor, TraversingVisitor, clone_expr

from posthog.models.utils import UUIDT

# https://github.com/ClickHouse/ClickHouse/issues/23194 - "Describe how identifiers in SELECT queries are resolved"

# To quickly disable global joins, switch this to False
USE_GLOBAL_JOINS = False

EMPTY_SCOPE = ast.SelectQueryType()


def resolve_constant_data_type(constant: Any) -> ConstantType:
    if constant is None:
        return ast.UnknownType()
    if isinstance(constant, bool):
        return ast.BooleanType(nullable=False)
    if isinstance(constant, int):
        return ast.IntegerType(nullable=False)
    if isinstance(constant, float):
        return ast.FloatType(nullable=False)
    if isinstance(constant, str):
        return ast.StringType(nullable=False)
    if isinstance(constant, list):
        unique_types = {str(resolve_constant_data_type(item)) for item in constant}
        return ast.ArrayType(
            nullable=False,
            item_type=resolve_constant_data_type(constant[0]) if len(unique_types) == 1 else ast.UnknownType(),
        )
    if isinstance(constant, tuple):
        return ast.TupleType(nullable=False, item_types=[resolve_constant_data_type(item) for item in constant])
    if isinstance(constant, datetime) or type(constant).__name__ == "FakeDatetime":
        return ast.DateTimeType(nullable=False)
    if isinstance(constant, date) or type(constant).__name__ == "FakeDate":
        return ast.DateType(nullable=False)
    if isinstance(constant, UUID) or isinstance(constant, UUIDT):
        return ast.UUIDType(nullable=False)
    raise ImpossibleASTError(f"Unsupported constant type: {type(constant)}")


def resolve_types_from_table(
    expr: ast.Expr, table_chain: list[str], context: HogQLContext, dialect: Literal["hogql", "clickhouse"]
) -> ast.Expr:
    if context.database is None:
        raise QueryError("Database needs to be defined")

    if not context.database.has_table(table_chain):
        raise QueryError(f'Table "{".".join(table_chain)}" does not exist')

    select_node = ast.SelectQuery(
        select=[ast.Field(chain=["*"])],
        select_from=ast.JoinExpr(table=ast.Field(chain=cast(list[str | int], table_chain))),
    )
    select_node_with_types = cast(ast.SelectQuery, resolve_types(select_node, context, dialect))
    assert select_node_with_types.type is not None

    return resolve_types(expr, context, dialect, [select_node_with_types.type])


def resolve_types(
    node: _T_AST,
    context: HogQLContext,
    dialect: Literal["hogql", "clickhouse"],
    scopes: Optional[list[ast.SelectQueryType]] = None,
) -> _T_AST:
    return Resolver(scopes=scopes, context=context, dialect=dialect).visit(node)


class AliasCollector(TraversingVisitor):
    def __init__(self):
        super().__init__()
        self.aliases: list[str] = []

    def visit_alias(self, node: ast.Alias):
        self.aliases.append(node.alias)
        return node


class Resolver(CloningVisitor):
    """The Resolver visits an AST and 1) resolves all fields, 2) assigns types to nodes, 3) expands all CTEs."""

    def __init__(
        self,
        context: HogQLContext,
        dialect: Literal["hogql", "clickhouse"] = "clickhouse",
        scopes: Optional[list[ast.SelectQueryType]] = None,
    ):
        super().__init__()
        # Each SELECT query creates a new scope (type). Store all of them in a list as we traverse the tree.
        self.scopes: list[ast.SelectQueryType] = scopes or []
        self.ctes: dict[str, ast.CTE] = {}
        self.current_view_depth: int = 0
        self.context = context
        self.dialect = dialect
        self.database = context.database
        self.cte_counter = 0
        self.inside_union = False

    def visit(self, node: ast.AST | None):
        if isinstance(node, ast.Expr) and node.type is not None:
            raise ResolutionError(
                f"Type already resolved for {type(node).__name__} ({type(node.type).__name__}). Can't run again."
            )
        return super().visit(node)

    def visit_select_set_query(self, node: ast.SelectSetQuery):
        # For UNION ALL queries, CTEs from all parts should be accumulated and available to all parts
        parent_ctes = self.ctes
        parent_inside_union = self.inside_union
        self.ctes = dict(parent_ctes)
        self.inside_union = True

        node = super().visit_select_set_query(node)
        node.type = ast.SelectSetQueryType(
            types=[node.initial_select_query.type, *(x.select_query.type for x in node.subsequent_select_queries)]  # type: ignore
        )

        self.ctes = parent_ctes
        self.inside_union = parent_inside_union

        return node

    def visit_cte(self, node: ast.CTE):
        self.cte_counter += 1

        # Save the current CTEs and create a new scope for nested queries
        parent_ctes = self.ctes
        self.ctes = dict(parent_ctes)

        cte_expr = clone_expr(node.expr)
        cte_expr = self.visit(cte_expr)
        node.type = ast.CTETableType(name=node.name, select_query_type=cte_expr.type)

        # Restore parent CTEs
        self.ctes = parent_ctes
        self.cte_counter -= 1

        node.expr = cte_expr

        self.ctes[node.name] = node

        return node

    def visit_select_query(self, node: ast.SelectQuery):
        """Visit each SELECT query or subquery."""
        # This "SelectQueryType" is also a new scope for variables in the SELECT query.
        # We will add fields to it when we encounter them. This is used to resolve fields later.
        node_type = ast.SelectQueryType()

        # Save parent CTEs for nested queries (unless we're in a UNION where CTEs should accumulate)
        parent_ctes = self.ctes if not self.inside_union else {}

        # First step: resolve all the "WITH" CTEs onto "self.ctes" if there are any
        if node.ctes:
            # If not in a UNION, start with parent CTEs so this query can reference them
            if not self.inside_union:
                self.ctes = dict(parent_ctes)
            # If in a UNION, CTEs accumulate in the shared union scope (don't create new dict)
            for cte in node.ctes.values():
                self.visit(cte)
            node_type.ctes = node.ctes
        elif not self.inside_union:
            # No CTEs in this query, but inherit parent CTEs (if not in UNION)
            self.ctes = dict(parent_ctes)

        # Append the "scope" onto the stack early, so that nodes we "self.visit" below can access it.
        self.scopes.append(node_type)

        # Clone the select query, piece by piece
        new_node = ast.SelectQuery(
            start=node.start,
            end=node.end,
            type=node_type,
            # Set CTEs on the first select query type
            ctes=self.ctes if len(self.scopes) == 1 and self.cte_counter == 0 else None,
            # "select" needs a default value, so [] it is
            select=[],
        )

        # Visit the FROM clauses first. This resolves all table aliases onto self.scopes[-1]
        new_node.select_from = self.visit(node.select_from)

        # Array joins (pass 1 - so we can use aliases from the array join in columns)
        new_node.array_join_op = node.array_join_op
        ac = AliasCollector()
        array_join_aliases = []
        if node.array_join_list:
            for expr in node.array_join_list:
                ac.visit(expr)
            array_join_aliases = ac.aliases
            for key in array_join_aliases:
                if key in node_type.aliases:
                    raise QueryError(f"Cannot redefine an alias with the name: {key}")
                node_type.aliases[key] = ast.FieldAliasType(alias=key, type=ast.UnknownType())

        # Visit all the "SELECT a,b,c" columns. Mark each for export in "columns".
        select_nodes = []
        for expr in node.select or []:
            new_expr = self.visit(expr)
            if isinstance(new_expr.type, ast.AsteriskType):
                columns = self._asterisk_columns(new_expr.type, chain_prefix=new_expr.chain[:-1])
                for col in columns:
                    visited_col = self.visit(col)
                    if isinstance(visited_col, ast.Field):
                        visited_col.from_asterisk = True
                    elif isinstance(visited_col, ast.Alias) and isinstance(visited_col.expr, ast.Field):
                        visited_col.expr.from_asterisk = True
                    select_nodes.append(visited_col)
            else:
                select_nodes.append(new_expr)

        columns_with_visible_alias = {}
        for new_expr in select_nodes:
            if isinstance(new_expr.type, ast.FieldAliasType):
                alias = new_expr.type.alias
            elif isinstance(new_expr.type, ast.FieldType):
                alias = new_expr.type.name
            elif isinstance(new_expr.type, ast.ExpressionFieldType):
                alias = new_expr.type.name
            elif isinstance(new_expr, ast.Alias):
                alias = new_expr.alias
            elif isinstance(new_expr.type, ast.CallType):
                from posthog.hogql.printer import print_prepared_ast

                alias = safe_identifier(print_prepared_ast(node=new_expr, context=self.context, dialect="hogql"))
            else:
                alias = None

            if alias:
                # Make a reference of the first visible or last hidden expr for each unique alias name.
                if isinstance(new_expr, ast.Alias) and new_expr.hidden:
                    if alias not in node_type.columns or not columns_with_visible_alias.get(alias, False):
                        node_type.columns[alias] = new_expr.type
                        columns_with_visible_alias[alias] = False
                else:
                    node_type.columns[alias] = new_expr.type
                    columns_with_visible_alias[alias] = True

            # add the column to the new select query
            new_node.select.append(new_expr)

        # Array joins (pass 2 - so we can use aliases from columns in the array join)
        if node.array_join_list:
            for key in array_join_aliases:
                if key in node_type.aliases:
                    # delete the keys we added in the first pass to avoid "can't redefine" errors
                    del node_type.aliases[key]
            new_node.array_join_list = [self.visit(expr) for expr in node.array_join_list]

        # :TRICKY: Make sure to clone and visit _all_ SelectQuery nodes.
        new_node.where = self.visit(node.where)
        new_node.prewhere = self.visit(node.prewhere)
        new_node.having = self.visit(node.having)
        if node.group_by:
            new_node.group_by = [self.visit(expr) for expr in node.group_by]
        if node.order_by:
            new_node.order_by = [self.visit(expr) for expr in node.order_by]
        new_node.limit_by = self.visit(node.limit_by)
        new_node.limit = self.visit(node.limit)
        new_node.limit_with_ties = node.limit_with_ties
        new_node.offset = self.visit(node.offset)
        new_node.distinct = node.distinct
        new_node.window_exprs = (
            {name: self.visit(expr) for name, expr in node.window_exprs.items()} if node.window_exprs else None
        )
        new_node.settings = node.settings.model_copy() if node.settings is not None else None
        new_node.view_name = node.view_name

        self.scopes.pop()

        # Restore parent CTEs (unless we're in a UNION where CTEs should accumulate)
        if not self.inside_union:
            self.ctes = parent_ctes

        return new_node

    def _asterisk_columns(self, asterisk: ast.AsteriskType, chain_prefix: list[str]) -> list[ast.Field]:
        """Expand an asterisk. Mutates `select_query.select` and `select_query.type.columns` with the new fields.

        If we have a chain prefix (for example, in the case of a table alias), we prepend it to the chain of the new fields.
        """
        if isinstance(asterisk.table_type, ast.BaseTableType):
            table = asterisk.table_type.resolve_database_table(self.context)
            database_fields = table.get_asterisk()
            return [ast.Field(chain=[*chain_prefix, key]) for key in database_fields.keys()]
        elif (
            isinstance(asterisk.table_type, ast.SelectSetQueryType)
            or isinstance(asterisk.table_type, ast.SelectQueryType)
            or isinstance(asterisk.table_type, ast.SelectQueryAliasType)
        ):
            select = asterisk.table_type

            # Recursion because might be an `ast.BaseTableType` such as `ast.SelectViewType`
            if isinstance(select, ast.SelectQueryAliasType):
                return self._asterisk_columns(ast.AsteriskType(table_type=select.select_query_type), chain_prefix)

            if isinstance(select, ast.SelectSetQueryType):
                select = select.types[0]

            if isinstance(select, ast.SelectQueryType):
                return [ast.Field(chain=[*chain_prefix, key]) for key in select.columns.keys()]
            else:
                raise QueryError("Can't expand asterisk (*) on subquery")
        else:
            raise QueryError(f"Can't expand asterisk (*) on a type of type {type(asterisk.table_type).__name__}")

    def visit_join_expr(self, node: ast.JoinExpr):
        """Visit each FROM and JOIN table or subquery."""

        if len(self.scopes) == 0:
            raise ImpossibleASTError("Unexpected JoinExpr outside a SELECT query")

        scope = self._get_scope()

        if isinstance(node.table, ast.HogQLXTag):
            node.table = expand_hogqlx_query(node.table, self.context.team_id)

        if isinstance(node.table, ast.Field):
            table_name_chain = [str(n) for n in node.table.chain]
            table_name_alias = "__".join(table_name_chain)
            table_alias: str = node.alias or table_name_alias
            if table_alias in scope.tables:
                raise QueryError(f'Already have joined a table called "{table_alias}". Can\'t redefine.')

            cte_table = self.ctes.get(".".join(table_name_chain))
            if cte_table:
                assert isinstance(cte_table.expr.type, ast.SelectQueryType)
                node.type = cte_table.expr.type
                if table_alias != table_name_alias:
                    node.type = ast.SelectQueryAliasType(alias=table_alias, select_query_type=cte_table.expr.type)

                if node.constraint and node.constraint.constraint_type == "USING":
                    # visit USING constraint before adding the table to avoid ambiguous names
                    node.constraint = self.visit_join_constraint(node.constraint)

                scope.tables[table_alias or cte_table.name] = node.type
                node.table.type = ast.CTETableType(
                    name=table_alias or cte_table.name, select_query_type=cte_table.expr.type
                )

                if node.constraint and node.constraint.constraint_type == "ON":
                    node.constraint = self.visit_join_constraint(node.constraint)

                return node
            else:
                database_table = self.database.get_table_node(table_name_chain).get()  # type: ignore

                if isinstance(database_table, SavedQuery):
                    self.current_view_depth += 1

                    node.table = parse_select(str(database_table.query))

                    if isinstance(node.table, ast.SelectQuery):
                        node.table.view_name = database_table.name

                    node.alias = table_alias or database_table.name
                    node = self.visit(node)

                    self.current_view_depth -= 1
                    return node

                if isinstance(database_table, LazyTable):
                    if isinstance(database_table, PersonsTable):
                        # Check for inlineable exprs in the join on the persons table
                        database_table = database_table.create_new_table_with_filter(node)
                    node_table_type = ast.LazyTableType(table=database_table)

                else:
                    node_table_type = ast.TableType(table=database_table)

                # Always add an alias for function call tables. This way `select table.* from table` is replaced with
                # `select table.* from something() as table`, and not with `select something().* from something()`.
                if table_alias != table_name_alias or isinstance(database_table, FunctionCallTable):
                    node_type: ast.TableOrSelectType = ast.TableAliasType(alias=table_alias, table_type=node_table_type)
                else:
                    node_type = node_table_type

                node = cast(ast.JoinExpr, clone_expr(node))
                if node.constraint and node.constraint.constraint_type == "USING":
                    # visit USING constraint before adding the table to avoid ambiguous names
                    node.constraint = self.visit_join_constraint(node.constraint)

                scope.tables[table_alias] = node_type

                # :TRICKY: Make sure to clone and visit _all_ JoinExpr fields/nodes.
                node.type = node_type
                node.table = cast(ast.Field, clone_expr(node.table))
                node.table.type = node_table_type
                if node.table_args is not None:
                    node.table_args = [self.visit(arg) for arg in node.table_args]
                node.next_join = self.visit(node.next_join)

                # Look ahead if current is events table and next is s3 table, global join must be used for distributed query on external data to work
                if USE_GLOBAL_JOINS:
                    global_table: ast.TableType | None = None

                    if isinstance(node.type, ast.TableAliasType) and isinstance(node.type.table_type, ast.TableType):
                        global_table = node.type.table_type
                    elif isinstance(node.type, ast.TableType):
                        global_table = node.type

                    if global_table and isinstance(global_table.table, EventsTable):
                        next_join = node.next_join
                        is_global = False

                        while next_join:
                            if self._is_next_s3(next_join):
                                is_global = True
                            # Use GLOBAL joins for nested subqueries for S3 tables until https://github.com/ClickHouse/ClickHouse/pull/85839 is in
                            elif isinstance(next_join.type, ast.SelectQueryAliasType):
                                select_query_type = next_join.type.select_query_type
                                tables = self._extract_tables_from_query_type(select_query_type)
                                if any(self._is_s3_table(table) for table in tables):
                                    is_global = True

                            next_join = next_join.next_join

                        # If there exists a S3 table in the chain, then all joins require to be a GLOBAL join
                        if is_global:
                            next_join = node.next_join
                            while next_join:
                                next_join.join_type = f"GLOBAL {next_join.join_type}"
                                next_join = next_join.next_join

                if node.constraint and node.constraint.constraint_type == "ON":
                    node.constraint = self.visit_join_constraint(node.constraint)
                node.sample = self.visit(node.sample)

                # In case we had a function call table, and had to add an alias where none was present, mark it here
                if isinstance(node_type, ast.TableAliasType) and node.alias is None:
                    node.alias = node_type.alias

                return node

        elif isinstance(node.table, ast.SelectQuery) or isinstance(node.table, ast.SelectSetQuery):
            node = cast(ast.JoinExpr, clone_expr(node))
            if node.constraint and node.constraint.constraint_type == "USING":
                # visit USING constraint before adding the table to avoid ambiguous names
                node.constraint = self.visit_join_constraint(node.constraint)

            node.table = super().visit(node.table)
            if isinstance(node.table, ast.SelectQuery) and node.table.view_name is not None and node.alias is not None:
                if node.alias in scope.tables:
                    raise QueryError(
                        f'Already have joined a table called "{node.alias}". Can\'t join another one with the same name.'
                    )
                node.type = ast.SelectViewType(
                    alias=node.alias, view_name=node.table.view_name, select_query_type=node.table.type
                )
                scope.tables[node.alias] = node.type
            elif node.alias is not None:
                if node.alias in scope.tables:
                    raise QueryError(
                        f'Already have joined a table called "{node.alias}". Can\'t join another one with the same name.'
                    )
                node.type = ast.SelectQueryAliasType(alias=node.alias, select_query_type=node.table.type)
                scope.tables[node.alias] = node.type
            else:
                node.type = node.table.type
                scope.anonymous_tables.append(node.type)

            # :TRICKY: Make sure to clone and visit _all_ JoinExpr fields/nodes.
            node.next_join = self.visit(node.next_join)
            if node.constraint and node.constraint.constraint_type == "ON":
                node.constraint = self.visit_join_constraint(node.constraint)
            node.sample = self.visit(node.sample)

            return node
        else:
            raise QueryError(f"A {type(node.table).__name__} cannot be used as a SELECT source")

    def visit_hogqlx_tag(self, node: ast.HogQLXTag):
        if node.kind in HOGQLX_TAGS or node.kind in HOGQLX_COMPONENTS:
            return self.visit(convert_to_hx(node))
        return self.visit(expand_hogqlx_query(node, self.context.team_id))

    def visit_alias(self, node: ast.Alias):
        """Visit column aliases. SELECT 1, (select 3 as y) as x."""
        if len(self.scopes) == 0:
            raise QueryError("Aliases are allowed only within SELECT queries")

        scope = self._get_scope()
        if node.alias in scope.aliases and not node.hidden:
            raise QueryError(f"Cannot redefine an alias with the name: {node.alias}")
        if node.alias == "":
            raise ImpossibleASTError("Alias cannot be empty")

        node = super().visit_alias(node)
        node.type = ast.FieldAliasType(alias=node.alias, type=node.expr.type or ast.UnknownType())
        if not node.hidden:
            scope.aliases[node.alias] = node.type
        return node

    def visit_arithmetic_operation(self, node: ast.ArithmeticOperation):
        node = super().visit_arithmetic_operation(node)

        if node.left.type is None or node.right.type is None:
            return node

        left_type = node.left.type.resolve_constant_type(self.context)
        right_type = node.right.type.resolve_constant_type(self.context)

        if isinstance(left_type, ast.IntegerType) and isinstance(right_type, ast.IntegerType):
            node.type = ast.IntegerType()
        elif isinstance(left_type, ast.FloatType) and isinstance(right_type, ast.FloatType):
            node.type = ast.FloatType()
        elif isinstance(left_type, ast.IntegerType) and isinstance(right_type, ast.FloatType):
            node.type = ast.FloatType()
        elif isinstance(left_type, ast.FloatType) and isinstance(right_type, ast.IntegerType):
            node.type = ast.FloatType()
        elif isinstance(left_type, ast.DateTimeType) or isinstance(right_type, ast.DateTimeType):
            node.type = ast.DateTimeType()
        elif isinstance(left_type, ast.UnknownType) or isinstance(right_type, ast.UnknownType):
            node.type = ast.UnknownType()
        else:
            node.type = ast.UnknownType()

        node.type.nullable = left_type.nullable or right_type.nullable
        return node

    def visit_call(self, node: ast.Call):
        """Visit function calls."""

        if func_meta := find_hogql_posthog_function(node.name):
            validate_function_args(node.args, func_meta.min_args, func_meta.max_args, node.name)

            if node.name == "sparkline":
                return self.visit(sparkline(node=node, args=node.args))
            if node.name == "recordingButton":
                return self.visit(recording_button(node=node, args=node.args))
            if node.name == "explainCSPReport":
                return self.visit(explain_csp_report(node=node, args=node.args))
            if node.name == "matchesAction":
                events_alias, _ = self._get_events_table_current_scope()
                if events_alias is None:
                    raise QueryError("matchesAction can only be used with the events table")
                return self.visit(
                    matches_action(node=node, args=node.args, context=self.context, events_alias=events_alias)
                )

        node = super().visit_call(node)
        arg_types: list[ast.ConstantType] = []
        for arg in node.args:
            if arg.type:
                arg_types.append(arg.type.resolve_constant_type(self.context))
            else:
                arg_types.append(ast.UnknownType())
        param_types: Optional[list[ast.ConstantType]] = None
        if node.params is not None:
            param_types = []
            for i, param in enumerate(node.params):
                if param.type:
                    param_types.append(param.type.resolve_constant_type(self.context))
                else:
                    raise ResolutionError(f"Unknown type for function '{node.name}', parameter {i}")

        return_type = None

        if func_meta := HOGQL_CLICKHOUSE_FUNCTIONS.get(node.name, None):
            if signatures := func_meta.signatures:
                for sig_arg_types, sig_return_type in signatures:
                    if sig_arg_types is None or compare_types(arg_types, sig_arg_types):
                        return_type = dataclasses.replace(sig_return_type)
                        break

        if return_type is None:
            return_type = ast.UnknownType()

            # Uncomment once all hogql mappings are complete with signatures
            # arg_type_classes = [arg_type.__class__.__name__ for arg_type in arg_types]
            # raise ResolutionError(
            #     f"Can't call function '{node.name}' with arguments of type: {', '.join(arg_type_classes)}"
            # )

        if node.name == "concat":
            return_type.nullable = False  # valid only if at least 1 param is not null
        elif not isinstance(return_type, ast.UnknownType):  # why cannot we set nullability here?
            return_type.nullable = any(arg_type.nullable for arg_type in arg_types)

        if node.name.lower() in ("nullif", "toNullable") or node.name.lower().endswith("OrNull"):
            return_type.nullable = True

        node.type = ast.CallType(
            name=node.name,
            arg_types=arg_types,
            param_types=param_types,
            return_type=return_type,
        )
        return node

    def visit_expr_call(self, node: ast.ExprCall):
        raise QueryError("You can only call simple functions in HogQL, not expressions")

    def visit_block(self, node: ast.Block):
        raise QueryError("You can not use blocks in HogQL")

    def visit_lambda(self, node: ast.Lambda):
        """Visit each SELECT query or subquery."""

        # Each Lambda is a new scope in field name resolution.
        # This type keeps track of all lambda arguments that are in scope.
        node_type = ast.SelectQueryType(parent=self.scopes[-1] if len(self.scopes) > 0 else None, is_lambda_type=True)

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
            raise ResolutionError("Invalid field access with empty chain")

        node = super().visit_field(node)

        # Only look for fields in the last SELECT scope, instead of all previous select queries.
        # That's because ClickHouse does not support subqueries accessing "x.event". This is forbidden:
        # - "SELECT event, (select count() from events where event = x.event) as c FROM events x where event = '$pageview'",
        # But this is supported:
        # - "SELECT t.big_count FROM (select count() + 100 as big_count from events) as t JOIN events e ON (e.event = t.event)",
        scope = self._get_scope()

        type: Optional[ast.Type] = None
        name = str(node.chain[0])

        # If the field contains at least two parts, the first might be a table.
        type = lookup_table_by_name(scope, self.ctes, node)

        # If it's a wildcard
        if name == "*" and len(node.chain) == 1:
            table_count = len(scope.anonymous_tables) + len(scope.tables)
            if table_count == 0:
                raise QueryError("Cannot use '*' when there are no tables in the query")
            if table_count > 1:
                raise QueryError("Cannot use '*' without table name when there are multiple tables in the query")
            table_type = (
                scope.anonymous_tables[0] if len(scope.anonymous_tables) > 0 else next(iter(scope.tables.values()))
            )
            type = ast.AsteriskType(table_type=table_type)

        # Field in scope
        if not type:
            type = lookup_field_by_name(scope, name, self.context)

        # If scope is a lambda, check with the parent scope
        if not type and scope.is_lambda_type and len(self.scopes) > 1:
            type = lookup_table_by_name(self.scopes[-2], self.ctes, node)

            if not type:
                type = lookup_field_by_name(self.scopes[-2], name, self.context)

        if not type:
            cte = self.ctes.get(name, None)
            if cte:
                if len(node.chain) > 1:
                    raise QueryError(f"Cannot access fields on CTE {name} yet")

                assert isinstance(cte.type, ast.CTETableType)

                if cte.cte_type == "column":
                    # Try to extract the actual return type from the scalar CTE's SELECT query
                    # Scalar CTEs should return a single column, so we get the type of the first selected column
                    inner_type: ast.Type = ast.StringType()
                    if isinstance(cte.type.select_query_type, ast.SelectQueryType):
                        select_query_type = cte.type.select_query_type
                        if select_query_type.columns:
                            # Get the type of the first (and should be only) column
                            first_column_type = next(iter(select_query_type.columns.values()), None)
                            if first_column_type is not None:
                                inner_type = first_column_type

                    return ast.Field(chain=node.chain, type=ast.FieldAliasType(alias=name, type=inner_type))
                else:
                    # For subquery CTEs, they should only be used in FROM clauses (handled in visit_join_expr)
                    # If we get here, it means someone is trying to use a subquery CTE as a value
                    raise QueryError(f"Cannot use subquery CTE {cte.name} as a value. Use it in a FROM clause instead.")

        if not type:
            if self.context.globals is not None and name in self.context.globals:
                parsed_chain: list[str] = []
                value = self.context.globals
                for link in node.chain:
                    parsed_chain.append(str(link))
                    if isinstance(value, dict):
                        value = value.get(str(link), None)
                    elif isinstance(value, list):
                        try:
                            value = value[int(link)]
                        except (ValueError, IndexError):
                            raise QueryError(f"Cannot resolve field: {'.'.join(parsed_chain)}")
                    else:
                        raise QueryError(f"Cannot resolve field: {'.'.join(parsed_chain)}")
                global_type = resolve_constant_data_type(value)
                if global_type:
                    self.context.add_notice(
                        start=node.start,
                        end=node.end,
                        message=f"Field '{'.'.join([str(c) for c in node.chain])}' is of type '{global_type.print_type()}'",
                    )
                return ast.Constant(value=value, type=global_type)

            if self.dialect == "clickhouse":
                # To debug, add a breakpoint() here and print self.context.database
                #
                # from rich.pretty import pprint
                # pprint(self.context.database, max_depth=3)
                # breakpoint()
                #
                # One likely cause is that the database context isn't set up as you
                # expect it to be.

                raise QueryError(f"Unable to resolve field: {name}")
            else:
                type = ast.UnresolvedFieldType(name=name)
                self.context.add_error(
                    start=node.start,
                    end=node.end,
                    message=f"Unable to resolve field: {name}",
                )

        # Recursively resolve the rest of the chain until we can point to the deepest node.
        field_name = str(node.chain[-1])
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

            # TODO: This will never return None, it always raises an exception
            # once it finds the unsupported field/type
            # There's no reason to have the `if loop_type is None` check here
            loop_type = loop_type.get_child(str(next_chain), self.context)
            if loop_type is None:
                raise ResolutionError(f"Cannot resolve type {'.'.join(node.chain)}. Unable to resolve {next_chain}.")
        node.type = loop_type

        if isinstance(node.type, ast.ExpressionFieldType):
            # only swap out expression fields in ClickHouse
            if self.dialect == "clickhouse":
                new_expr = clone_expr(node.type.expr)
                new_node: ast.Expr = ast.Alias(alias=node.type.name, expr=new_expr, hidden=True)

                if node.type.isolate_scope:
                    table_type = node.type.table_type
                    while isinstance(table_type, ast.VirtualTableType):
                        table_type = table_type.table_type
                    self.scopes.append(ast.SelectQueryType(tables={node.type.name: table_type}))

                new_node = self.visit(new_node)

                if node.type.isolate_scope:
                    self.scopes.pop()
                return new_node

        if isinstance(node.type, ast.FieldType) and node.start is not None and node.end is not None:
            self.context.add_notice(
                start=node.start,
                end=node.end,
                message=f"Field '{node.type.name}' is of type '{node.type.resolve_constant_type(self.context).print_type()}'",
            )

        if isinstance(node.type, ast.FieldType):
            return ast.Alias(
                alias=field_name or node.type.name,
                expr=node,
                hidden=True,
                type=ast.FieldAliasType(alias=node.type.name, type=node.type),
            )
        elif isinstance(node.type, ast.PropertyType):
            property_alias = "__".join(str(s) for s in node.type.chain)
            return ast.Alias(
                alias=property_alias,
                expr=node,
                hidden=True,
                type=ast.FieldAliasType(alias=property_alias, type=node.type),
            )

        return node

    def visit_array_access(self, node: ast.ArrayAccess):
        node = super().visit_array_access(node)

        if self.dialect == "clickhouse" and isinstance(node.property, ast.Constant) and node.property.value == 0:
            raise QueryError("SQL indexes start from one, not from zero. E.g: array[1]")

        array = node.array
        while isinstance(array, ast.Alias):
            array = array.expr

        if (
            isinstance(array, ast.Field)
            and isinstance(node.property, ast.Constant)
            and (isinstance(node.property.value, str) or isinstance(node.property.value, int))
            and (
                (isinstance(array.type, ast.PropertyType))
                or (
                    isinstance(array.type, ast.FieldType)
                    and isinstance(
                        array.type.resolve_database_field(self.context),
                        StringJSONDatabaseField,
                    )
                )
            )
        ):
            array.chain.append(node.property.value)
            array.type = array.type.get_child(node.property.value, self.context)
            return array

        return node

    def visit_tuple_access(self, node: ast.TupleAccess):
        node = super().visit_tuple_access(node)

        if self.dialect == "clickhouse" and node.index == 0:
            raise QueryError("SQL indexes start from one, not from zero. E.g: array.1")

        tuple = node.tuple
        while isinstance(tuple, ast.Alias):
            tuple = tuple.expr

        if isinstance(tuple, ast.Field) and (
            (isinstance(tuple.type, ast.PropertyType))
            or (
                isinstance(tuple.type, ast.FieldType)
                and isinstance(tuple.type.resolve_database_field(self.context), StringJSONDatabaseField)
            )
        ):
            tuple.chain.append(node.index)
            tuple.type = tuple.type.get_child(node.index, self.context)
            return tuple

        return node

    def visit_dict(self, node: ast.Dict):
        return self.visit(convert_to_hx(node))

    def visit_between_expr(self, node: ast.BetweenExpr):
        node = super().visit_between_expr(node)
        if node is None:
            return None
        node.type = ast.BooleanType(nullable=False)
        return node

    def visit_constant(self, node: ast.Constant):
        node = super().visit_constant(node)
        if node is None:
            return None
        node.type = resolve_constant_data_type(node.value)
        return node

    def visit_and(self, node: ast.And):
        node = super().visit_and(node)
        if node is None:
            return None
        node.type = ast.BooleanType(
            nullable=any(expr.type.resolve_constant_type(self.context).nullable for expr in node.exprs)
        )
        return node

    def visit_or(self, node: ast.Or):
        node = super().visit_or(node)
        if node is None:
            return None
        node.type = ast.BooleanType(
            nullable=any(expr.type.resolve_constant_type(self.context).nullable for expr in node.exprs)
        )
        return node

    def visit_not(self, node: ast.Not):
        node = super().visit_not(node)
        if node is None:
            return None
        node.type = ast.BooleanType(nullable=node.expr.type.resolve_constant_type(self.context).nullable)
        return node

    def visit_compare_operation(self, node: ast.CompareOperation):
        if self.context.modifiers.inCohortVia == "subquery":
            if node.op == ast.CompareOperationOp.InCohort:
                return self.visit(
                    ast.CompareOperation(
                        op=ast.CompareOperationOp.In,
                        left=node.left,
                        right=cohort_query_node(node.right, context=self.context),
                    )
                )
            elif node.op == ast.CompareOperationOp.NotInCohort:
                return self.visit(
                    ast.CompareOperation(
                        op=ast.CompareOperationOp.NotIn,
                        left=node.left,
                        right=cohort_query_node(node.right, context=self.context),
                    )
                )

        node = super().visit_compare_operation(node)
        node.type = ast.BooleanType(nullable=False)

        if (
            USE_GLOBAL_JOINS
            and (node.op == ast.CompareOperationOp.In or node.op == ast.CompareOperationOp.NotIn)
            and self._is_events_table(node.left)
            and self._is_s3_cluster(node.right)
        ):
            if node.op == ast.CompareOperationOp.In:
                node.op = ast.CompareOperationOp.GlobalIn
            else:
                node.op = ast.CompareOperationOp.GlobalNotIn

        return node

    def _get_scope(self):
        if len(self.scopes) > 0:
            return self.scopes[-1]
        elif len(self.ctes) > 0:
            # Use an empty scope to allow lookups on any present CTEs
            return EMPTY_SCOPE
        else:
            raise QueryError("No scope or CTE available")

    # Used to find events table in current scope for action functions
    def _get_events_table_current_scope(self) -> tuple[Optional[str], Optional[EventsTable]]:
        scope = self._get_scope()
        for alias, table_type in scope.tables.items():
            if isinstance(table_type, ast.TableType) and isinstance(table_type.table, EventsTable):
                return alias, table_type.table

            if isinstance(table_type, ast.TableAliasType):
                if isinstance(table_type.table_type, ast.TableType) and isinstance(
                    table_type.table_type.table, EventsTable
                ):
                    return alias, table_type.table_type.table

        return None, None

    def _is_events_table(self, node: ast.Expr) -> bool:
        while isinstance(node, ast.Alias):
            node = node.expr
        if isinstance(node, ast.Field) and isinstance(node.type, ast.FieldType):
            if isinstance(node.type.table_type, ast.TableAliasType):
                return isinstance(node.type.table_type.table_type.table, EventsTable)
            if isinstance(node.type.table_type, ast.TableType):
                return isinstance(node.type.table_type.table, EventsTable)
        elif isinstance(node, ast.Field) and isinstance(node.type, ast.PropertyType):
            if isinstance(node.type.field_type.table_type, ast.TableAliasType):
                return isinstance(node.type.field_type.table_type.table_type.table, EventsTable)
            if isinstance(node.type.field_type.table_type, ast.TableType):
                return isinstance(node.type.field_type.table_type.table, EventsTable)
        return False

    def _is_s3_cluster(self, node: ast.Expr) -> bool:
        while isinstance(node, ast.Alias):
            node = node.expr
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

    def _is_s3_table(self, table: ast.TableOrSelectType) -> bool:
        if isinstance(table, ast.TableAliasType):
            return self._is_s3_table(table.table_type)

        if isinstance(table, ast.TableType):
            return isinstance(table.table, S3Table)

        return False

    def _is_next_s3(self, node: Optional[ast.JoinExpr]):
        if node is None:
            return False
        if isinstance(node.type, ast.TableAliasType):
            return self._is_s3_table(node.type)
        return False

    def _extract_tables_from_query_type(
        self, select_query_type: ast.SelectQueryType | ast.SelectSetQueryType
    ) -> list[ast.TableOrSelectType]:
        tables: list[ast.TableOrSelectType] = []
        if isinstance(select_query_type, ast.SelectQueryType):
            for t in select_query_type.tables.values():
                if isinstance(t, ast.SelectQueryAliasType):
                    tables.extend(self._extract_tables_from_query_type(t.select_query_type))
                else:
                    tables.append(t)

            for at in select_query_type.anonymous_tables:
                tables.extend(self._extract_tables_from_query_type(at))
        else:
            for sqt in select_query_type.types:
                tables.extend(self._extract_tables_from_query_type(sqt))

        return tables
