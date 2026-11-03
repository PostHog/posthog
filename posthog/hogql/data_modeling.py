from dataclasses import field

from posthog.hogql.context import HogQLContext
from posthog.hogql.database.models import FieldOrTable, StructDatabaseField, Table, TableNode
from posthog.hogql.errors import QueryError

from posthog.dataclasses import frozen


@frozen(frozen=False)
class ModelingSourceFields:
    fields: set[str] = field(default_factory=set)
    known: bool = True

    def serialize(self) -> list[str] | None:
        return sorted(self.fields) if self.known else None


def modeling_field_key(table: Table, name: str) -> str:
    return f"{type(table).__module__}.{type(table).__name__}:{table.name}:{name}"


def modeling_field_policies(root: TableNode) -> dict[str, bool]:
    pending: list[FieldOrTable | TableNode] = [root]
    visited: set[int] = set()
    policies: dict[str, bool] = {}
    while pending:
        node = pending.pop()
        if id(node) in visited:
            continue
        visited.add(id(node))
        if isinstance(node, TableNode):
            pending.extend(node.children.values())
            if node.table is not None:
                pending.append(node.table)
        elif isinstance(node, Table):
            for name, field in node.fields.items():
                policies[modeling_field_key(node, name)] = field.modeling_allowed
                if isinstance(field, StructDatabaseField):
                    policies[modeling_field_key(node, name)] &= all(
                        child.modeling_allowed for child in field.fields.values()
                    )
            pending.extend(node.fields.values())
    return policies


def validate_modeling_field(table: Table, name: str, context: HogQLContext) -> None:
    database = context.database
    if database is None or not database.for_data_modeling:
        return
    key = modeling_field_key(table, name)
    if not table.get_field(name).modeling_allowed or not database.modeling_field_policies.get(key, True):
        raise QueryError(f"Field `{name}` is not available for data modeling. Remove it from the query.")
    if context.user is not None and context.restricted_properties:
        from posthog.hogql import ast  # noqa: PLC0415 - avoids the AST import cycle
        from posthog.hogql.restricted_properties import (  # noqa: PLC0415 - avoids the AST import cycle
            RESTRICTABLE_JSON_BLOB_COLUMNS,
            mirrored_property_for_column,
            restricted_property_keys_for_table_type,
        )

        table_type = ast.TableType(table=table)
        restricted = restricted_property_keys_for_table_type(table_type, context)
        if restricted and (
            name in RESTRICTABLE_JSON_BLOB_COLUMNS
            or mirrored_property_for_column(table_type, name, context) in restricted
        ):
            raise QueryError(
                "This source field has restricted properties. "
                "Ask an administrator for full property access before you use it in data modeling."
            )
    if key in database.modeling_field_policies:
        database.modeling_source_fields.add(key)


def validate_materialized_view_fields(table: Table, context: HogQLContext) -> None:
    database = context.database
    if database is None or not table.is_materialized_view:
        return
    fields = table.modeling_source_fields
    if not all(database.modeling_field_policies.values()):
        if fields is None or any(not database.modeling_field_policies.get(key, False) for key in fields):
            raise QueryError(
                "This materialized view has no valid source field record for data modeling. "
                "Remove restricted fields from its query and run a full rebuild."
            )
    if database.for_data_modeling:
        if fields is None:
            database.modeling_source_fields_known = False
        else:
            database.modeling_source_fields.update(fields)
