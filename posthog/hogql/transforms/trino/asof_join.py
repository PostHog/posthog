from typing import Literal

from posthog.hogql import ast
from posthog.hogql.transforms.trino.any_join import TrinoAnyJoinLowerer
from posthog.hogql.transforms.trino.errors import TrinoLoweringError
from posthog.hogql.visitor import CloningVisitor, clone_expr


class TrinoAsOfJoinLowerer(CloningVisitor):
    def __init__(self) -> None:
        super().__init__(clear_types=False)
        self.index = 0

    def _columns(self, join: ast.JoinExpr) -> list[str]:
        if join.column_aliases:
            raise TrinoLoweringError("TRINO_ASOF_COLUMN_ALIASES_UNSUPPORTED", "ASOF column aliases", join)
        relation = join.type
        while isinstance(relation, (ast.TableAliasType, ast.CTETableAliasType)):
            relation = relation.cte_table_type if isinstance(relation, ast.CTETableAliasType) else relation.table_type
        if isinstance(relation, ast.SelectQueryAliasType):
            relation = relation.select_query_type
        if isinstance(relation, ast.CTETableType):
            relation = relation.select_query_type
        if isinstance(relation, (ast.SelectQueryType, ast.SelectSetQueryType)):
            return list(relation.columns)
        if isinstance(relation, ast.TableType) and getattr(relation.table, "has_complete_columns", False):
            return list(relation.table.get_asterisk())
        raise TrinoLoweringError("TRINO_ASOF_COMPLETE_TABLE_REQUIRED", "ASOF without complete input columns", join)

    def _alias(self, join: ast.JoinExpr) -> str:
        if join.alias is not None:
            return join.alias
        if isinstance(join.table, ast.Field) and isinstance(join.table.chain[-1], str):
            return join.table.chain[-1]
        raise TrinoLoweringError("TRINO_ASOF_ALIAS_REQUIRED", "ASOF without an input alias", join)

    def visit_select_query(self, node: ast.SelectQuery) -> ast.SelectQuery:
        lowered = super().visit_select_query(node)
        left = lowered.select_from
        right = left.next_join if left is not None else None
        if right is None or "ASOF" not in (right.join_type or "").split():
            return lowered
        if right.next_join is not None or right.join_type not in {
            "ASOF INNER JOIN",
            "LEFT ASOF JOIN",
            "ASOF LEFT JOIN",
        }:
            raise TrinoLoweringError(
                "TRINO_ASOF_JOIN_SHAPE_UNSUPPORTED", "ASOF outside a two-table INNER or LEFT join", right
            )
        assert left is not None
        if right.constraint is None or right.constraint.constraint_type != "ON":
            raise TrinoLoweringError("TRINO_ASOF_ON_REQUIRED", "ASOF without an ON constraint", right)
        left_alias, right_alias = self._alias(left), self._alias(right)
        left_columns, right_columns = self._columns(left), self._columns(right)
        left_type, right_type = left.type, right.type
        if left_type is None or right_type is None:
            raise TrinoLoweringError("TRINO_ASOF_COMPLETE_TABLE_REQUIRED", "ASOF without input types", right)
        bindings = TrinoAnyJoinLowerer()
        predicate = right.constraint.expr
        terms = predicate.exprs if isinstance(predicate, ast.And) else [predicate]
        equality_terms: list[ast.Expr] = []
        nearest: ast.Expr | None = None
        direction: Literal["ASC", "DESC"] = "DESC"
        for term in terms:
            if not isinstance(term, ast.CompareOperation):
                raise TrinoLoweringError("TRINO_ASOF_CONSTRAINT_UNSUPPORTED", "ASOF with a non-comparison term", term)
            if term.op == ast.CompareOperationOp.Eq:
                equality_terms.append(term)
                continue
            if nearest is not None or term.op not in {
                ast.CompareOperationOp.Lt,
                ast.CompareOperationOp.LtEq,
                ast.CompareOperationOp.Gt,
                ast.CompareOperationOp.GtEq,
            }:
                raise TrinoLoweringError(
                    "TRINO_ASOF_CONSTRAINT_UNSUPPORTED", "ASOF without exactly one inequality", term
                )
            right_on_right = bindings._right_field_name(term.right, right_alias, right_type) is not None
            right_on_left = bindings._right_field_name(term.left, right_alias, right_type) is not None
            if right_on_left == right_on_right:
                raise TrinoLoweringError(
                    "TRINO_ASOF_CONSTRAINT_UNSUPPORTED", "ASOF inequality without one right field", term
                )
            nearest = term.right if right_on_right else term.left
            left_time = term.left if right_on_right else term.right
            if bindings._right_field_name(left_time, left_alias, left_type) is None:
                raise TrinoLoweringError(
                    "TRINO_ASOF_CONSTRAINT_UNSUPPORTED", "ASOF inequality without one left field", term
                )
            ascending = term.op in {ast.CompareOperationOp.Lt, ast.CompareOperationOp.LtEq}
            direction = "ASC" if ascending == right_on_right else "DESC"
        if nearest is None or not equality_terms:
            raise TrinoLoweringError(
                "TRINO_ASOF_CONSTRAINT_UNSUPPORTED", "ASOF needs equality keys and one inequality", right
            )
        bindings._right_key_expressions(ast.And(exprs=equality_terms), right_alias, right_type)
        prefix = f"__hogql_asof_{self.index}"
        self.index += 1
        while prefix in {left_alias, right_alias}:
            prefix += "_"
        row_name = f"{prefix}_left_row"
        while row_name in left_columns:
            row_name += "_"
        rank_name = f"{prefix}_rank"
        mappings = [
            (alias, name, f"{side}_{index}")
            for side, alias, columns in [("left", left_alias, left_columns), ("right", right_alias, right_columns)]
            for index, name in enumerate(columns)
        ]
        source = clone_expr(left, clear_types=False)
        source.next_join = None
        numbered = ast.SelectQuery(
            select=[ast.Field(chain=[left_alias, name]) for name in left_columns]
            + [
                ast.Alias(
                    alias=row_name, expr=ast.WindowFunction(name="row_number", exprs=[], over_expr=ast.WindowExpr())
                )
            ],
            select_from=source,
        )
        right.join_type = "LEFT JOIN" if "LEFT" in (right.join_type or "").split() else "INNER JOIN"
        projections: list[ast.Expr] = [
            ast.Alias(alias=output, expr=ast.Field(chain=[alias, name])) for alias, name, output in mappings
        ]
        projections.append(
            ast.Alias(
                alias=rank_name,
                expr=ast.WindowFunction(
                    name="row_number",
                    exprs=[],
                    over_expr=ast.WindowExpr(
                        partition_by=[ast.Field(chain=[left_alias, row_name])],
                        order_by=[ast.OrderExpr(expr=nearest, order=direction)],
                    ),
                ),
            )
        )
        ranked = ast.SelectQuery(
            select=projections,
            select_from=ast.JoinExpr(table=numbered, alias=left_alias, next_join=right),
        )
        matched = ast.SelectQuery(
            select=[ast.Field(chain=[prefix, output]) for _, _, output in mappings],
            select_from=ast.JoinExpr(table=ranked, alias=prefix),
            where=ast.CompareOperation(
                left=ast.Field(chain=[prefix, rank_name]), op=ast.CompareOperationOp.Eq, right=ast.Constant(value=1)
            ),
        )
        by_left = {name: output for alias, name, output in mappings if alias == left_alias}
        by_right = {name: output for alias, name, output in mappings if alias == right_alias}

        class OutputRewriter(CloningVisitor):
            def visit_select_query(self, query: ast.SelectQuery) -> ast.SelectQuery:
                raise TrinoLoweringError(
                    "TRINO_ASOF_SUBQUERY_UNSUPPORTED", "ASOF with a subquery outside its inputs", query
                )

            def visit_field(self, field: ast.Field) -> ast.Field:
                name = bindings._right_field_name(field, left_alias, left_type)
                if name is not None and name in by_left:
                    return ast.Field(chain=[prefix, by_left[name]])
                name = bindings._right_field_name(field, right_alias, right_type)
                if name is not None and name in by_right:
                    return ast.Field(chain=[prefix, by_right[name]])
                if isinstance(field.type, ast.FieldAliasType) and len(field.chain) == 1:
                    return field
                raise TrinoLoweringError(
                    "TRINO_ASOF_OUTPUT_UNSUPPORTED", "ASOF output without a direct input field", field
                )

        rewriter = OutputRewriter(clear_types=False)
        lowered.select = [rewriter.visit(expr) for expr in lowered.select]
        for clause in ["where", "prewhere", "having", "qualify", "limit_by"]:
            expression = getattr(lowered, clause)
            if expression is not None:
                setattr(lowered, clause, rewriter.visit(expression))
        lowered.group_by = [rewriter.visit(expr) for expr in lowered.group_by] if lowered.group_by is not None else None
        lowered.order_by = [rewriter.visit(expr) for expr in lowered.order_by] if lowered.order_by is not None else None
        lowered.array_join_list = (
            [rewriter.visit(expr) for expr in lowered.array_join_list] if lowered.array_join_list else None
        )
        lowered.window_exprs = (
            {name: rewriter.visit(expr) for name, expr in lowered.window_exprs.items()}
            if lowered.window_exprs
            else None
        )
        lowered.select_from = ast.JoinExpr(table=matched, alias=prefix)
        return lowered
