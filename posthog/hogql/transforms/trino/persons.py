from typing import ClassVar

from posthog.hogql import ast
from posthog.hogql.context import HogQLContext
from posthog.hogql.database.lazy_join_tags import FOREIGN_KEY
from posthog.hogql.database.models import (
    DateTimeDatabaseField,
    FieldOrTable,
    IntegerDatabaseField,
    LazyJoin,
    LazyTable,
    LazyTableToAdd,
    StringDatabaseField,
    Table,
    UUIDDatabaseField,
)
from posthog.hogql.database.schema.events import EventsTable
from posthog.hogql.database.schema.persons import PERSONS_FIELDS, PersonsTable
from posthog.hogql.errors import QueryError

TRINO_PERSONS_PDI_TABLE_NAME = "__trino_persons_pdi"

# DuckLake does not export last_seen_at, so the lowering rejects it before SQL reaches Trino.
TRINO_EXPORTED_PERSONS_FIELDS: dict[str, FieldOrTable] = {
    name: field for name, field in PERSONS_FIELDS.items() if name != "last_seen_at"
}


class TrinoPhysicalPersonsTable(Table):
    name: str | None = None
    fields: dict[str, FieldOrTable] = {
        **TRINO_EXPORTED_PERSONS_FIELDS,
        "distinct_id": StringDatabaseField(name="distinct_id", nullable=False),
        "person_distinct_id_version": IntegerDatabaseField(name="person_distinct_id_version", nullable=False),
        "person_version": IntegerDatabaseField(name="person_version", nullable=False),
        "_inserted_at": DateTimeDatabaseField(name="_inserted_at", nullable=False),
    }
    trino_locator_name: ClassVar[str] = "persons"

    def to_printed_hogql(self) -> str:
        return "persons"


TRINO_PHYSICAL_PERSONS_TABLE = TrinoPhysicalPersonsTable()


def _latest_rows_select(
    table_to_add: LazyTableToAdd,
    *,
    group_field: str,
    version_fields: tuple[str, ...],
) -> ast.SelectQuery:
    select: list[ast.Expr] = [ast.Field(chain=[group_field])]
    version = ast.Call(name="tuple", args=[ast.Field(chain=[field]) for field in version_fields])

    for alias, chain in table_to_add.fields_accessed.items():
        if chain and chain[0] == "last_seen_at":
            raise QueryError("Last seen is not available for managed warehouse queries.")
        if chain == [group_field]:
            if alias != group_field:
                select.append(ast.Alias(alias=alias, expr=ast.Field(chain=[group_field])))
            continue
        select.append(
            ast.Alias(
                alias=alias,
                expr=ast.Call(name="argMax", args=[ast.Field(chain=chain), version]),
            )
        )

    return ast.SelectQuery(
        select=select,
        select_from=ast.JoinExpr(
            table=ast.Field(chain=["persons"], type=ast.TableType(table=TRINO_PHYSICAL_PERSONS_TABLE))
        ),
        group_by=[ast.Field(chain=[group_field])],
    )


class TrinoPersonsPDITable(LazyTable):
    name: str | None = TRINO_PERSONS_PDI_TABLE_NAME
    fields: dict[str, FieldOrTable] = {
        "team_id": IntegerDatabaseField(name="team_id", nullable=False),
        "distinct_id": StringDatabaseField(name="distinct_id", nullable=False),
        "person_id": UUIDDatabaseField(name="person_id", nullable=False),
    }

    def lazy_select(
        self,
        table_to_add: LazyTableToAdd,
        context: HogQLContext,
        node: ast.SelectQuery,
    ) -> ast.SelectQuery:
        fields_accessed = {
            alias: ["id", *chain[1:]] if chain and chain[0] == "person_id" else chain
            for alias, chain in table_to_add.fields_accessed.items()
        }
        fields_accessed.setdefault("person_id", ["id"])
        return _latest_rows_select(
            LazyTableToAdd(lazy_table=self, fields_accessed=fields_accessed),
            group_field="distinct_id",
            version_fields=("person_distinct_id_version", "person_version", "_inserted_at"),
        )

    def to_printed_hogql(self) -> str:
        return TRINO_PERSONS_PDI_TABLE_NAME


TRINO_PERSONS_PDI_TABLE = TrinoPersonsPDITable()


class TrinoPersonsTable(LazyTable):
    name: str | None = "persons"
    fields: dict[str, FieldOrTable] = {
        **PERSONS_FIELDS,
        "pdi": LazyJoin(
            from_field=["id"],
            join_table=TRINO_PERSONS_PDI_TABLE,
            to_field=["person_id"],
            resolver=FOREIGN_KEY,
        ),
    }

    def lazy_select(
        self,
        table_to_add: LazyTableToAdd,
        context: HogQLContext,
        node: ast.SelectQuery,
    ) -> ast.SelectQuery:
        return _latest_rows_select(
            table_to_add,
            group_field="id",
            version_fields=("person_version", "_inserted_at"),
        )

    def to_printed_hogql(self) -> str:
        return "persons"


TRINO_PERSONS_TABLE = TrinoPersonsTable()


def resolve_trino_table_reference(field: ast.Field, context: HogQLContext) -> Table | None:
    if "persons" not in context.trino_table_locators:
        return None
    if isinstance(field.type, ast.TableType) and field.type.table is TRINO_PHYSICAL_PERSONS_TABLE:
        return TRINO_PHYSICAL_PERSONS_TABLE
    return None


def is_internal_trino_logical_table(table_name_chain: list[str | int]) -> bool:
    return table_name_chain == [TRINO_PERSONS_PDI_TABLE_NAME]


def resolve_internal_trino_logical_table(table_name_chain: list[str], context: HogQLContext) -> Table | None:
    if "persons" not in context.trino_table_locators:
        return None
    if table_name_chain == [TRINO_PERSONS_PDI_TABLE_NAME]:
        return TRINO_PERSONS_PDI_TABLE
    return None


def lower_trino_table(table: Table, context: HogQLContext) -> Table:
    if "persons" not in context.trino_table_locators:
        return table
    if isinstance(table, PersonsTable):
        return TRINO_PERSONS_TABLE
    if isinstance(table, EventsTable):
        return table.model_copy(
            update={
                "fields": {
                    **table.fields,
                    "override": LazyJoin(
                        from_field=["distinct_id"],
                        join_table=TRINO_PERSONS_PDI_TABLE,
                        to_field=["distinct_id"],
                        resolver=FOREIGN_KEY,
                    ),
                }
            }
        )
    return table
