from posthog.hogql import ast
from posthog.hogql.database.models import DatabaseField
from posthog.hogql.transforms.trino.errors import TrinoLoweringError
from posthog.hogql.visitor import CloningVisitor, TraversingVisitor, clone_expr

_SUPPORTED_ANY_JOIN_TYPES = {
    "ANY INNER JOIN": "INNER JOIN",
    "LEFT ANY JOIN": "LEFT JOIN",
}


class TrinoAnyJoinLowerer(CloningVisitor):
    def __init__(self) -> None:
        super().__init__(clear_types=False)
        self.join_index = 0

    def visit_select_query(self, node: ast.SelectQuery) -> ast.SelectQuery:
        first = node.select_from
        second = first.next_join if first is not None else None
        right_modes = {
            "RIGHT ANY JOIN": "LEFT ANY JOIN",
            "RIGHT SEMI JOIN": "LEFT SEMI JOIN",
            "RIGHT ANTI JOIN": "LEFT ANTI JOIN",
        }
        if first is not None and second is not None and second.join_type in right_modes:
            if second.next_join is not None:
                raise TrinoLoweringError(
                    "TRINO_RIGHT_JOIN_CHAIN_UNSUPPORTED", "RIGHT ANY, SEMI, or ANTI in a join chain", second
                )
            node = clone_expr(node, clear_types=False)
            first = node.select_from
            assert first is not None and first.next_join is not None
            second = first.next_join
            assert second.join_type is not None
            first.join_type = right_modes[second.join_type]
            first.constraint = second.constraint
            first.next_join = None
            second.join_type = None
            second.constraint = None
            second.next_join = first
            node.select_from = second
        lowered = super().visit_select_query(node)
        join = lowered.select_from
        while join is not None:
            if join.join_type in {"LEFT SEMI JOIN", "SEMI JOIN", "LEFT ANTI JOIN", "ANTI JOIN"}:
                self._lower_filter_join(lowered, join)
            join = join.next_join
        return lowered

    def _lower_filter_join(self, query: ast.SelectQuery, join: ast.JoinExpr) -> None:
        if join.column_aliases:
            raise TrinoLoweringError(
                "TRINO_FILTER_JOIN_COLUMN_ALIASES_UNSUPPORTED", "SEMI or ANTI column aliases", join
            )
        alias = join.alias
        if alias is None and isinstance(join.table, ast.Field) and isinstance(join.table.chain[-1], str):
            alias = join.table.chain[-1]
        if alias is None or join.constraint is None or join.constraint.constraint_type != "ON":
            raise TrinoLoweringError("TRINO_FILTER_JOIN_ON_REQUIRED", "SEMI or ANTI JOIN without an alias and ON", join)
        table_type = join.type
        while isinstance(table_type, (ast.TableAliasType, ast.ColumnAliasedTableType)):
            table_type = table_type.table_type
        if not isinstance(table_type, (ast.BaseTableType, ast.SelectQueryAliasType)):
            raise TrinoLoweringError(
                "TRINO_FILTER_JOIN_TABLE_UNRESOLVED", "SEMI or ANTI JOIN without a table type", join
            )
        keys = self._right_key_expressions(join.constraint.expr, alias, table_type)
        names = [self._right_field_name(key, alias, table_type) for key in keys]
        if not names or any(name is None for name in names):
            raise TrinoLoweringError(
                "TRINO_FILTER_JOIN_FIELD_KEYS_REQUIRED", "SEMI or ANTI JOIN with a computed right key", join
            )
        outer = self
        right_alias: str = alias
        right_type: ast.TableOrSelectType = table_type

        class RightReferenceValidator(TraversingVisitor):
            def visit_field(self, field: ast.Field) -> None:
                if outer._right_field_name(field, right_alias, right_type) is not None:
                    raise TrinoLoweringError(
                        "TRINO_FILTER_JOIN_RIGHT_OUTPUT_UNSUPPORTED", "SEMI or ANTI JOIN right-side output", field
                    )

        validator = RightReferenceValidator()
        for expression in [
            *query.select,
            query.where,
            query.prewhere,
            query.having,
            query.qualify,
            query.limit_by,
            *(query.group_by or []),
            *(query.order_by or []),
            *(query.array_join_list or []),
            *(query.window_exprs or {}).values(),
        ]:
            if expression is not None:
                validator.visit(expression)
        following = join.next_join
        while following is not None:
            if following.constraint is not None:
                validator.visit(following.constraint)
            if following.table is not None:
                validator.visit(following.table)
            for argument in following.table_args or []:
                validator.visit(argument)
            following = following.next_join
        source = clone_expr(join, clear_types=False)
        source.join_type = None
        source.constraint = None
        source.next_join = None
        join.table = ast.SelectQuery(
            select=[
                ast.Alias(alias=name, expr=ast.Field(chain=[alias, name])) for name in dict.fromkeys(names) if name
            ],
            select_from=source,
            distinct=True,
        )
        join.alias = alias
        join.table_args = None
        join.column_aliases = None
        join.table_final = None
        join.sample = None
        if "ANTI" in (join.join_type or "").split():
            predicate = ast.Call(name="isNull", args=[ast.Field(chain=[alias, str(names[0])])])
            query.where = ast.And(exprs=[query.where, predicate]) if query.where is not None else predicate
            join.join_type = "LEFT JOIN"
        else:
            join.join_type = "INNER JOIN"

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
        self, constraint: ast.Expr, alias: str, right_table_type: ast.TableOrSelectType
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
        self, expression: ast.Expr, alias: str, right_table_type: ast.TableOrSelectType
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
        right_table_type: ast.TableOrSelectType,
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

    def _right_field_name(
        self, expression: ast.Expr, alias: str, right_table_type: ast.TableOrSelectType
    ) -> str | None:
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
