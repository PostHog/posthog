from dataclasses import fields

from posthog.hogql import ast
from posthog.hogql.context import HogQLContext
from posthog.hogql.database.models import DatabaseField, Table


def prepare_trino_view_types(node: ast.AST, context: HogQLContext, stack: list[ast.SelectQuery] | None = None) -> None:
    pending: list[object] = [node, *(stack or [])]
    visited: set[int] = set()
    column_tables: dict[str, Table] = {}
    while pending:
        current = pending.pop()
        if not isinstance(current, (ast.AST, dict, list, tuple)) or id(current) in visited:
            continue
        visited.add(id(current))
        if isinstance(current, ast.AST):
            if isinstance(current, ast.SelectViewType):
                if current.view_name not in column_tables:
                    table = current.resolve_database_table(context)
                    column_tables[current.view_name] = Table(
                        name=table.name,
                        fields={
                            name: column.model_copy(deep=True)
                            for name, column in table.fields.items()
                            if isinstance(column, DatabaseField)
                        },
                    )
                current.column_table = column_tables[current.view_name]
            # Expression visitors skip type edges, which can contain view references and cycles.
            pending.extend(getattr(current, field.name) for field in fields(current))
        elif isinstance(current, dict):
            pending.extend(current.values())
        elif isinstance(current, (list, tuple)):
            pending.extend(current)
