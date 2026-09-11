from posthog.hogql import ast
from posthog.hogql.database.models import DatabaseField
from posthog.hogql.transforms.trino.errors import TrinoLoweringError
from posthog.hogql.visitor import CloningVisitor

_SUPPORTED_ANY_JOIN_TYPES = {
    "ANY INNER JOIN": "INNER JOIN",
    "LEFT ANY JOIN": "LEFT JOIN",
}


class TrinoAnyJoinLowerer(CloningVisitor):
    def __init__(self) -> None:
        super().__init__(clear_types=False)
        self.join_index = 0

    def visit_join_expr(self, node: ast.JoinExpr) -> ast.JoinExpr:
        lowered = super().visit_join_expr(node)
        join_type = lowered.join_type or ""
        if "ANY" not in join_type.split():
            return lowered
        target_join_type = _SUPPORTED_ANY_JOIN_TYPES.get(join_type)
        if target_join_type is None:
            raise TrinoLoweringError("TRINO_ANY_JOIN_MODE_UNSUPPORTED", join_type, lowered)
        if lowered.alias is None:
            if not isinstance(lowered.table, ast.Field) or not isinstance(lowered.table.chain[-1], str):
                raise TrinoLoweringError("TRINO_ANY_JOIN_ALIAS_REQUIRED", f"{join_type} without a right alias", lowered)
            lowered.alias = lowered.table.chain[-1]
        if lowered.column_aliases:
            raise TrinoLoweringError(
                "TRINO_ANY_JOIN_COLUMN_ALIASES_UNSUPPORTED", f"{join_type} with column aliases", lowered
            )
        if lowered.constraint is None or lowered.constraint.constraint_type != "ON":
            raise TrinoLoweringError("TRINO_ANY_JOIN_ON_REQUIRED", f"{join_type} without an ON constraint", lowered)

        table_type = lowered.type
        while isinstance(table_type, (ast.TableAliasType, ast.ColumnAliasedTableType, ast.CTETableAliasType)):
            if isinstance(table_type, ast.CTETableAliasType):
                table_type = table_type.cte_table_type
                continue
            table_type = table_type.table_type
        key_expressions = self._right_key_expressions(lowered.constraint.expr, lowered.alias, table_type)
        key_names = [
            name
            for expr in key_expressions
            if (name := self._right_field_name(expr, lowered.alias, table_type)) is not None
        ]
        if isinstance(table_type, ast.LazyTableType) and table_type.table.name == "persons" and key_names == ["id"]:
            lowered.join_type = target_join_type
            return lowered
        if isinstance(table_type, ast.CTETableType):
            column_names = list(table_type.select_query_type.columns)
        elif isinstance(table_type, ast.SelectQueryAliasType):
            column_names = list(table_type.select_query_type.columns)
        elif isinstance(lowered.table, (ast.SelectQuery, ast.SelectSetQuery)) and isinstance(
            lowered.table.type, (ast.SelectQueryType, ast.SelectSetQueryType)
        ):
            column_names = list(lowered.table.type.columns)
        elif isinstance(table_type, ast.LazyTableType):
            column_names = [
                field.name
                for field in table_type.table.fields.values()
                if isinstance(field, DatabaseField)
                and not (table_type.table.name == "persons" and field.name == "last_seen_at")
            ]
        elif not isinstance(table_type, ast.TableType):
            raise TrinoLoweringError(
                "TRINO_ANY_JOIN_COMPLETE_TABLE_REQUIRED",
                f"{join_type} against a relation without a physical column list",
                lowered,
            )
        else:
            column_names = [
                field.name for field in table_type.table.fields.values() if isinstance(field, DatabaseField)
            ]
        if not column_names:
            raise TrinoLoweringError("TRINO_ANY_JOIN_EMPTY_TABLE_UNSUPPORTED", f"{join_type} without columns", lowered)

        index = self.join_index
        self.join_index += 1
        source_alias = f"__hogql_any_source_{index}"
        ranked_alias = f"__hogql_any_ranked_{index}"
        row_name = f"__hogql_any_row_{index}"
        while row_name in column_names:
            row_name += "_"

        ranked = ast.SelectQuery(
            select=[ast.Field(chain=[source_alias, name]) for name in column_names]
            + [
                ast.Alias(
                    alias=row_name,
                    expr=ast.WindowFunction(
                        name="row_number",
                        exprs=[],
                        over_expr=ast.WindowExpr(
                            partition_by=[
                                self._qualify_right_expression(expr, lowered.alias, table_type, source_alias)
                                for expr in key_expressions
                            ]
                        ),
                    ),
                )
            ],
            select_from=ast.JoinExpr(
                table=lowered.table,
                table_args=lowered.table_args,
                alias=source_alias,
            ),
        )
        deduplicated = ast.SelectQuery(
            select=[ast.Field(chain=[ranked_alias, name]) for name in column_names],
            select_from=ast.JoinExpr(table=ranked, alias=ranked_alias),
            where=ast.CompareOperation(
                left=ast.Field(chain=[ranked_alias, row_name]),
                right=ast.Constant(value=1),
                op=ast.CompareOperationOp.Eq,
            ),
        )

        lowered.join_type = target_join_type
        lowered.table = deduplicated
        lowered.table_args = None
        lowered.column_aliases = None
        return lowered

    def _right_key_expressions(
        self, constraint: ast.Expr, alias: str, right_table_type: ast.BaseTableType
    ) -> list[ast.Expr]:
        terms = constraint.exprs if isinstance(constraint, ast.And) else [constraint]
        key_expressions: list[ast.Expr] = []
        for term in terms:
            if not isinstance(term, ast.CompareOperation) or term.op != ast.CompareOperationOp.Eq:
                raise TrinoLoweringError(
                    "TRINO_ANY_JOIN_EQUI_KEYS_REQUIRED",
                    "ANY JOIN with a non-equality ON term",
                    term,
                )
            left_is_right = self._expression_uses_only_right_fields(term.left, alias, right_table_type)
            right_is_right = self._expression_uses_only_right_fields(term.right, alias, right_table_type)
            if left_is_right == right_is_right:
                raise TrinoLoweringError(
                    "TRINO_ANY_JOIN_EQUI_KEYS_REQUIRED",
                    "ANY JOIN equality without exactly one right-side field",
                    term,
                )
            key_expressions.append(term.left if left_is_right else term.right)
        return key_expressions

    def _expression_uses_only_right_fields(
        self, expression: ast.Expr, alias: str, right_table_type: ast.BaseTableType
    ) -> bool:
        outer = self

        class RightFieldFinder(CloningVisitor):
            def __init__(self) -> None:
                super().__init__(clear_types=False)
                self.found = False
                self.invalid = False

            def visit_field(self, node: ast.Field) -> ast.Field:
                if outer._right_field_name(node, alias, right_table_type) is None:
                    self.invalid = True
                else:
                    self.found = True
                return node

        finder = RightFieldFinder()
        finder.visit(expression)
        return finder.found and not finder.invalid

    def _qualify_right_expression(
        self,
        expression: ast.Expr,
        alias: str,
        right_table_type: ast.BaseTableType,
        source_alias: str,
    ) -> ast.Expr:
        outer = self

        class RightFieldQualifier(CloningVisitor):
            def visit_field(self, node: ast.Field) -> ast.Field:
                name = outer._right_field_name(node, alias, right_table_type)
                if name is None:
                    raise TrinoLoweringError(
                        "TRINO_ANY_JOIN_EQUI_KEYS_REQUIRED",
                        "ANY JOIN right key expression includes a left-side field",
                        node,
                    )
                return ast.Field(chain=[source_alias, name], start=node.start, end=node.end)

        return RightFieldQualifier(clear_types=False).visit(expression)

    def _right_field_name(self, expression: ast.Expr, alias: str, right_table_type: ast.BaseTableType) -> str | None:
        while isinstance(expression, ast.Alias):
            expression = expression.expr
        if not isinstance(expression, ast.Field):
            return None
        field_type = expression.type
        while isinstance(field_type, ast.FieldAliasType):
            field_type = field_type.type
        if not isinstance(field_type, ast.FieldType):
            return None
        table_type = field_type.table_type
        while isinstance(table_type, ast.ColumnAliasedTableType):
            table_type = table_type.table_type
        if isinstance(table_type, ast.TableAliasType) and table_type.alias == alias:
            return field_type.name
        if isinstance(table_type, ast.CTETableAliasType) and table_type.alias == alias:
            return field_type.name
        if isinstance(table_type, ast.SelectQueryAliasType) and table_type.alias == alias:
            return field_type.name
        if (
            isinstance(table_type, ast.TableType)
            and isinstance(right_table_type, ast.TableType)
            and table_type.table is right_table_type.table
        ):
            return field_type.name
        if (
            isinstance(table_type, ast.LazyTableType)
            and isinstance(right_table_type, ast.LazyTableType)
            and table_type.table is right_table_type.table
        ):
            return field_type.name
        return None


def lower_trino_any_joins(node: ast.AST) -> ast.AST:
    return TrinoAnyJoinLowerer().visit(node)
