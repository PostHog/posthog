from copy import deepcopy
from typing import Any, Generic, Optional, TypeVar

from posthog.hogql import ast
from posthog.hogql.ast import SelectSetNode
from posthog.hogql.base import AST, Expr
from posthog.hogql.errors import BaseHogQLError
from posthog.hogql.utils import is_simple_value

T = TypeVar("T")
T_AST = TypeVar("T_AST", bound=AST)
T_Expr = TypeVar("T_Expr", bound=Expr)


def clone_expr(expr: T_AST, clear_types=False, clear_locations=False, inline_subquery_field_names=False) -> T_AST:
    """Clone an expression node."""
    return CloningVisitor(
        clear_types=clear_types,
        clear_locations=clear_locations,
        inline_subquery_field_names=inline_subquery_field_names,
    ).visit(expr)


def clear_locations(expr: T_AST) -> T_AST:
    return CloningVisitor(clear_locations=True).visit(expr)


class Visitor(Generic[T]):
    def visit(self, node: AST | None) -> T:
        if node is None:
            return node  # type: ignore

        try:
            return node.accept(self)
        except BaseHogQLError as e:
            if e.start is None or e.end is None:
                e.start = node.start
                e.end = node.end
            raise


class TraversingVisitor(Visitor[None]):
    """Visitor that traverses the AST tree without returning anything"""

    def visit_cte(self, node: ast.CTE):
        pass

    def visit_alias(self, node: ast.Alias):
        self.visit(node.expr)

    def visit_arithmetic_operation(self, node: ast.ArithmeticOperation):
        self.visit(node.left)
        self.visit(node.right)

    def visit_and(self, node: ast.And):
        for expr in node.exprs:
            self.visit(expr)

    def visit_or(self, node: ast.Or):
        for expr in node.exprs:
            self.visit(expr)

    def visit_compare_operation(self, node: ast.CompareOperation):
        self.visit(node.left)
        self.visit(node.right)

    def visit_not(self, node: ast.Not):
        self.visit(node.expr)

    def visit_order_expr(self, node: ast.OrderExpr):
        self.visit(node.expr)

    def visit_tuple_access(self, node: ast.TupleAccess):
        self.visit(node.tuple)

    def visit_tuple(self, node: ast.Tuple):
        for expr in node.exprs:
            self.visit(expr)

    def visit_lambda(self, node: ast.Lambda):
        self.visit(node.expr)

    def visit_array_access(self, node: ast.ArrayAccess):
        self.visit(node.array)
        self.visit(node.property)

    def visit_array(self, node: ast.Array):
        for expr in node.exprs:
            self.visit(expr)

    def visit_dict(self, node: ast.Dict):
        for key, value in node.items:
            self.visit(key)
            self.visit(value)

    def visit_constant(self, node: ast.Constant):
        self.visit(node.type)

    def visit_field(self, node: ast.Field):
        self.visit(node.type)

    def visit_placeholder(self, node: ast.Placeholder):
        self.visit(node.expr)

    def visit_call(self, node: ast.Call):
        for expr in node.args:
            self.visit(expr)
        if node.params:
            for expr in node.params:
                self.visit(expr)

    def visit_expr_call(self, node: ast.ExprCall):
        self.visit(node.expr)
        for expr in node.args:
            self.visit(expr)

    def visit_sample_expr(self, node: ast.SampleExpr):
        self.visit(node.sample_value)
        self.visit(node.offset_value)

    def visit_ratio_expr(self, node: ast.RatioExpr):
        self.visit(node.left)
        self.visit(node.right)

    def visit_join_expr(self, node: ast.JoinExpr):
        # :TRICKY: when adding new fields, also add them to visit_select_query of resolver.py
        self.visit(node.table)
        for expr in node.table_args or []:
            self.visit(expr)
        self.visit(node.constraint)
        self.visit(node.next_join)

    def visit_select_query(self, node: ast.SelectQuery):
        # :TRICKY: when adding new fields, also add them to visit_select_query of resolver.py
        self.visit(node.select_from)
        if node.ctes is not None:
            for expr0 in list(node.ctes.values()):
                self.visit(expr0)
        for expr1 in node.array_join_list or []:
            self.visit(expr1)
        for expr2 in node.select or []:
            self.visit(expr2)
        self.visit(node.where)
        self.visit(node.prewhere)
        self.visit(node.having)
        for expr3 in node.group_by or []:
            self.visit(expr3)
        for expr4 in node.order_by or []:
            self.visit(expr4)
        self.visit(node.limit_by)
        self.visit(node.limit)
        self.visit(node.offset)
        for expr5 in (node.window_exprs or {}).values():
            self.visit(expr5)

    def visit_select_set_query(self, node: ast.SelectSetQuery):
        self.visit(node.initial_select_query)
        for expr in node.subsequent_select_queries:
            self.visit(expr.select_query)

    def visit_lambda_argument_type(self, node: ast.LambdaArgumentType):
        pass

    def visit_field_alias_type(self, node: ast.FieldAliasType):
        self.visit(node.type)

    def visit_field_type(self, node: ast.FieldType):
        pass

    def visit_select_query_type(self, node: ast.SelectQueryType):
        for expr0 in node.tables.values():
            self.visit(expr0)
        for expr1 in node.anonymous_tables:
            self.visit(expr1)
        for expr2 in node.aliases.values():
            self.visit(expr2)
        for expr3 in node.columns.values():
            self.visit(expr3)

    def visit_select_set_query_type(self, node: ast.SelectSetQueryType):
        for type in node.types:
            self.visit(type)

    def visit_table_type(self, node: ast.TableType):
        pass

    def visit_lazy_table_type(self, node: ast.TableType):
        pass

    def visit_field_traverser_type(self, node: ast.LazyJoinType):
        self.visit(node.table_type)

    def visit_lazy_join_type(self, node: ast.LazyJoinType):
        self.visit(node.table_type)

    def visit_virtual_table_type(self, node: ast.VirtualTableType):
        self.visit(node.table_type)

    def visit_table_alias_type(self, node: ast.TableAliasType):
        self.visit(node.table_type)

    def visit_select_query_alias_type(self, node: ast.SelectQueryAliasType):
        self.visit(node.select_query_type)

    def visit_select_view_type(self, node: ast.SelectViewType):
        self.visit(node.select_query_type)

    def visit_asterisk_type(self, node: ast.AsteriskType):
        self.visit(node.table_type)

    def visit_call_type(self, node: ast.CallType):
        for expr in node.arg_types:
            self.visit(expr)
        if node.param_types:
            for expr in node.param_types:
                self.visit(expr)

    def visit_integer_type(self, node: ast.IntegerType):
        pass

    def visit_float_type(self, node: ast.FloatType):
        pass

    def visit_decimal_type(self, node: ast.DecimalType):
        pass

    def visit_string_type(self, node: ast.StringType):
        pass

    def visit_string_json_type(self, node: ast.StringJSONType):
        pass

    def visit_string_array_type(self, node: ast.StringArrayType):
        pass

    def visit_boolean_type(self, node: ast.BooleanType):
        pass

    def visit_unknown_type(self, node: ast.UnknownType):
        pass

    def visit_array_type(self, node: ast.ArrayType):
        self.visit(node.item_type)

    def visit_tuple_type(self, node: ast.TupleType):
        for expr in node.item_types:
            self.visit(expr)

    def visit_date_type(self, node: ast.DateType):
        pass

    def visit_date_time_type(self, node: ast.DateTimeType):
        pass

    def visit_interval_type(self, node: ast.IntervalType):
        pass

    def visit_uuid_type(self, node: ast.UUIDType):
        pass

    def visit_property_type(self, node: ast.PropertyType):
        self.visit(node.field_type)

    def visit_map_property_type(self, node: ast.PropertyType):
        self.visit(node.field_type)

    def visit_expression_field_type(self, node: ast.ExpressionFieldType):
        pass

    def visit_unresolved_field_type(self, node: ast.UnresolvedFieldType):
        pass

    def visit_window_expr(self, node: ast.WindowExpr):
        for expr in node.partition_by or []:
            self.visit(expr)
        for expr in node.order_by or []:
            self.visit(expr)
        self.visit(node.frame_start)
        self.visit(node.frame_end)

    def visit_window_function(self, node: ast.WindowFunction):
        for expr in node.exprs or []:
            self.visit(expr)
        for arg in node.args or []:
            self.visit(arg)
        self.visit(node.over_expr)

    def visit_window_frame_expr(self, node: ast.WindowFrameExpr):
        pass

    def visit_join_constraint(self, node: ast.JoinConstraint):
        self.visit(node.expr)

    def visit_hogqlx_tag(self, node: ast.HogQLXTag):
        for attribute in node.attributes:
            self.visit(attribute)

    def visit_hogqlx_attribute(self, node: ast.HogQLXAttribute):
        if isinstance(node.value, list):
            for value in node.value:
                if is_simple_value(value):
                    self.visit(ast.Constant(value=value))
                else:
                    self.visit(value)
        else:
            self.visit(node.value)

    def visit_program(self, node: ast.Program):
        for expr in node.declarations:
            self.visit(expr)

    def visit_limit_by_expr(self, node: ast.LimitByExpr):
        self.visit(node.n)
        if node.offset_value:
            self.visit(node.offset_value)
        for expr in node.exprs:
            self.visit(expr)

    def visit_statement(self, node: ast.Statement):
        raise NotImplementedError("Abstract 'visit_statement' not implemented")

    def visit_block(self, node: ast.Block):
        for expr in node.declarations:
            self.visit(expr)

    def visit_if_statement(self, node: ast.IfStatement):
        self.visit(node.expr)
        self.visit(node.then)
        if node.else_:
            self.visit(node.else_)

    def visit_while_statement(self, node: ast.WhileStatement):
        self.visit(node.expr)
        self.visit(node.body)

    def visit_for_statement(self, node: ast.ForStatement):
        if node.initializer:
            self.visit(node.initializer)
        self.visit(node.condition)
        self.visit(node.increment)
        self.visit(node.body)

    def visit_for_in_statement(self, node: ast.ForInStatement):
        self.visit(node.expr)
        self.visit(node.body)

    def visit_expr_statement(self, node: ast.ExprStatement):
        self.visit(node.expr)

    def visit_return_statement(self, node: ast.ReturnStatement):
        if node.expr:
            self.visit(node.expr)

    def visit_throw_statement(self, node: ast.ThrowStatement):
        if node.expr:
            self.visit(node.expr)

    def visit_try_catch_statement(self, node: ast.TryCatchStatement):
        self.visit(node.try_stmt)
        for catch in node.catches:
            self.visit(catch[2])
        self.visit(node.finally_stmt)

    def visit_function(self, node: ast.Function):
        self.visit(node.body)

    def visit_declaration(self, node: ast.Declaration):
        raise NotImplementedError("Abstract 'visit_declaration' not implemented")

    def visit_variable_declaration(self, node: ast.VariableDeclaration):
        if node.expr:
            self.visit(node.expr)

    def visit_variable_assignment(self, node: ast.VariableAssignment):
        self.visit(node.left)
        self.visit(node.right)


class CloningVisitor(Visitor[Any]):
    """Visitor that traverses and clones the AST tree. Clears types."""

    def __init__(
        self,
        clear_types: Optional[bool] = True,
        clear_locations: Optional[bool] = False,
        inline_subquery_field_names: Optional[bool] = False,
    ):
        self.clear_types = clear_types
        self.clear_locations = clear_locations
        self.inline_subquery_field_names = inline_subquery_field_names

    def visit_cte(self, node: ast.CTE):
        return ast.CTE(
            start=None if self.clear_locations else node.start,
            end=None if self.clear_locations else node.end,
            type=None if self.clear_types else node.type,
            name=node.name,
            expr=self.visit(node.expr),
            cte_type=node.cte_type,
        )

    def visit_alias(self, node: ast.Alias):
        return ast.Alias(
            start=None if self.clear_locations else node.start,
            end=None if self.clear_locations else node.end,
            type=None if self.clear_types else node.type,
            alias=node.alias,
            hidden=node.hidden,
            expr=self.visit(node.expr),
        )

    def visit_arithmetic_operation(self, node: ast.ArithmeticOperation):
        return ast.ArithmeticOperation(
            start=None if self.clear_locations else node.start,
            end=None if self.clear_locations else node.end,
            type=None if self.clear_types else node.type,
            left=self.visit(node.left),
            right=self.visit(node.right),
            op=node.op,
        )

    def visit_and(self, node: ast.And):
        return ast.And(
            start=None if self.clear_locations else node.start,
            end=None if self.clear_locations else node.end,
            type=None if self.clear_types else node.type,
            exprs=[self.visit(expr) for expr in node.exprs],
        )

    def visit_or(self, node: ast.Or):
        return ast.Or(
            start=None if self.clear_locations else node.start,
            end=None if self.clear_locations else node.end,
            type=None if self.clear_types else node.type,
            exprs=[self.visit(expr) for expr in node.exprs],
        )

    def visit_compare_operation(self, node: ast.CompareOperation):
        return ast.CompareOperation(
            start=None if self.clear_locations else node.start,
            end=None if self.clear_locations else node.end,
            type=None if self.clear_types else node.type,
            left=self.visit(node.left),
            right=self.visit(node.right),
            op=node.op,
        )

    def visit_not(self, node: ast.Not):
        return ast.Not(
            start=None if self.clear_locations else node.start,
            end=None if self.clear_locations else node.end,
            type=None if self.clear_types else node.type,
            expr=self.visit(node.expr),
        )

    def visit_order_expr(self, node: ast.OrderExpr):
        return ast.OrderExpr(
            start=None if self.clear_locations else node.start,
            end=None if self.clear_locations else node.end,
            type=None if self.clear_types else node.type,
            expr=self.visit(node.expr),
            order=node.order,
        )

    def visit_tuple_access(self, node: ast.TupleAccess):
        return ast.TupleAccess(
            start=None if self.clear_locations else node.start,
            end=None if self.clear_locations else node.end,
            type=None if self.clear_types else node.type,
            tuple=self.visit(node.tuple),
            index=node.index,
            nullish=node.nullish,
        )

    def visit_tuple(self, node: ast.Tuple):
        return ast.Tuple(
            start=None if self.clear_locations else node.start,
            end=None if self.clear_locations else node.end,
            type=None if self.clear_types else node.type,
            exprs=[self.visit(expr) for expr in node.exprs],
        )

    def visit_lambda(self, node: ast.Lambda):
        return ast.Lambda(
            start=None if self.clear_locations else node.start,
            end=None if self.clear_locations else node.end,
            type=None if self.clear_types else node.type,
            args=list(node.args),
            expr=self.visit(node.expr),
        )

    def visit_array_access(self, node: ast.ArrayAccess):
        return ast.ArrayAccess(
            start=None if self.clear_locations else node.start,
            end=None if self.clear_locations else node.end,
            type=None if self.clear_types else node.type,
            array=self.visit(node.array),
            property=self.visit(node.property),
            nullish=node.nullish,
        )

    def visit_array(self, node: ast.Array):
        return ast.Array(
            start=None if self.clear_locations else node.start,
            end=None if self.clear_locations else node.end,
            type=None if self.clear_types else node.type,
            exprs=[self.visit(expr) for expr in node.exprs],
        )

    def visit_dict(self, node: ast.Dict):
        return ast.Dict(
            start=None if self.clear_locations else node.start,
            end=None if self.clear_locations else node.end,
            type=None if self.clear_types else node.type,
            items=[(self.visit(key), self.visit(value)) for key, value in node.items],
        )

    def visit_constant(self, node: ast.Constant):
        return ast.Constant(
            start=None if self.clear_locations else node.start,
            end=None if self.clear_locations else node.end,
            type=None if self.clear_types else node.type,
            value=node.value,
        )

    def visit_field(self, node: ast.Field):
        field = ast.Field(
            start=None if self.clear_locations else node.start,
            end=None if self.clear_locations else node.end,
            type=None if self.clear_types else node.type,
            chain=node.chain.copy(),
        )
        if (
            self.inline_subquery_field_names
            and isinstance(node.type, ast.PropertyType)
            and node.type.joined_subquery is not None
            and node.type.joined_subquery_field_name is not None
        ):
            field.chain = [node.type.joined_subquery_field_name]
        return field

    def visit_placeholder(self, node: ast.Placeholder):
        return ast.Placeholder(
            start=None if self.clear_locations else node.start,
            end=None if self.clear_locations else node.end,
            type=None if self.clear_types else node.type,
            expr=self.visit(node.expr),
        )

    def visit_call(self, node: ast.Call):
        return ast.Call(
            start=None if self.clear_locations else node.start,
            end=None if self.clear_locations else node.end,
            type=None if self.clear_types else node.type,
            name=node.name,
            args=[self.visit(arg) for arg in node.args],
            params=[self.visit(param) for param in node.params] if node.params is not None else None,
            distinct=node.distinct,
        )

    def visit_expr_call(self, node: ast.ExprCall):
        return ast.ExprCall(
            start=None if self.clear_locations else node.start,
            end=None if self.clear_locations else node.end,
            type=None if self.clear_types else node.type,
            expr=self.visit(node.expr),
            args=[self.visit(arg) for arg in node.args],
        )

    def visit_ratio_expr(self, node: ast.RatioExpr):
        return ast.RatioExpr(
            start=None if self.clear_locations else node.start,
            end=None if self.clear_locations else node.end,
            type=None if self.clear_types else node.type,
            left=self.visit(node.left),
            right=self.visit(node.right),
        )

    def visit_sample_expr(self, node: ast.SampleExpr):
        return ast.SampleExpr(
            start=None if self.clear_locations else node.start,
            end=None if self.clear_locations else node.end,
            type=None if self.clear_types else node.type,
            sample_value=self.visit(node.sample_value),
            offset_value=self.visit(node.offset_value),
        )

    def visit_join_expr(self, node: ast.JoinExpr):
        # :TRICKY: when adding new fields, also add them to visit_join_expr of resolver.py
        return ast.JoinExpr(
            start=None if self.clear_locations else node.start,
            end=None if self.clear_locations else node.end,
            type=None if self.clear_types else node.type,
            table=self.visit(node.table),
            table_args=[self.visit(expr) for expr in node.table_args] if node.table_args is not None else None,
            next_join=self.visit(node.next_join),
            table_final=node.table_final,
            alias=node.alias,
            join_type=node.join_type,
            constraint=self.visit(node.constraint),
            sample=self.visit(node.sample),
        )

    def visit_select_query(self, node: ast.SelectQuery):
        # :TRICKY: when adding new fields, also add them to visit_select_query of resolver.py
        return ast.SelectQuery(
            start=None if self.clear_locations else node.start,
            end=None if self.clear_locations else node.end,
            type=None if self.clear_types else node.type,
            ctes={key: self.visit(expr) for key, expr in node.ctes.items()} if node.ctes else None,  # to not traverse
            select_from=self.visit(node.select_from),  # keep "select_from" before "select" to resolve tables first
            select=[self.visit(expr) for expr in node.select] if node.select else [],
            array_join_op=node.array_join_op,
            array_join_list=[self.visit(expr) for expr in node.array_join_list] if node.array_join_list else None,
            where=self.visit(node.where),
            prewhere=self.visit(node.prewhere),
            having=self.visit(node.having),
            group_by=[self.visit(expr) for expr in node.group_by] if node.group_by else None,
            order_by=[self.visit(expr) for expr in node.order_by] if node.order_by else None,
            limit_by=self.visit(node.limit_by),
            limit=self.visit(node.limit),
            limit_with_ties=node.limit_with_ties,
            offset=self.visit(node.offset),
            distinct=node.distinct,
            window_exprs=(
                {name: self.visit(expr) for name, expr in node.window_exprs.items()} if node.window_exprs else None
            ),
            settings=node.settings.model_copy() if node.settings is not None else None,
            view_name=node.view_name,
        )

    def visit_select_set_query(self, node: ast.SelectSetQuery):
        return ast.SelectSetQuery(
            start=None if self.clear_locations else node.start,
            end=None if self.clear_locations else node.end,
            type=None if self.clear_types else node.type,
            initial_select_query=self.visit(node.initial_select_query),
            subsequent_select_queries=[
                SelectSetNode(set_operator=expr.set_operator, select_query=self.visit(expr.select_query))
                for expr in node.subsequent_select_queries
            ],
        )

    def visit_window_expr(self, node: ast.WindowExpr):
        return ast.WindowExpr(
            start=None if self.clear_locations else node.start,
            end=None if self.clear_locations else node.end,
            type=None if self.clear_types else node.type,
            partition_by=[self.visit(expr) for expr in node.partition_by] if node.partition_by else None,
            order_by=[self.visit(expr) for expr in node.order_by] if node.order_by else None,
            frame_method=node.frame_method,
            frame_start=self.visit(node.frame_start),
            frame_end=self.visit(node.frame_end),
        )

    def visit_window_function(self, node: ast.WindowFunction):
        return ast.WindowFunction(
            start=None if self.clear_locations else node.start,
            end=None if self.clear_locations else node.end,
            type=None if self.clear_types else node.type,
            name=node.name,
            exprs=[self.visit(expr) for expr in node.exprs] if node.exprs else None,
            args=[self.visit(arg) for arg in node.args] if node.args else None,
            over_expr=self.visit(node.over_expr) if node.over_expr else None,
            over_identifier=node.over_identifier,
        )

    def visit_window_frame_expr(self, node: ast.WindowFrameExpr):
        return ast.WindowFrameExpr(
            start=None if self.clear_locations else node.start,
            end=None if self.clear_locations else node.end,
            type=None if self.clear_types else node.type,
            frame_type=node.frame_type,
            frame_value=node.frame_value,
        )

    def visit_join_constraint(self, node: ast.JoinConstraint) -> ast.JoinConstraint:
        return ast.JoinConstraint(expr=self.visit(node.expr), constraint_type=node.constraint_type)

    def visit_hogqlx_tag(self, node: ast.HogQLXTag):
        return ast.HogQLXTag(kind=node.kind, attributes=[self.visit(a) for a in node.attributes])

    def visit_hogqlx_attribute(self, node: ast.HogQLXAttribute):
        if isinstance(node.value, list):
            return ast.HogQLXAttribute(
                name=node.name,
                value=[self.visit(ast.Constant(value=v)) if is_simple_value(v) else self.visit(v) for v in node.value],
            )

        value = node.value
        if is_simple_value(value):
            value = ast.Constant(value=value)
        return ast.HogQLXAttribute(name=node.name, value=self.visit(value))

    def visit_program(self, node: ast.Program):
        return ast.Program(
            start=None if self.clear_locations else node.start,
            end=None if self.clear_locations else node.end,
            declarations=[self.visit(expr) for expr in node.declarations],
        )

    def visit_statement(self, node: ast.Statement):
        raise NotImplementedError("Abstract 'visit_statement' not implemented")

    def visit_block(self, node: ast.Block):
        return ast.Block(
            start=None if self.clear_locations else node.start,
            end=None if self.clear_locations else node.end,
            declarations=[self.visit(expr) for expr in node.declarations],
        )

    def visit_if_statement(self, node: ast.IfStatement):
        return ast.IfStatement(
            start=None if self.clear_locations else node.start,
            end=None if self.clear_locations else node.end,
            expr=self.visit(node.expr),
            then=self.visit(node.then),
            else_=self.visit(node.else_) if node.else_ else None,
        )

    def visit_while_statement(self, node: ast.WhileStatement):
        return ast.WhileStatement(
            start=None if self.clear_locations else node.start,
            end=None if self.clear_locations else node.end,
            expr=self.visit(node.expr),
            body=self.visit(node.body),
        )

    def visit_for_statement(self, node: ast.ForStatement):
        return ast.ForStatement(
            start=None if self.clear_locations else node.start,
            end=None if self.clear_locations else node.end,
            initializer=self.visit(node.initializer) if node.initializer else None,
            condition=self.visit(node.condition),
            increment=self.visit(node.increment),
            body=self.visit(node.body),
        )

    def visit_for_in_statement(self, node: ast.ForInStatement):
        return ast.ForInStatement(
            start=None if self.clear_locations else node.start,
            end=None if self.clear_locations else node.end,
            valueVar=node.valueVar,
            keyVar=node.keyVar,
            expr=self.visit(node.expr),
            body=self.visit(node.body),
        )

    def visit_expr_statement(self, node: ast.ExprStatement):
        return ast.ExprStatement(
            start=None if self.clear_locations else node.start,
            end=None if self.clear_locations else node.end,
            expr=self.visit(node.expr),
        )

    def visit_return_statement(self, node: ast.ReturnStatement):
        return ast.ReturnStatement(
            start=None if self.clear_locations else node.start,
            end=None if self.clear_locations else node.end,
            expr=self.visit(node.expr) if node.expr else None,
        )

    def visit_throw_statement(self, node: ast.ThrowStatement):
        return ast.ThrowStatement(
            start=None if self.clear_locations else node.start,
            end=None if self.clear_locations else node.end,
            expr=self.visit(node.expr) if node.expr else None,
        )

    def visit_try_catch_statement(self, node: ast.TryCatchStatement):
        return ast.TryCatchStatement(
            start=None if self.clear_locations else node.start,
            end=None if self.clear_locations else node.end,
            try_stmt=self.visit(node.try_stmt),
            catches=[(c[0], c[1], self.visit(c[2])) for c in node.catches],
            finally_stmt=self.visit(node.finally_stmt),
        )

    def visit_function(self, node: ast.Function):
        return ast.Function(
            start=None if self.clear_locations else node.start,
            end=None if self.clear_locations else node.end,
            name=node.name,
            params=deepcopy(node.params),
            body=self.visit(node.body),
        )

    def visit_declaration(self, node: ast.Declaration):
        raise NotImplementedError("Abstract 'visit_declaration' not implemented")

    def visit_variable_declaration(self, node: ast.VariableDeclaration):
        return ast.VariableDeclaration(
            start=None if self.clear_locations else node.start,
            end=None if self.clear_locations else node.end,
            name=node.name,
            expr=self.visit(node.expr) if node.expr else None,
        )

    def visit_variable_assignment(self, node: ast.VariableAssignment):
        return ast.VariableAssignment(
            start=None if self.clear_locations else node.start,
            end=None if self.clear_locations else node.end,
            left=self.visit(node.left),
            right=self.visit(node.right),
        )

    def visit_limit_by_expr(self, node: ast.LimitByExpr) -> ast.LimitByExpr:
        return ast.LimitByExpr(
            start=None if self.clear_locations else node.start,
            end=None if self.clear_locations else node.end,
            n=self.visit(node.n),
            offset_value=self.visit(node.offset_value) if node.offset_value is not None else None,
            exprs=[self.visit(expr) for expr in node.exprs],
        )

    def visit_select_set_node(self, node: ast.SelectSetNode) -> ast.SelectSetNode:
        return ast.SelectSetNode(
            start=None if self.clear_locations else node.start,
            end=None if self.clear_locations else node.end,
            set_operator=node.set_operator,
            select_query=self.visit(node.select_query),
        )
