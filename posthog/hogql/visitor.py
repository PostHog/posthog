from typing import Optional

from posthog.hogql import ast


def clone_expr(self: ast.Expr, clear_refs=False) -> ast.Expr:
    """Clone an expression node."""
    return CloningVisitor(clear_refs=clear_refs).visit(self)


class Visitor(object):
    def visit(self, node: ast.AST):
        if node is None:
            return node
        return node.accept(self)


class TraversingVisitor(Visitor):
    """Visitor that traverses the AST tree without returning anything"""

    def visit_expr(self, node: ast.Expr):
        raise ValueError("Can not visit generic Expr node")

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
        self.visit(node.ref)

    def visit_field(self, node: ast.Field):
        self.visit(node.ref)

    def visit_placeholder(self, node: ast.Placeholder):
        self.visit(node.ref)

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

    def visit_lambda_argument_ref(self, node: ast.LambdaArgumentRef):
        pass

    def visit_field_alias_ref(self, node: ast.FieldAliasRef):
        self.visit(node.ref)

    def visit_field_ref(self, node: ast.FieldRef):
        self.visit(node.table)

    def visit_select_query_ref(self, node: ast.SelectQueryRef):
        for expr in node.tables.values():
            self.visit(expr)
        for expr in node.anonymous_tables:
            self.visit(expr)
        for expr in node.aliases.values():
            self.visit(expr)
        for expr in node.columns.values():
            self.visit(expr)

    def visit_select_union_query_ref(self, node: ast.SelectUnionQueryRef):
        for ref in node.refs:
            self.visit(ref)

    def visit_table_ref(self, node: ast.TableRef):
        pass

    def visit_lazy_table_ref(self, node: ast.TableRef):
        pass

    def visit_field_traverser_ref(self, node: ast.LazyJoinRef):
        self.visit(node.table)

    def visit_lazy_join_ref(self, node: ast.LazyJoinRef):
        self.visit(node.table)

    def visit_virtual_table_ref(self, node: ast.VirtualTableRef):
        self.visit(node.table)

    def visit_table_alias_ref(self, node: ast.TableAliasRef):
        self.visit(node.table_ref)

    def visit_select_query_alias_ref(self, node: ast.SelectQueryAliasRef):
        self.visit(node.ref)

    def visit_asterisk_ref(self, node: ast.AsteriskRef):
        self.visit(node.table)

    def visit_call_ref(self, node: ast.CallRef):
        for expr in node.args:
            self.visit(expr)

    def visit_constant_ref(self, node: ast.ConstantRef):
        pass

    def visit_property_ref(self, node: ast.PropertyRef):
        self.visit(node.parent)


class CloningVisitor(Visitor):
    """Visitor that traverses and clones the AST tree. Clears refs."""

    def __init__(self, clear_refs: Optional[bool] = True):
        self.clear_refs = clear_refs

    def visit_expr(self, node: ast.Expr):
        raise ValueError("Can not visit generic Expr node")

    def visit_macro(self, node: ast.Macro):
        return ast.Macro(
            name=node.name,
            expr=clone_expr(node.expr),
            type=node.type,
        )

    def visit_alias(self, node: ast.Alias):
        return ast.Alias(
            ref=None if self.clear_refs else node.ref,
            alias=node.alias,
            expr=self.visit(node.expr),
        )

    def visit_binary_operation(self, node: ast.BinaryOperation):
        return ast.BinaryOperation(
            ref=None if self.clear_refs else node.ref,
            left=self.visit(node.left),
            right=self.visit(node.right),
            op=node.op,
        )

    def visit_and(self, node: ast.And):
        return ast.And(ref=None if self.clear_refs else node.ref, exprs=[self.visit(expr) for expr in node.exprs])

    def visit_or(self, node: ast.Or):
        return ast.Or(ref=None if self.clear_refs else node.ref, exprs=[self.visit(expr) for expr in node.exprs])

    def visit_compare_operation(self, node: ast.CompareOperation):
        return ast.CompareOperation(
            ref=None if self.clear_refs else node.ref,
            left=self.visit(node.left),
            right=self.visit(node.right),
            op=node.op,
        )

    def visit_not(self, node: ast.Not):
        return ast.Not(ref=None if self.clear_refs else node.ref, expr=self.visit(node.expr))

    def visit_order_expr(self, node: ast.OrderExpr):
        return ast.OrderExpr(
            ref=None if self.clear_refs else node.ref,
            expr=self.visit(node.expr),
            order=node.order,
        )

    def visit_tuple(self, node: ast.Array):
        return ast.Tuple(ref=None if self.clear_refs else node.ref, exprs=[self.visit(expr) for expr in node.exprs])

    def visit_lambda(self, node: ast.Lambda):
        return ast.Lambda(
            ref=None if self.clear_refs else node.ref, args=[arg for arg in node.args], expr=self.visit(node.expr)
        )

    def visit_array_access(self, node: ast.ArrayAccess):
        return ast.ArrayAccess(
            ref=None if self.clear_refs else node.ref, array=self.visit(node.array), property=self.visit(node.property)
        )

    def visit_array(self, node: ast.Array):
        return ast.Array(ref=None if self.clear_refs else node.ref, exprs=[self.visit(expr) for expr in node.exprs])

    def visit_constant(self, node: ast.Constant):
        return ast.Constant(ref=None if self.clear_refs else node.ref, value=node.value)

    def visit_field(self, node: ast.Field):
        return ast.Field(ref=None if self.clear_refs else node.ref, chain=node.chain)

    def visit_placeholder(self, node: ast.Placeholder):
        return ast.Placeholder(ref=None if self.clear_refs else node.ref, field=node.field)

    def visit_call(self, node: ast.Call):
        return ast.Call(
            ref=None if self.clear_refs else node.ref,
            name=node.name,
            args=[self.visit(arg) for arg in node.args],
            distinct=node.distinct,
        )

    def visit_ratio_expr(self, node: ast.RatioExpr):
        return ast.RatioExpr(
            ref=None if self.clear_refs else node.ref, left=self.visit(node.left), right=self.visit(node.right)
        )

    def visit_sample_expr(self, node: ast.SampleExpr):
        return ast.SampleExpr(
            ref=None if self.clear_refs else node.ref,
            sample_value=self.visit(node.sample_value),
            offset_value=self.visit(node.offset_value),
        )

    def visit_join_expr(self, node: ast.JoinExpr):
        return ast.JoinExpr(
            ref=None if self.clear_refs else node.ref,
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
            ref=None if self.clear_refs else node.ref,
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
            ref=None if self.clear_refs else node.ref, select_queries=[self.visit(expr) for expr in node.select_queries]
        )
