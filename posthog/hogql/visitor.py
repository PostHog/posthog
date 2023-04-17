from typing import Optional

from posthog.hogql import ast
from posthog.hogql.errors import HogQLException


def clone_expr(self: ast.Expr, clear_types=False) -> ast.Expr:
    """Clone an expression node."""
    return CloningVisitor(clear_types=clear_types).visit(self)


class Visitor(object):
    def visit(self, node: ast.AST):
        if node is None:
            return node
        return node.accept(self)


class TraversingVisitor(Visitor):
    """Visitor that traverses the AST tree without returning anything"""

    def visit_expr(self, node: ast.Expr):
        raise HogQLException("Can not visit generic Expr node")

    def visit_macro(self, node: ast.Macro):
        pass

    def visit_alias(self, node: ast.Alias):
        self.visit(node.expr)

    def visit_binary_operation(self, node: ast.BinaryOperation):
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

    def visit_constant(self, node: ast.Constant):
        self.visit(node.type)

    def visit_field(self, node: ast.Field):
        self.visit(node.type)

    def visit_placeholder(self, node: ast.Placeholder):
        self.visit(node.type)

    def visit_call(self, node: ast.Call):
        for expr in node.args:
            self.visit(expr)

    def visit_sample_expr(self, node: ast.SampleExpr):
        self.visit(node.sample_value)
        self.visit(node.offset_value)

    def visit_ratio_expr(self, node: ast.RatioExpr):
        self.visit(node.left)
        self.visit(node.right)

    def visit_join_expr(self, node: ast.JoinExpr):
        self.visit(node.table)
        self.visit(node.constraint)
        self.visit(node.next_join)

    def visit_select_query(self, node: ast.SelectQuery):
        self.visit(node.select_from)
        for expr in node.select or []:
            self.visit(expr)
        self.visit(node.where)
        self.visit(node.prewhere)
        self.visit(node.having)
        for expr in node.group_by or []:
            self.visit(expr)
        for expr in node.order_by or []:
            self.visit(expr)
        for expr in node.limit_by or []:
            self.visit(expr)
        self.visit(node.limit),
        self.visit(node.offset),

    def visit_select_union_query(self, node: ast.SelectUnionQuery):
        for expr in node.select_queries:
            self.visit(expr)

    def visit_lambda_argument_type(self, node: ast.LambdaArgumentType):
        pass

    def visit_field_alias_type(self, node: ast.FieldAliasType):
        self.visit(node.type)

    def visit_field_type(self, node: ast.FieldType):
        self.visit(node.table_type)

    def visit_select_query_type(self, node: ast.SelectQueryType):
        for expr in node.tables.values():
            self.visit(expr)
        for expr in node.anonymous_tables:
            self.visit(expr)
        for expr in node.aliases.values():
            self.visit(expr)
        for expr in node.columns.values():
            self.visit(expr)

    def visit_select_union_query_type(self, node: ast.SelectUnionQueryType):
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

    def visit_asterisk_type(self, node: ast.AsteriskType):
        self.visit(node.table_type)

    def visit_call_type(self, node: ast.CallType):
        for expr in node.args:
            self.visit(expr)

    def visit_constant_type(self, node: ast.ConstantType):
        pass

    def visit_property_type(self, node: ast.PropertyType):
        self.visit(node.field_type)


class CloningVisitor(Visitor):
    """Visitor that traverses and clones the AST tree. Clears types."""

    def __init__(self, clear_types: Optional[bool] = True):
        self.clear_types = clear_types

    def visit_expr(self, node: ast.Expr):
        raise HogQLException("Can not visit generic Expr node")

    def visit_macro(self, node: ast.Macro):
        return ast.Macro(
            type=None if self.clear_types else node.type,
            name=node.name,
            expr=clone_expr(node.expr),
            macro_type=node.macro_type,
        )

    def visit_alias(self, node: ast.Alias):
        return ast.Alias(
            type=None if self.clear_types else node.type,
            alias=node.alias,
            expr=self.visit(node.expr),
        )

    def visit_binary_operation(self, node: ast.BinaryOperation):
        return ast.BinaryOperation(
            type=None if self.clear_types else node.type,
            left=self.visit(node.left),
            right=self.visit(node.right),
            op=node.op,
        )

    def visit_and(self, node: ast.And):
        return ast.And(type=None if self.clear_types else node.type, exprs=[self.visit(expr) for expr in node.exprs])

    def visit_or(self, node: ast.Or):
        return ast.Or(type=None if self.clear_types else node.type, exprs=[self.visit(expr) for expr in node.exprs])

    def visit_compare_operation(self, node: ast.CompareOperation):
        return ast.CompareOperation(
            type=None if self.clear_types else node.type,
            left=self.visit(node.left),
            right=self.visit(node.right),
            op=node.op,
        )

    def visit_not(self, node: ast.Not):
        return ast.Not(type=None if self.clear_types else node.type, expr=self.visit(node.expr))

    def visit_order_expr(self, node: ast.OrderExpr):
        return ast.OrderExpr(
            type=None if self.clear_types else node.type,
            expr=self.visit(node.expr),
            order=node.order,
        )

    def visit_tuple(self, node: ast.Array):
        return ast.Tuple(type=None if self.clear_types else node.type, exprs=[self.visit(expr) for expr in node.exprs])

    def visit_lambda(self, node: ast.Lambda):
        return ast.Lambda(
            type=None if self.clear_types else node.type, args=[arg for arg in node.args], expr=self.visit(node.expr)
        )

    def visit_array_access(self, node: ast.ArrayAccess):
        return ast.ArrayAccess(
            type=None if self.clear_types else node.type,
            array=self.visit(node.array),
            property=self.visit(node.property),
        )

    def visit_array(self, node: ast.Array):
        return ast.Array(type=None if self.clear_types else node.type, exprs=[self.visit(expr) for expr in node.exprs])

    def visit_constant(self, node: ast.Constant):
        return ast.Constant(type=None if self.clear_types else node.type, value=node.value)

    def visit_field(self, node: ast.Field):
        return ast.Field(type=None if self.clear_types else node.type, chain=node.chain)

    def visit_placeholder(self, node: ast.Placeholder):
        return ast.Placeholder(type=None if self.clear_types else node.type, field=node.field)

    def visit_call(self, node: ast.Call):
        return ast.Call(
            type=None if self.clear_types else node.type,
            name=node.name,
            args=[self.visit(arg) for arg in node.args],
            distinct=node.distinct,
        )

    def visit_ratio_expr(self, node: ast.RatioExpr):
        return ast.RatioExpr(
            type=None if self.clear_types else node.type, left=self.visit(node.left), right=self.visit(node.right)
        )

    def visit_sample_expr(self, node: ast.SampleExpr):
        return ast.SampleExpr(
            type=None if self.clear_types else node.type,
            sample_value=self.visit(node.sample_value),
            offset_value=self.visit(node.offset_value),
        )

    def visit_join_expr(self, node: ast.JoinExpr):
        return ast.JoinExpr(
            type=None if self.clear_types else node.type,
            table=self.visit(node.table),
            next_join=self.visit(node.next_join),
            table_final=node.table_final,
            alias=node.alias,
            join_type=node.join_type,
            constraint=self.visit(node.constraint),
            sample=self.visit(node.sample),
        )

    def visit_select_query(self, node: ast.SelectQuery):
        return ast.SelectQuery(
            type=None if self.clear_types else node.type,
            macros={key: expr for key, expr in node.macros.items()} if node.macros else None,  # to not traverse
            select=[self.visit(expr) for expr in node.select] if node.select else None,
            select_from=self.visit(node.select_from),
            where=self.visit(node.where),
            prewhere=self.visit(node.prewhere),
            having=self.visit(node.having),
            group_by=[self.visit(expr) for expr in node.group_by] if node.group_by else None,
            order_by=[self.visit(expr) for expr in node.order_by] if node.order_by else None,
            limit_by=[self.visit(expr) for expr in node.limit_by] if node.limit_by else None,
            limit=self.visit(node.limit),
            limit_with_ties=node.limit_with_ties,
            offset=self.visit(node.offset),
            distinct=node.distinct,
        )

    def visit_select_union_query(self, node: ast.SelectUnionQuery):
        return ast.SelectUnionQuery(
            type=None if self.clear_types else node.type,
            select_queries=[self.visit(expr) for expr in node.select_queries],
        )
