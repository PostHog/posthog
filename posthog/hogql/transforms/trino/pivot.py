from posthog.hogql import ast
from posthog.hogql.transforms.trino.errors import TrinoLoweringError
from posthog.hogql.visitor import TraversingVisitor, clone_expr


class TrinoPivotLowerer:
    def lower(self, node: ast.PivotExpr, source_columns: list[str]) -> ast.SelectQuery:
        if len(node.columns) != 1 or len(node.aggregates) != 1:
            raise TrinoLoweringError("TRINO_PIVOT_SHAPE_UNSUPPORTED", "PIVOT with multiple keys or aggregates", node)
        column = node.columns[0]
        key = column.column
        while isinstance(key, ast.Alias) and key.hidden:
            key = key.expr
        aggregate = node.aggregates[0]
        suffix = ""
        if isinstance(aggregate, ast.Alias):
            suffix = f"_{aggregate.alias}"
            aggregate = aggregate.expr
        if not isinstance(aggregate, ast.Call) or aggregate.name.lower() not in {"count", "sum", "avg", "min", "max"}:
            raise TrinoLoweringError("TRINO_PIVOT_AGGREGATE_UNSUPPORTED", "PIVOT without a standard aggregate", node)
        if not isinstance(key, ast.Field) or not column.values:
            raise TrinoLoweringError(
                "TRINO_PIVOT_SHAPE_UNSUPPORTED", "PIVOT without a field key and static values", node
            )
        consumed: set[str] = set()

        class ConsumedFields(TraversingVisitor):
            def visit_field(self, field: ast.Field) -> None:
                consumed.add(str(field.chain[-1]))

        finder = ConsumedFields()
        finder.visit(key)
        finder.visit(aggregate)
        groups: list[ast.Expr] = (
            node.group_by
            if node.group_by is not None
            else [ast.Field(chain=[name]) for name in source_columns if name not in consumed]
        )
        if not all(isinstance(group, ast.Field) for group in groups):
            raise TrinoLoweringError("TRINO_PIVOT_GROUP_UNSUPPORTED", "PIVOT with a computed grouping key", node)
        names = {str(group.chain[-1]).casefold() for group in groups if isinstance(group, ast.Field)}
        projections = list(groups)
        for value in column.values:
            name = None
            if isinstance(value, ast.Alias):
                name = value.alias
                value = value.expr
            if (
                not isinstance(value, ast.Constant)
                or not isinstance(value.value, (str, int))
                or isinstance(value.value, bool)
            ):
                raise TrinoLoweringError(
                    "TRINO_PIVOT_VALUE_UNSUPPORTED", "PIVOT with a non-string or non-integer value", value
                )
            name = f"{name if name is not None else value.value}{suffix}"
            if name.casefold() in names:
                raise TrinoLoweringError("TRINO_PIVOT_OUTPUT_COLLISION", "PIVOT with duplicate output names", node)
            names.add(name.casefold())
            filtered = clone_expr(aggregate, clear_types=False)
            predicate = ast.CompareOperation(left=key, op=ast.CompareOperationOp.Eq, right=value)
            filtered.filter_expr = (
                ast.And(exprs=[filtered.filter_expr, predicate]) if filtered.filter_expr is not None else predicate
            )
            projections.append(ast.Alias(alias=name, expr=filtered))
        if isinstance(node.table, ast.JoinExpr):
            source = node.table
        elif isinstance(
            node.table,
            (ast.Field, ast.SelectQuery, ast.SelectSetQuery, ast.ValuesQuery, ast.UnpivotExpr, ast.PivotExpr),
        ):
            source = ast.JoinExpr(table=node.table)
        else:
            raise TrinoLoweringError("TRINO_PIVOT_SOURCE_UNSUPPORTED", "PIVOT without a table source", node)
        return ast.SelectQuery(select=projections, select_from=source, group_by=groups or None)
