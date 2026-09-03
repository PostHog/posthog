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
            raise TrinoLoweringError("TRINO_ANY_JOIN_ALIAS_REQUIRED", f"{join_type} without a right alias", lowered)
        if lowered.column_aliases:
            raise TrinoLoweringError(
                "TRINO_ANY_JOIN_COLUMN_ALIASES_UNSUPPORTED", f"{join_type} with column aliases", lowered
            )
        if lowered.constraint is None or lowered.constraint.constraint_type != "ON":
            raise TrinoLoweringError("TRINO_ANY_JOIN_ON_REQUIRED", f"{join_type} without an ON constraint", lowered)

        table_type = lowered.type
        while isinstance(table_type, (ast.TableAliasType, ast.ColumnAliasedTableType)):
            table_type = table_type.table_type
        if not isinstance(table_type, ast.TableType) or not getattr(table_type.table, "has_complete_columns", False):
            raise TrinoLoweringError(
                "TRINO_ANY_JOIN_COMPLETE_TABLE_REQUIRED",
                f"{join_type} against a relation without a complete physical column list",
                lowered,
            )
        if any(not isinstance(field, DatabaseField) for field in table_type.table.fields.values()):
            raise TrinoLoweringError(
                "TRINO_ANY_JOIN_PHYSICAL_COLUMNS_REQUIRED",
                f"{join_type} against a relation with logical or nested fields",
                lowered,
            )

        column_names = [field.name for field in table_type.table.fields.values() if isinstance(field, DatabaseField)]
        if not column_names:
            raise TrinoLoweringError("TRINO_ANY_JOIN_EMPTY_TABLE_UNSUPPORTED", f"{join_type} without columns", lowered)
        key_names = self._right_key_names(lowered.constraint.expr, lowered.alias)

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
                            partition_by=[ast.Field(chain=[source_alias, name]) for name in key_names]
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

    def _right_key_names(self, constraint: ast.Expr, alias: str) -> list[str]:
        terms = constraint.exprs if isinstance(constraint, ast.And) else [constraint]
        key_names: list[str] = []
        for term in terms:
            if not isinstance(term, ast.CompareOperation) or term.op != ast.CompareOperationOp.Eq:
                raise TrinoLoweringError(
                    "TRINO_ANY_JOIN_EQUI_KEYS_REQUIRED",
                    "ANY JOIN with a non-equality ON term",
                    term,
                )
            left_name = self._right_field_name(term.left, alias)
            right_name = self._right_field_name(term.right, alias)
            if (left_name is None) == (right_name is None):
                raise TrinoLoweringError(
                    "TRINO_ANY_JOIN_EQUI_KEYS_REQUIRED",
                    "ANY JOIN equality without exactly one right-side field",
                    term,
                )
            key_names.append(left_name or right_name or "")
        return list(dict.fromkeys(key_names))

    def _right_field_name(self, expression: ast.Expr, alias: str) -> str | None:
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
        return None


def lower_trino_any_joins(node: ast.AST) -> ast.AST:
    return TrinoAnyJoinLowerer().visit(node)
