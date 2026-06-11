import dataclasses
from collections.abc import Sequence
from typing import Any, Protocol

from posthog.hogql.database.direct_postgres_table import DirectPostgresTable
from posthog.hogql.database.lazy_join_tags import FOREIGN_KEY
from posthog.hogql.database.models import LazyJoin, Table, TableNode
from posthog.hogql.database.utils import get_join_field_chain

from posthog.exceptions_capture import capture_exception

from products.warehouse_sources.backend.models.external_data_schema import ExternalDataSchema
from products.warehouse_sources.backend.models.external_data_source import ExternalDataSource
from products.warehouse_sources.backend.models.table import DataWarehouseTable


class DatabaseTableLookup(Protocol):
    def has_table(self, table_name: str | list[str]) -> bool: ...

    def get_table(self, table_name: str | list[str]) -> Table: ...

    def get_table_node(self, table_name: str | list[str]) -> TableNode: ...


@dataclasses.dataclass(frozen=True)
class WarehouseForeignKey:
    column: str
    target_table: str
    target_column: str


def add_postgres_foreign_key_lazy_joins(
    source_name: str,
    warehouse_table: DataWarehouseTable,
    database: DatabaseTableLookup,
    schemas: Sequence[ExternalDataSchema],
    field_names_by_name: dict[str, set[str]] | None = None,
) -> None:
    """Wire a warehouse table's foreign keys, emitting forward/reverse joins onto the source/target
    *nodes* by name (via add_pending_field). Works from the source's name and column metadata, so it can
    run before the source (a deferred stub) is built and never forces it to build.

    `field_names_by_name` maps each warehouse table's name to the field names it will expose, so FK
    inference can resolve a target's columns without building it."""
    columns = warehouse_table.columns or {}
    # The field names the built table will expose (after redefinitions / dropped columns / synthetic
    # `properties`). Checking against these — not raw columns — keeps FK wiring byte-identical to the
    # eager build, which consulted the built table's fields, while still avoiding a build. Reuse the
    # caller's prebuilt map entry for this table when present rather than recomputing it.
    field_names = (field_names_by_name or {}).get(source_name) or warehouse_table.hogql_field_names()
    foreign_keys = _get_foreign_keys_from_schemas(schemas)

    for foreign_key in foreign_keys:
        _add_foreign_key_lazy_join(
            source_name=source_name,
            warehouse_table=warehouse_table,
            field_names=field_names,
            database=database,
            column=foreign_key.column,
            target_table=foreign_key.target_table,
            target_column=foreign_key.target_column,
        )

    if foreign_keys:
        return

    # Fallback inference when explicit FK metadata is unavailable.
    # This keeps direct Postgres ergonomics high for common *_id columns.
    namespace = source_name.split(".")[:-1]

    for column_name in columns.keys():
        if not column_name.endswith("_id") or len(column_name) <= 3:
            continue

        field_name = column_name[:-3]
        if field_name in field_names:
            continue

        inferred_foreign_key = _find_inferred_foreign_key(
            column=column_name,
            base_name=field_name,
            namespace=namespace,
            source_name=source_name,
            warehouse_table=warehouse_table,
            database=database,
            field_names_by_name=field_names_by_name or {},
        )
        if inferred_foreign_key is None:
            continue

        _add_foreign_key_lazy_join(
            source_name=source_name,
            warehouse_table=warehouse_table,
            field_names=field_names,
            database=database,
            column=inferred_foreign_key.column,
            target_table=inferred_foreign_key.target_table,
            target_column=inferred_foreign_key.target_column,
        )


def _get_foreign_keys_from_schemas(schemas: Sequence[ExternalDataSchema]) -> list[WarehouseForeignKey]:
    schema_with_foreign_keys = next((schema for schema in schemas if _get_foreign_keys(schema)), None)
    return _get_foreign_keys(schema_with_foreign_keys) if schema_with_foreign_keys is not None else []


def _get_foreign_keys(schema: ExternalDataSchema | None) -> list[WarehouseForeignKey]:
    if schema is None:
        return []

    raw_foreign_keys: Any = schema.foreign_keys
    if raw_foreign_keys is None:
        metadata = schema.sync_type_config.get("schema_metadata") if schema.sync_type_config else None
        if isinstance(metadata, dict):
            raw_foreign_keys = metadata.get("foreign_keys")

    if not isinstance(raw_foreign_keys, list):
        return []

    foreign_keys: list[WarehouseForeignKey] = []
    for foreign_key in raw_foreign_keys:
        if not isinstance(foreign_key, dict):
            continue

        column = foreign_key.get("column")
        target_table = foreign_key.get("target_table")
        target_column = foreign_key.get("target_column")
        if not (isinstance(column, str) and isinstance(target_table, str) and isinstance(target_column, str)):
            continue

        foreign_keys.append(WarehouseForeignKey(column=column, target_table=target_table, target_column=target_column))

    return foreign_keys


def _add_foreign_key_lazy_join(
    *,
    source_name: str,
    warehouse_table: DataWarehouseTable,
    field_names: set[str],
    database: DatabaseTableLookup,
    column: str,
    target_table: str,
    target_column: str,
) -> None:
    if not column or not target_table or not target_column:
        return

    try:
        from_field = get_join_field_chain(column)
        to_field = get_join_field_chain(target_column)
    except Exception as error:
        capture_exception(error)
        return

    if from_field is None or to_field is None:
        return

    field_name = column[:-3] if column.endswith("_id") and len(column) > 3 else column
    # A field already named `field_name` (e.g. `user` alongside `user_id`) owns that name; don't shadow
    # it with a FK join, and don't emit the matching reverse join either. Checked against the built
    # field set (which may redefine/drop columns) so this matches the eager build without forcing one.
    if field_name in field_names:
        return

    source_table_name = source_name

    target_table_name = _resolve_target_name(
        target_table=target_table,
        source_table_name=source_table_name,
        database=database,
    )
    if target_table_name is None:
        return

    if not _is_same_external_scope(source_table_name, target_table_name, warehouse_table, database):
        return

    # Forward and reverse FK joins are attached to the source/target *nodes*, by name, via
    # add_pending_field: applied immediately if the node is already built, or when it later materializes
    # if it's a deferred stub. Referencing both endpoints by name (resolved lazily on traversal) means
    # wiring a table's FK never forces another table to build. The join recipe is plain data — a
    # resolver tag, not a closure — so the built table stays serializable.
    database.get_table_node(source_table_name).add_pending_field(
        field_name,
        LazyJoin(
            from_field=from_field,
            to_field=to_field,
            join_table=target_table_name,
            resolver=FOREIGN_KEY,
        ),
        override=False,
    )

    reverse_field_name = _reverse_foreign_key_field_name(source_table_name, target_table_name)
    database.get_table_node(target_table_name).add_pending_field(
        reverse_field_name,
        LazyJoin(
            from_field=to_field,
            to_field=from_field,
            join_table=source_table_name,
            resolver=FOREIGN_KEY,
        ),
        override=False,
    )


def _resolve_target_name(
    *,
    target_table: str,
    source_table_name: str,
    database: DatabaseTableLookup,
) -> str | None:
    """Resolve a FK target to its (possibly namespace-qualified) table name without building it.

    Uses has_table (which treats an unbuilt stub as present), so the join can be wired without forcing
    the target's build — the resolver materializes it lazily only if a query traverses the join.
    """
    name = target_table
    if "." in source_table_name and "." not in name:
        name = ".".join([*source_table_name.split(".")[:-1], name])

    if not database.has_table(name):
        return None

    return name


def _is_same_external_scope(
    source_table_name: str,
    target_table_name: str,
    warehouse_table: DataWarehouseTable,
    database: DatabaseTableLookup,
) -> bool:
    source = warehouse_table.external_data_source
    if source is not None and source.access_method == ExternalDataSource.AccessMethod.DIRECT:
        # Direct-query mode (the eager path): the scope check needs the built target's type/source id,
        # so resolve it here. This branch is not reached on the lazy path (direct queries stay eager).
        if not database.has_table(target_table_name):
            return False
        target_hogql_table = database.get_table(target_table_name)
        return isinstance(
            target_hogql_table, DirectPostgresTable
        ) and target_hogql_table.external_data_source_id == str(source.id)

    if "." not in source_table_name or "." not in target_table_name:
        return False

    return source_table_name.rsplit(".", 1)[0] == target_table_name.rsplit(".", 1)[0]


def _reverse_foreign_key_field_name(from_table: str, target_table: str) -> str:
    from_base = from_table.split(".")[-1]
    target_base = target_table.split(".")[-1]

    if from_base.startswith(target_base):
        reverse_name = from_base[len(target_base) :].lstrip("_") or from_base
    else:
        reverse_name = from_base

    if not reverse_name.endswith("s"):
        reverse_name = f"{reverse_name}s"

    return reverse_name


def _find_inferred_foreign_key(
    *,
    column: str,
    base_name: str,
    namespace: list[str],
    source_name: str,
    warehouse_table: DataWarehouseTable,
    database: DatabaseTableLookup,
    field_names_by_name: dict[str, set[str]],
) -> WarehouseForeignKey | None:
    source_table_name = source_name

    for candidate in _candidate_target_tables(base_name=base_name, namespace=namespace):
        if not database.has_table(candidate) or candidate == source_table_name:
            continue

        # Read the target's field names from metadata (no build). hogql_field_names() equals the built
        # field set (pinned by test), so this is equivalent to inspecting the built table. Fall back to
        # building only for a candidate that isn't a known warehouse table (e.g. a view) — uncommon, and
        # preserves the prior behavior there.
        target_field_names = field_names_by_name.get(candidate)
        if target_field_names is None:
            target_hogql_table = database.get_table(candidate)
            if not isinstance(target_hogql_table, Table) or not isinstance(target_hogql_table.name, str):
                continue
            target_field_names = set(target_hogql_table.fields)

        if not _is_same_external_scope(source_table_name, candidate, warehouse_table, database):
            continue

        target_column = next((name for name in (column, "id") if name in target_field_names), None)
        if target_column is None:
            continue

        return WarehouseForeignKey(column=column, target_table=candidate, target_column=target_column)

    return None


def _candidate_target_tables(*, base_name: str, namespace: list[str]) -> list[str]:
    local_candidates = [base_name, f"{base_name}s", f"posthog_{base_name}"]
    scoped_candidates = [".".join([*namespace, candidate]) for candidate in local_candidates] if namespace else []
    return scoped_candidates or local_candidates
