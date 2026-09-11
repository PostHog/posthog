from posthog.hogql import ast
from posthog.hogql.functions.mapping import find_hogql_aggregation
from posthog.hogql.transforms.trino.errors import TrinoLoweringError
from posthog.hogql.transforms.trino.expressions import constant_integer, expression_key, positional_index
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
        if lowered.limit_by is not None:
            finder = _WindowFunctionFinder()
            for expr in lowered.limit_by.exprs:
                finder.visit(self._input_expression(expr, lowered.select))
            for order in lowered.order_by or []:
                finder.visit(self._input_expression(order.expr, lowered.select))
            if lowered.qualify is not None or finder.found:
                lowered = self._stage_limit_by(lowered)
        if lowered.qualify is not None:
            lowered = self._lower_qualify(lowered)
        if lowered.limit_by is not None:
            lowered = self._lower_limit_by(lowered)
        if lowered.limit_percent:
            lowered = self._lower_limit_percent(lowered)
        return lowered

    def _lower_limit_percent(self, node: ast.SelectQuery) -> ast.SelectQuery:
        if (
            not isinstance(node.limit, ast.Constant)
            or isinstance(node.limit.value, bool)
            or not isinstance(node.limit.value, (int, float))
            or not 0 <= node.limit.value <= 100
            or node.limit_with_ties
        ):
            raise TrinoLoweringError(
                "TRINO_LIMIT_PERCENT_UNSUPPORTED", "LIMIT PERCENT without a constant percentage, or with ties", node
            )
        percentage = node.limit.value / 100
        offset = self._non_negative_integer(node.offset, "percentage offset", default=0)
        node.limit = None
        node.offset = None
        node.limit_percent = False
        staged = self._wrap(node, ast.Constant(value=True))
        row_number = ast.WindowFunction(name="row_number", exprs=[], over_expr=ast.WindowExpr(order_by=staged.order_by))
        count = ast.WindowFunction(name="count", exprs=[], over_expr=ast.WindowExpr())
        upper_bound = ast.ArithmeticOperation(
            left=ast.Constant(value=offset),
            op=ast.ArithmeticOperationOp.Add,
            right=ast.Call(
                name="ceil",
                args=[
                    ast.ArithmeticOperation(
                        left=count, op=ast.ArithmeticOperationOp.Mult, right=ast.Constant(value=percentage)
                    )
                ],
            ),
        )
        predicate: ast.Expr = ast.CompareOperation(left=row_number, op=ast.CompareOperationOp.LtEq, right=upper_bound)
        if offset:
            predicate = ast.And(
                exprs=[
                    ast.CompareOperation(
                        left=row_number, op=ast.CompareOperationOp.Gt, right=ast.Constant(value=offset)
                    ),
                    predicate,
                ]
            )
        helper_name = self._helper_name(staged, f"__hogql_percent_{self.wrapper_index}")
        staged.select.append(ast.Alias(alias=helper_name, expr=predicate))
        return self._wrap(staged, ast.Field(chain=[helper_name]), helper_name=helper_name)

    def _stage_limit_by(self, node: ast.SelectQuery) -> ast.SelectQuery:
        assert node.limit_by is not None
        if any(order.with_fill is not None for order in node.order_by or []):
            raise TrinoLoweringError("TRINO_WITH_FILL_UNSUPPORTED", "WITH FILL in a staged LIMIT BY query", node)
        output_names = self._output_names(node)
        visible_count = len(output_names)
        limit_by = node.limit_by
        node.limit_by = None
        columns = dict(node.type.columns) if node.type is not None else {}
        node.type = ast.SelectQueryType(columns=columns)

        def project(expr: ast.Expr) -> str:
            expression = self._input_expression(expr, node.select[:visible_count])
            key = expression_key(expression)
            for name, projection in zip(columns, node.select, strict=True):
                if expression_key(self._input_expression(projection, node.select)) == key:
                    return name
            if node.distinct:
                raise TrinoLoweringError(
                    "TRINO_LIMIT_BY_DISTINCT_PARTITION_NOT_PROJECTED",
                    "DISTINCT LIMIT BY stage with an unprojected expression",
                    expr,
                )
            name = self._helper_name(node, f"__hogql_stage_{len(columns)}")
            node.select.append(ast.Alias(alias=name, expr=expression))
            columns[name] = expression.type or ast.UnknownType()
            return name

        partition_names = [project(expr) for expr in limit_by.exprs]
        ordering = [(project(order.expr), order.order) for order in node.order_by or []]
        node.order_by = None
        staged = self._lower_qualify(node) if node.qualify is not None else self._wrap(node, ast.Constant(value=True))
        assert staged.select_from is not None
        source_alias = staged.select_from.alias
        assert source_alias is not None
        staged.limit_by = ast.LimitByExpr(
            n=limit_by.n,
            offset_value=limit_by.offset_value,
            exprs=[ast.Field(chain=[source_alias, name]) for name in partition_names],
        )
        staged.order_by = [
            ast.OrderExpr(expr=ast.Field(chain=[source_alias, name]), order=order) for name, order in ordering
        ] or None
        result = self._lower_limit_by(staged)
        result.select = result.select[:visible_count]
        result.type = ast.SelectQueryType(columns={name: columns[name] for name in output_names})
        return result

    def _lower_qualify(self, node: ast.SelectQuery) -> ast.SelectQuery:
        assert node.qualify is not None
        finder = _WindowFunctionFinder()
        finder.visit(node.qualify)
        predicate = node.qualify
        node.qualify = None
        output_names = self._output_names(node)
        projection_keys = [expression_key(self._input_expression(expr, node.select)) for expr in node.select]

        class ProjectedPredicate(CloningVisitor):
            def visit_field(self, field: ast.Field) -> ast.Field:
                if (
                    isinstance(field.type, ast.FieldAliasType)
                    and len(field.chain) == 1
                    and field.chain[0] in output_names
                ):
                    return ast.Field(chain=list(field.chain))
                key = expression_key(field)
                if key in projection_keys:
                    return ast.Field(chain=[output_names[projection_keys.index(key)]])
                raise TrinoLoweringError("TRINO_QUALIFY_HELPER_REQUIRED", "QUALIFY with an unprojected field", field)

        projected_predicate = predicate
        try:
            projected_predicate = ProjectedPredicate(clear_types=False).visit(predicate)
            needs_helper = finder.found
        except TrinoLoweringError:
            needs_helper = True
        if not needs_helper:
            return self._wrap(node, projected_predicate)
        if node.distinct:
            self._outer_order_by(node, output_names, "")
        helper_name = self._helper_name(node, f"__hogql_qualify_{self.wrapper_index}")
        node.select.append(ast.Alias(alias=helper_name, expr=predicate))
        distinct = node.distinct
        node.distinct = False
        result = self._wrap(node, ast.Field(chain=[helper_name]), helper_name=helper_name)
        result.distinct = distinct
        return result

    def _lower_limit_by(self, node: ast.SelectQuery) -> ast.SelectQuery:
        assert node.limit_by is not None
        if node.distinct:
            node = self._wrap_distinct_limit_by_input(node)
        limit_by = node.limit_by
        assert limit_by is not None
        n = self._non_negative_integer(limit_by.n, "LIMIT BY count")
        offset = self._non_negative_integer(limit_by.offset_value, "LIMIT BY offset", default=0)
        helper_name = self._helper_name(node, f"__hogql_limit_by_row_{self.wrapper_index}")
        row_number = ast.WindowFunction(
            name="row_number",
            exprs=[],
            over_expr=ast.WindowExpr(
                partition_by=[self._input_expression(expr, node.select) for expr in limit_by.exprs],
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

    def _wrap_distinct_limit_by_input(self, node: ast.SelectQuery) -> ast.SelectQuery:
        assert node.limit_by is not None
        output_names = self._output_names(node)
        selected_expressions = [self._input_expression(expr, node.select) for expr in node.select]
        projection_keys = [expression_key(expr) for expr in selected_expressions]
        source_alias = f"__hogql_trino_distinct_{self.wrapper_index}"
        self.wrapper_index += 1

        partition_by: list[ast.Expr] = []
        for expr in node.limit_by.exprs:
            key = expression_key(self._input_expression(expr, node.select))
            if key not in projection_keys:
                raise TrinoLoweringError(
                    "TRINO_LIMIT_BY_DISTINCT_PARTITION_NOT_PROJECTED",
                    "DISTINCT LIMIT BY expression not present in SELECT",
                    expr,
                )
            partition_by.append(ast.Field(chain=[source_alias, output_names[projection_keys.index(key)]]))

        node.select = [
            expr
            if isinstance(expr, ast.Alias) and expr.alias == name and not expr.hidden
            else ast.Alias(alias=name, expr=expr)
            for expr, name in zip(node.select, output_names, strict=True)
        ]
        outer_order = self._outer_order_by(node, output_names, source_alias)
        outer_ctes = node.ctes
        outer_limit = node.limit
        outer_offset = node.offset
        outer_limit_with_ties = node.limit_with_ties
        outer_limit_percent = node.limit_percent
        limit_by = node.limit_by
        node.ctes = None
        node.order_by = None
        node.limit = None
        node.offset = None
        node.limit_by = None
        node.limit_with_ties = False
        node.limit_percent = False

        return ast.SelectQuery(
            type=node.type,
            ctes=outer_ctes,
            select=[ast.Field(chain=[source_alias, name]) for name in output_names],
            select_from=ast.JoinExpr(table=node, alias=source_alias),
            order_by=outer_order,
            limit=outer_limit,
            offset=outer_offset,
            limit_by=ast.LimitByExpr(n=limit_by.n, exprs=partition_by, offset_value=limit_by.offset_value),
            limit_with_ties=outer_limit_with_ties,
            limit_percent=outer_limit_percent,
            view_name=node.view_name,
        )

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
            type=ast.SelectQueryType(columns=dict(node.type.columns)) if node.type is not None else None,
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
        value = constant_integer(node)
        if value is None:
            raise TrinoLoweringError("TRINO_LIMIT_BY_NON_CONSTANT_LIMIT", f"non-constant {label}", node)
        if value < 0:
            raise TrinoLoweringError("TRINO_LIMIT_BY_NEGATIVE_LIMIT", f"negative {label}", node)
        return value


def lower_trino_query_wrappers(node: ast.AST) -> ast.AST:
    return TrinoQueryWrapperLowerer().visit(node)
