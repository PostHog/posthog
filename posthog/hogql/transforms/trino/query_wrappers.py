from posthog.hogql import ast
from posthog.hogql.functions.mapping import find_hogql_aggregation
from posthog.hogql.transforms.trino.errors import TrinoLoweringError
from posthog.hogql.transforms.trino.expressions import expression_key, positional_index
from posthog.hogql.visitor import CloningVisitor, TraversingVisitor


class _WindowFunctionFinder(TraversingVisitor):
    found: bool = False

    def visit_window_function(self, node: ast.WindowFunction) -> None:
        self.found = True
        super().visit_window_function(node)


class _AggregateFunctionFinder(TraversingVisitor):
    found: bool = False

    def visit_select_query(self, node: ast.SelectQuery) -> None:
        pass

    def visit_call(self, node: ast.Call) -> None:
        if find_hogql_aggregation(node.name):
            self.found = True
        else:
            super().visit_call(node)


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
        helper_name = self._helper_name(node, f"__hogql_limit_by_row_{self.wrapper_index}")
        row_number = ast.WindowFunction(
            name="row_number",
            exprs=[],
            over_expr=ast.WindowExpr(
                partition_by=[self._input_expression(expr, node.select) for expr in node.limit_by.exprs],
                order_by=(
                    [
                        ast.OrderExpr(expr=self._input_expression(order.expr, node.select), order=order.order)
                        for order in node.order_by
                    ]
                    if node.order_by
                    else None
                ),
            ),
        )
        finder = _WindowFunctionFinder()
        finder.visit(row_number.over_expr)
        if finder.found:
            raise TrinoLoweringError(
                "TRINO_LIMIT_BY_WINDOW_UNSUPPORTED",
                "LIMIT BY partition or ordering containing a window expression",
                node,
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
            expr
            if isinstance(expr, ast.Alias) and expr.alias == name and not expr.hidden
            else ast.Alias(alias=name, expr=expr)
            for expr, name in zip(visible_select, output_names, strict=True)
        ] + ([node.select[-1]] if helper_name is not None else [])

        outer_order = self._outer_order_by(node, output_names, source_alias)
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
        node: ast.SelectQuery,
        output_names: list[str],
        source_alias: str,
    ) -> list[ast.OrderExpr] | None:
        if node.order_by is None:
            return None
        projections = [expression_key(expr) for expr in node.select[: len(output_names)]]
        outer: list[ast.OrderExpr] = []
        for order in node.order_by:
            if order.with_fill is not None:
                raise TrinoLoweringError("TRINO_ORDER_BY_WITH_FILL_UNSUPPORTED", "ORDER BY WITH FILL", order.expr)
            position = positional_index(order.expr)
            if position is not None:
                if not 1 <= position <= len(output_names):
                    raise TrinoLoweringError(
                        "TRINO_POSITIONAL_REFERENCE_INVALID", "ORDER BY ordinal out of range", order.expr
                    )
                expr: ast.Expr = ast.PositionalRef(index=position)
            else:
                unwrapped = self._input_expression(order.expr, node.select[: len(output_names)])
                key = expression_key(unwrapped)
                if key in projections:
                    name = output_names[projections.index(key)]
                else:
                    finder = _AggregateFunctionFinder()
                    finder.visit(unwrapped)
                    if node.distinct or node.group_by is not None or finder.found:
                        raise TrinoLoweringError(
                            "TRINO_WRAPPER_ORDER_NOT_PROJECTED",
                            "DISTINCT or grouped wrapper, or aggregate ORDER BY expression not present in SELECT",
                            order.expr,
                        )
                    name = self._helper_name(node, f"__hogql_order_{len(outer)}")
                    node.select.append(ast.Alias(alias=name, expr=unwrapped))
                expr = ast.Field(chain=[source_alias, name])
            outer.append(ast.OrderExpr(expr=expr, order=order.order))
        return outer

    def _input_expression(self, expr: ast.Expr, select: list[ast.Expr]) -> ast.Expr:
        expr = self._unwrap_hidden_alias(expr)
        position = positional_index(expr)
        if position is not None:
            if not 1 <= position <= len(select):
                raise TrinoLoweringError("TRINO_POSITIONAL_REFERENCE_INVALID", "wrapper ordinal out of range", expr)
            expr = select[position - 1]
        elif isinstance(expr, ast.Field) and isinstance(expr.type, ast.FieldAliasType) and len(expr.chain) == 1:
            alias_name = expr.chain[0]
            expr = next(
                (
                    projection
                    for projection in select
                    if isinstance(projection, ast.Alias) and projection.alias == alias_name
                ),
                expr,
            )
        while isinstance(expr, ast.Alias):
            expr = expr.expr
        return expr

    def _helper_name(self, node: ast.SelectQuery, prefix: str) -> str:
        names = set(self._output_names(node))

        class NameFinder(TraversingVisitor):
            def visit_alias(self, alias: ast.Alias) -> None:
                names.add(alias.alias)
                super().visit_alias(alias)

            def visit_field(self, field: ast.Field) -> None:
                names.update(part for part in field.chain if isinstance(part, str))

        NameFinder().visit(node)
        name = prefix
        suffix = 1
        while name in names:
            name = f"{prefix}_{suffix}"
            suffix += 1
        return name

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
