from posthog.hogql import ast
from posthog.hogql.transforms.trino.errors import TrinoLoweringError
from posthog.hogql.visitor import CloningVisitor, TraversingVisitor


class _WindowFunctionFinder(TraversingVisitor):
    found: bool = False

    def visit_window_function(self, node: ast.WindowFunction) -> None:
        self.found = True
        super().visit_window_function(node)


class TrinoQueryWrapperLowerer(CloningVisitor):
    def __init__(self) -> None:
        super().__init__(clear_types=False)
        self.wrapper_index = 0

    def visit_select_query(self, node: ast.SelectQuery) -> ast.SelectQuery:
        lowered = super().visit_select_query(node)
        if lowered.qualify is not None and lowered.limit_by is not None:
            raise TrinoLoweringError("TRINO_QUALIFY_LIMIT_BY_UNSUPPORTED", "combined QUALIFY and LIMIT BY", node)
        if lowered.qualify is not None:
            lowered = self._lower_qualify(lowered)
        if lowered.limit_by is not None:
            lowered = self._lower_limit_by(lowered)
        return lowered

    def _lower_qualify(self, node: ast.SelectQuery) -> ast.SelectQuery:
        assert node.qualify is not None
        finder = _WindowFunctionFinder()
        finder.visit(node.qualify)
        if finder.found:
            raise TrinoLoweringError(
                "TRINO_QUALIFY_WINDOW_NOT_PROJECTED",
                "QUALIFY window expression without a projected alias",
                node.qualify,
            )
        predicate = node.qualify
        node.qualify = None
        return self._wrap(node, predicate)

    def _lower_limit_by(self, node: ast.SelectQuery) -> ast.SelectQuery:
        assert node.limit_by is not None
        if node.distinct:
            raise TrinoLoweringError("TRINO_LIMIT_BY_DISTINCT_UNSUPPORTED", "LIMIT BY with DISTINCT", node)
        n = self._non_negative_integer(node.limit_by.n, "LIMIT BY count")
        offset = self._non_negative_integer(node.limit_by.offset_value, "LIMIT BY offset", default=0)
        helper_name = f"__hogql_limit_by_row_{self.wrapper_index}"
        row_number = ast.WindowFunction(
            name="row_number",
            exprs=[],
            over_expr=ast.WindowExpr(
                partition_by=[self._unwrap_hidden_alias(expr) for expr in node.limit_by.exprs],
                order_by=(
                    [
                        ast.OrderExpr(expr=self._unwrap_hidden_alias(order.expr), order=order.order)
                        for order in node.order_by
                    ]
                    if node.order_by
                    else None
                ),
            ),
        )
        node.select.append(ast.Alias(alias=helper_name, expr=row_number))
        node.limit_by = None
        predicate: ast.Expr = ast.CompareOperation(
            left=ast.Field(chain=[helper_name]),
            right=ast.Constant(value=offset + n),
            op=ast.CompareOperationOp.LtEq,
        )
        if offset:
            predicate = ast.And(
                exprs=[
                    ast.CompareOperation(
                        left=ast.Field(chain=[helper_name]),
                        right=ast.Constant(value=offset),
                        op=ast.CompareOperationOp.Gt,
                    ),
                    predicate,
                ]
            )
        return self._wrap(node, predicate, helper_name=helper_name)

    def _wrap(self, node: ast.SelectQuery, predicate: ast.Expr, helper_name: str | None = None) -> ast.SelectQuery:
        source_alias = f"__hogql_trino_source_{self.wrapper_index}"
        self.wrapper_index += 1
        output_names = self._output_names(node)
        visible_select = node.select[:-1] if helper_name is not None else node.select
        if len(output_names) != len(visible_select):
            raise TrinoLoweringError(
                "TRINO_WRAPPER_OUTPUT_NAME_UNSAFE", "wrapper query without stable output names", node
            )
        node.select = [
            expr if isinstance(expr, ast.Alias) and expr.alias == name else ast.Alias(alias=name, expr=expr)
            for expr, name in zip(visible_select, output_names, strict=True)
        ] + ([node.select[-1]] if helper_name is not None else [])

        outer_order = self._outer_order_by(node.order_by, output_names, source_alias)
        outer_limit = node.limit
        outer_offset = node.offset
        outer_limit_with_ties = node.limit_with_ties
        outer_limit_percent = node.limit_percent
        outer_ctes = node.ctes
        node.ctes = None
        node.order_by = None
        node.limit = None
        node.offset = None
        node.limit_with_ties = False
        node.limit_percent = False

        return ast.SelectQuery(
            ctes=outer_ctes,
            select=[ast.Field(chain=[source_alias, name]) for name in output_names],
            select_from=ast.JoinExpr(table=node, alias=source_alias),
            where=self._qualify_wrapper_fields(
                predicate,
                source_alias,
                {*output_names, *({helper_name} if helper_name else set())},
            ),
            order_by=outer_order,
            limit=outer_limit,
            offset=outer_offset,
            limit_with_ties=outer_limit_with_ties,
            limit_percent=outer_limit_percent,
            view_name=node.view_name,
        )

    def _output_names(self, node: ast.SelectQuery) -> list[str]:
        if not isinstance(node.type, ast.SelectQueryType):
            raise TrinoLoweringError(
                "TRINO_WRAPPER_OUTPUT_TYPE_UNRESOLVED", "wrapper query with unresolved output types", node
            )
        return list(node.type.columns)

    def _outer_order_by(
        self,
        order_by: list[ast.OrderExpr] | None,
        output_names: list[str],
        source_alias: str,
    ) -> list[ast.OrderExpr] | None:
        if order_by is None:
            return None
        output_set = set(output_names)
        outer: list[ast.OrderExpr] = []
        for order in order_by:
            if order.with_fill is not None:
                raise TrinoLoweringError("TRINO_ORDER_BY_WITH_FILL_UNSUPPORTED", "ORDER BY WITH FILL", order.expr)
            if isinstance(order.expr, ast.PositionalRef):
                expr: ast.Expr = ast.PositionalRef(index=order.expr.index)
            else:
                unwrapped = self._unwrap_hidden_alias(order.expr)
                if not isinstance(unwrapped, ast.Field) or not isinstance(unwrapped.chain[-1], str):
                    raise TrinoLoweringError(
                        "TRINO_WRAPPER_ORDER_NOT_PROJECTED",
                        "LIMIT BY or QUALIFY ORDER BY expression not present in SELECT",
                        order.expr,
                    )
                name = unwrapped.chain[-1]
                if name not in output_set:
                    raise TrinoLoweringError(
                        "TRINO_WRAPPER_ORDER_NOT_PROJECTED",
                        "LIMIT BY or QUALIFY ORDER BY expression not present in SELECT",
                        order.expr,
                    )
                expr = ast.Field(chain=[source_alias, name])
            outer.append(ast.OrderExpr(expr=expr, order=order.order))
        return outer

    def _unwrap_hidden_alias(self, expr: ast.Expr) -> ast.Expr:
        while isinstance(expr, ast.Alias) and expr.hidden:
            expr = expr.expr
        return expr

    def _qualify_wrapper_fields(self, node: ast.Expr, source_alias: str, output_names: set[str]) -> ast.Expr:
        class FieldQualifier(CloningVisitor):
            def visit_field(self, field: ast.Field) -> ast.Field:
                if not field.chain or not isinstance(field.chain[-1], str) or field.chain[-1] not in output_names:
                    raise TrinoLoweringError(
                        "TRINO_WRAPPER_PREDICATE_NOT_PROJECTED",
                        "wrapper predicate that does not reference a projected output alias",
                        field,
                    )
                return ast.Field(chain=[source_alias, field.chain[-1]], start=field.start, end=field.end)

        return FieldQualifier(clear_types=False).visit(node)

    def _non_negative_integer(self, node: ast.Expr | None, label: str, default: int | None = None) -> int:
        if node is None and default is not None:
            return default
        if not isinstance(node, ast.Constant) or isinstance(node.value, bool) or not isinstance(node.value, int):
            raise TrinoLoweringError("TRINO_LIMIT_BY_NON_CONSTANT_LIMIT", f"non-constant {label}", node)
        if node.value < 0:
            raise TrinoLoweringError("TRINO_LIMIT_BY_NEGATIVE_LIMIT", f"negative {label}", node)
        return node.value


def lower_trino_query_wrappers(node: ast.AST) -> ast.AST:
    return TrinoQueryWrapperLowerer().visit(node)
