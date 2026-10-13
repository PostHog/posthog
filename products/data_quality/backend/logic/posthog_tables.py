"""The PostHog tables a check can be authored on, each with a deterministic id from its name."""

from collections.abc import Callable, Collection
from uuid import NAMESPACE_URL, UUID, uuid5

from posthog.schema import DatabaseSerializedFieldType

from posthog.hogql.database.models import (
    BooleanDatabaseField,
    DatabaseField,
    DateDatabaseField,
    DateTimeDatabaseField,
    ExpressionField,
    FloatDatabaseField,
    IntegerDatabaseField,
    StringArrayDatabaseField,
    StringJSONDatabaseField,
    Table,
)
from posthog.hogql.database.schema.events import EventsTable
from posthog.hogql.database.schema.groups import GroupsTable
from posthog.hogql.database.schema.persons import PersonsTable

from posthog.dataclasses import frozen
from posthog.scopes import APIScopeObject

_SUBJECT_NAMESPACE = "data-quality-posthog-table:"
RESOURCE: APIScopeObject = "warehouse_table"

_FIELD_TYPES: list[tuple[type, DatabaseSerializedFieldType]] = [
    (IntegerDatabaseField, DatabaseSerializedFieldType.INTEGER),
    (FloatDatabaseField, DatabaseSerializedFieldType.FLOAT),
    (StringJSONDatabaseField, DatabaseSerializedFieldType.JSON),
    (StringArrayDatabaseField, DatabaseSerializedFieldType.ARRAY),
    (DateTimeDatabaseField, DatabaseSerializedFieldType.DATETIME),
    (DateDatabaseField, DatabaseSerializedFieldType.DATE),
    (BooleanDatabaseField, DatabaseSerializedFieldType.BOOLEAN),
    (ExpressionField, DatabaseSerializedFieldType.EXPRESSION),
    (DatabaseField, DatabaseSerializedFieldType.STRING),
]


@frozen
class PostHogTable:
    name: str
    time_column: str
    table_class: Callable[[], Table]

    @property
    def id(self) -> UUID:
        return uuid5(NAMESPACE_URL, f"{_SUBJECT_NAMESPACE}{self.name}")

    @property
    def columns(self) -> dict[str, str]:
        return {
            name: _field_type(field)
            for name, field in self.table_class().fields.items()
            if isinstance(field, DatabaseField) and not field.hidden
        }


TABLES: tuple[PostHogTable, ...] = (
    PostHogTable(name="events", time_column="timestamp", table_class=EventsTable),
    PostHogTable(name="persons", time_column="created_at", table_class=PersonsTable),
    PostHogTable(name="groups", time_column="created_at", table_class=GroupsTable),
)

_BY_NAME = {table.name: table for table in TABLES}
_BY_ID = {table.id: table for table in TABLES}


def by_name(name: str) -> PostHogTable | None:
    return _BY_NAME.get(name)


def by_id(subject_uuid: str | UUID) -> PostHogTable | None:
    try:
        return _BY_ID.get(UUID(str(subject_uuid)))
    except ValueError:
        return None


def all_ids() -> frozenset[UUID]:
    return frozenset(_BY_ID)


def names_of(ids: Collection[UUID]) -> list[str]:
    return [entry.name for entry in TABLES if entry.id in ids]


def names() -> tuple[str, ...]:
    return tuple(_BY_NAME)


def _field_type(field: object) -> str:
    for field_class, serialized in _FIELD_TYPES:
        if isinstance(field, field_class):
            return serialized.value
    return DatabaseSerializedFieldType.UNKNOWN.value
