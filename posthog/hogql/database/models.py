from typing import Any, Callable, Dict, List, Optional, TYPE_CHECKING
from pydantic import BaseModel, Extra

from posthog.hogql.errors import HogQLException, NotImplementedException


if TYPE_CHECKING:
    from posthog.hogql.context import HogQLContext


class DatabaseField(BaseModel):
    """
    Base class for a field in a database table.
    """

    class Config:
        extra = Extra.forbid

    name: str
    array: Optional[bool]


class IntegerDatabaseField(DatabaseField):
    pass


class FloatDatabaseField(DatabaseField):
    pass


class StringDatabaseField(DatabaseField):
    pass


class StringJSONDatabaseField(DatabaseField):
    pass


class DateDatabaseField(DatabaseField):
    pass


class DateTimeDatabaseField(DatabaseField):
    pass


class BooleanDatabaseField(DatabaseField):
    pass


class FieldTraverser(BaseModel):
    class Config:
        extra = Extra.forbid

    chain: List[str]


class Table(BaseModel):
    class Config:
        extra = Extra.forbid

    def has_field(self, name: str) -> bool:
        return hasattr(self, name)

    def get_field(self, name: str) -> DatabaseField:
        if self.has_field(name):
            return getattr(self, name)
        raise HogQLException(f'Field "{name}" not found on table {self.__class__.__name__}')

    def to_printed_clickhouse(self, context: "HogQLContext") -> str:
        raise NotImplementedException("Table.to_printed_clickhouse not overridden")

    def to_printed_hogql(self) -> str:
        raise NotImplementedException("Table.to_printed_hogql not overridden")

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

    join_function: Callable[[str, str, Dict[str, Any]], Any]
    join_table: Table
    from_field: str


class LazyTable(Table):
    """
    A table that is replaced with a subquery returned from `lazy_select(requested_fields: Dict[name, chain])`
    """

    class Config:
        extra = Extra.forbid

    def lazy_select(self, requested_fields: Dict[str, List[str]]) -> Any:
        raise NotImplementedException("LazyTable.lazy_select not overridden")


class VirtualTable(Table):
    """
    A nested table that reuses the parent for storage. E.g. events.person.* fields with PoE enabled.
    """

    class Config:
        extra = Extra.forbid


class FunctionCallTable(Table):
    """
    A table that returns a function call, e.g. numbers(...) or s3(...). The team_id guard is NOT added for these.
    """

    name: str
