from typing import Any, Callable, Dict, List, Optional
from pydantic import BaseModel, Extra

from posthog.hogql.errors import HogQLException, NotImplementedException


class DatabaseField(BaseModel):
    """Base class for a field in a database table."""

    class Config:
        extra = Extra.forbid

    name: str
    array: Optional[bool]


class IntegerDatabaseField(DatabaseField):
    pass


class StringDatabaseField(DatabaseField):
    pass


class StringJSONDatabaseField(DatabaseField):
    pass


class DateTimeDatabaseField(DatabaseField):
    pass


class BooleanDatabaseField(DatabaseField):
    pass


class Table(BaseModel):
    class Config:
        extra = Extra.forbid

    def has_field(self, name: str) -> bool:
        return hasattr(self, name)

    def get_field(self, name: str) -> DatabaseField:
        if self.has_field(name):
            return getattr(self, name)
        raise HogQLException(f'Field "{name}" not found on table {self.__class__.__name__}')

    def clickhouse_table(self):
        raise NotImplementedException("Table.clickhouse_table not overridden")

    def hogql_table(self):
        raise NotImplementedException("Table.hogql_table not overridden")

    def avoid_asterisk_fields(self) -> List[str]:
        return []

    def get_asterisk(self) -> Dict[str, DatabaseField]:
        asterisk: Dict[str, DatabaseField] = {}
        fields_to_avoid = self.avoid_asterisk_fields() + ["team_id"]
        for key in self.dict().keys():
            if key in fields_to_avoid:
                continue
            database_field = getattr(self, key)
            if isinstance(database_field, DatabaseField):
                asterisk[key] = database_field
            elif (
                isinstance(database_field, Table)
                or isinstance(database_field, LazyJoin)
                or isinstance(database_field, FieldTraverser)
            ):
                pass  # ignore virtual tables for now
            else:
                raise HogQLException(f"Unknown field type {type(database_field).__name__} for asterisk")
        return asterisk


class LazyJoin(BaseModel):
    class Config:
        extra = Extra.forbid

    join_function: Callable[[str, str, str, Dict[str, Any]], Any]
    join_table: Table
    from_field: str


class LazyTable(Table):
    class Config:
        extra = Extra.forbid

    def lazy_select(self, requested_fields: Dict[str, List[str]]) -> Any:
        raise NotImplementedException("LazyTable.lazy_select not overridden")


class VirtualTable(Table):
    class Config:
        extra = Extra.forbid


class FieldTraverser(BaseModel):
    class Config:
        extra = Extra.forbid

    chain: List[str]
