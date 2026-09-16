from typing import Literal

from posthog.hogql import ast
from posthog.hogql.transforms.trino.any_join import TrinoAnyJoinLowerer
from posthog.hogql.transforms.trino.errors import TrinoLoweringError
from posthog.hogql.visitor import CloningVisitor, clone_expr

from posthog.dataclasses import frozen

_SUPPORTED_ASOF_JOIN_TYPES = {"ASOF INNER JOIN", "LEFT ASOF JOIN", "ASOF LEFT JOIN"}
_ASCENDING_OPS = {ast.CompareOperationOp.Lt, ast.CompareOperationOp.LtEq}
_NEAREST_OPS = _ASCENDING_OPS | {ast.CompareOperationOp.Gt, ast.CompareOperationOp.GtEq}


@frozen
class _AsofJoin:
    left: ast.JoinExpr
    right: ast.JoinExpr
    constraint: ast.Expr
    left_alias: str
    right_alias: str
    left_columns: list[str]
    right_columns: list[str]
    left_type: ast.TableOrSelectType
    right_type: ast.TableOrSelectType


@frozen
class _NearestMatch:
    expr: ast.Expr
    direction: Literal["ASC", "DESC"]


@frozen
class _LoweredAsof:
    prefix: str
    matched: ast.SelectQuery
    by_left: dict[str, str]
    by_right: dict[str, str]


class TrinoAsOfJoinLowerer(CloningVisitor):
    def __init__(self) -> None:
        super().__init__(clear_types=False)
        self.index = 0
        self.bindings = TrinoAnyJoinLowerer()

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

    def _asof_join(self, query: ast.SelectQuery) -> _AsofJoin | None:
        left = query.select_from
        right = left.next_join if left is not None else None
        if right is None or "ASOF" not in (right.join_type or "").split():
            return None
        if right.next_join is not None or right.join_type not in _SUPPORTED_ASOF_JOIN_TYPES:
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
        return _AsofJoin(
            left=left,
            right=right,
            constraint=right.constraint.expr,
            left_alias=left_alias,
            right_alias=right_alias,
            left_columns=left_columns,
            right_columns=right_columns,
            left_type=left_type,
            right_type=right_type,
        )

    def _nearest_match(self, term: ast.CompareOperation, join: _AsofJoin) -> _NearestMatch:
        if term.op not in _NEAREST_OPS:
            raise TrinoLoweringError("TRINO_ASOF_CONSTRAINT_UNSUPPORTED", "ASOF without exactly one inequality", term)
        right_on_right = self.bindings._right_field_name(term.right, join.right_alias, join.right_type) is not None
        right_on_left = self.bindings._right_field_name(term.left, join.right_alias, join.right_type) is not None
        if right_on_left == right_on_right:
            raise TrinoLoweringError(
                "TRINO_ASOF_CONSTRAINT_UNSUPPORTED", "ASOF inequality without one right field", term
            )
        nearest = term.right if right_on_right else term.left
        left_time = term.left if right_on_right else term.right
        if self.bindings._right_field_name(left_time, join.left_alias, join.left_type) is None:
            raise TrinoLoweringError(
                "TRINO_ASOF_CONSTRAINT_UNSUPPORTED", "ASOF inequality without one left field", term
            )
        ascending = term.op in _ASCENDING_OPS
        return _NearestMatch(expr=nearest, direction="ASC" if ascending == right_on_right else "DESC")

    def _analyze_constraint(self, join: _AsofJoin) -> _NearestMatch:
        terms = join.constraint.exprs if isinstance(join.constraint, ast.And) else [join.constraint]
        equality_terms: list[ast.Expr] = []
        nearest: _NearestMatch | None = None
        for term in terms:
            if not isinstance(term, ast.CompareOperation):
                raise TrinoLoweringError("TRINO_ASOF_CONSTRAINT_UNSUPPORTED", "ASOF with a non-comparison term", term)
            if term.op == ast.CompareOperationOp.Eq:
                equality_terms.append(term)
                continue
            if nearest is not None:
                raise TrinoLoweringError(
                    "TRINO_ASOF_CONSTRAINT_UNSUPPORTED", "ASOF without exactly one inequality", term
                )
            nearest = self._nearest_match(term, join)
        if nearest is None or not equality_terms:
            raise TrinoLoweringError(
                "TRINO_ASOF_CONSTRAINT_UNSUPPORTED", "ASOF needs equality keys and one inequality", join.right
            )
        self.bindings._right_key_expressions(ast.And(exprs=equality_terms), join.right_alias, join.right_type)
        return nearest

    def _lower_join(self, join: _AsofJoin, nearest: _NearestMatch) -> _LoweredAsof:
        prefix = f"__hogql_asof_{self.index}"
        self.index += 1
        while prefix in {join.left_alias, join.right_alias}:
            prefix += "_"
        row_name = f"{prefix}_left_row"
        while row_name in join.left_columns:
            row_name += "_"
        rank_name = f"{prefix}_rank"
        mappings = [
            (alias, name, f"{side}_{index}")
            for side, alias, columns in [
                ("left", join.left_alias, join.left_columns),
                ("right", join.right_alias, join.right_columns),
            ]
            for index, name in enumerate(columns)
        ]
        source = clone_expr(join.left, clear_types=False)
        source.next_join = None
        numbered = ast.SelectQuery(
            select=[ast.Field(chain=[join.left_alias, name]) for name in join.left_columns]
            + [
                ast.Alias(
                    alias=row_name, expr=ast.WindowFunction(name="row_number", exprs=[], over_expr=ast.WindowExpr())
                )
            ],
            select_from=source,
        )
        join.right.join_type = "LEFT JOIN" if "LEFT" in (join.right.join_type or "").split() else "INNER JOIN"
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
                        partition_by=[ast.Field(chain=[join.left_alias, row_name])],
                        order_by=[ast.OrderExpr(expr=nearest.expr, order=nearest.direction)],
                    ),
                ),
            )
        )
        ranked = ast.SelectQuery(
            select=projections,
            select_from=ast.JoinExpr(table=numbered, alias=join.left_alias, next_join=join.right),
        )
        matched = ast.SelectQuery(
            select=[ast.Field(chain=[prefix, output]) for _, _, output in mappings],
            select_from=ast.JoinExpr(table=ranked, alias=prefix),
            where=ast.CompareOperation(
                left=ast.Field(chain=[prefix, rank_name]), op=ast.CompareOperationOp.Eq, right=ast.Constant(value=1)
            ),
        )
        return _LoweredAsof(
            prefix=prefix,
            matched=matched,
            by_left={name: output for alias, name, output in mappings if alias == join.left_alias},
            by_right={name: output for alias, name, output in mappings if alias == join.right_alias},
        )

    def _rewrite_outputs(self, query: ast.SelectQuery, join: _AsofJoin, lowered: _LoweredAsof) -> None:
        bindings = self.bindings

        class OutputRewriter(CloningVisitor):
            def visit_select_query(self, node: ast.SelectQuery) -> ast.SelectQuery:
                raise TrinoLoweringError(
                    "TRINO_ASOF_SUBQUERY_UNSUPPORTED", "ASOF with a subquery outside its inputs", node
                )

            def visit_field(self, field: ast.Field) -> ast.Field:
                name = bindings._right_field_name(field, join.left_alias, join.left_type)
                if name is not None and name in lowered.by_left:
                    return ast.Field(chain=[lowered.prefix, lowered.by_left[name]])
                name = bindings._right_field_name(field, join.right_alias, join.right_type)
                if name is not None and name in lowered.by_right:
                    return ast.Field(chain=[lowered.prefix, lowered.by_right[name]])
                if isinstance(field.type, ast.FieldAliasType) and len(field.chain) == 1:
                    return field
                raise TrinoLoweringError(
                    "TRINO_ASOF_OUTPUT_UNSUPPORTED", "ASOF output without a direct input field", field
                )

        rewriter = OutputRewriter(clear_types=False)
        query.select = [rewriter.visit(expr) for expr in query.select]
        for clause in ["where", "prewhere", "having", "qualify", "limit_by"]:
            expression = getattr(query, clause)
            if expression is not None:
                setattr(query, clause, rewriter.visit(expression))
        query.group_by = [rewriter.visit(expr) for expr in query.group_by] if query.group_by is not None else None
        query.order_by = [rewriter.visit(expr) for expr in query.order_by] if query.order_by is not None else None
        query.array_join_list = (
            [rewriter.visit(expr) for expr in query.array_join_list] if query.array_join_list else None
        )
        query.window_exprs = (
            {name: rewriter.visit(expr) for name, expr in query.window_exprs.items()} if query.window_exprs else None
        )
        query.select_from = ast.JoinExpr(table=lowered.matched, alias=lowered.prefix)

    def visit_select_query(self, node: ast.SelectQuery) -> ast.SelectQuery:
        query = super().visit_select_query(node)
        join = self._asof_join(query)
        if join is None:
            return query
        nearest = self._analyze_constraint(join)
        self._rewrite_outputs(query, join, self._lower_join(join, nearest))
        return query
