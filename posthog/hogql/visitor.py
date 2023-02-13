from posthog.hogql import ast


class Visitor(object):
    def visit(self, node: ast.AST):
        if node is None:
            return node
        return node.accept(self)


class TraversingVisitor(Visitor):
    """Visitor that traverses the AST tree without returning anything"""

    def visit_expr(self, node: ast.Expr):
        raise ValueError("Can not visit generic Expr node")

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

    def visit_constant(self, node: ast.Constant):
        pass

    def visit_field(self, node: ast.Field):
        pass

    def visit_placeholder(self, node: ast.Placeholder):
        pass

    def visit_call(self, node: ast.Call):
        for expr in node.args:
            self.visit(expr)

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


class CloningVisitor(Visitor):
    """Visitor that traverses and clones the AST tree"""

    def visit_expr(self, node: ast.Expr):
        raise ValueError("Can not visit generic Expr node")

    def visit_alias(self, node: ast.Alias):
        return ast.Alias(
            alias=node.alias,
            expr=self.visit(node.expr),
        )

    def visit_binary_operation(self, node: ast.BinaryOperation):
        return ast.BinaryOperation(
            left=self.visit(node.left),
            right=self.visit(node.right),
            op=node.op,
        )

    def visit_and(self, node: ast.And):
        return ast.And(exprs=[self.visit(expr) for expr in node.exprs])

    def visit_or(self, node: ast.Or):
        return ast.Or(exprs=[self.visit(expr) for expr in node.exprs])

    def visit_compare_operation(self, node: ast.CompareOperation):
        return ast.CompareOperation(
            left=self.visit(node.left),
            right=self.visit(node.right),
            op=node.op,
        )

    def visit_not(self, node: ast.Not):
        return ast.Not(expr=self.visit(node.expr))

    def visit_order_expr(self, node: ast.OrderExpr):
        return ast.OrderExpr(
            expr=self.visit(node.expr),
            order=node.order,
        )

    def visit_constant(self, node: ast.Constant):
        return node

    def visit_field(self, node: ast.Field):
        return node

    def visit_placeholder(self, node: ast.Placeholder):
        return node

    def visit_call(self, node: ast.Call):
        return ast.Call(
            name=node.name,
            args=[self.visit(arg) for arg in node.args],
        )

    def visit_join_expr(self, node: ast.JoinExpr):
        return ast.JoinExpr(
            table=self.visit(node.table),
            next_join=self.visit(node.next_join),
            table_final=node.table_final,
            alias=node.alias,
            join_type=node.join_type,
            constraint=self.visit(node.constraint),
        )

    def visit_select_query(self, node: ast.SelectQuery):
        return ast.SelectQuery(
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
