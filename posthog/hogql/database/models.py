from typing import Any, Callable, Dict, List, Optional, TYPE_CHECKING
from pydantic import ConfigDict, BaseModel

from posthog.hogql.base import Expr
from posthog.hogql.errors import HogQLException, NotImplementedException
from posthog.schema import HogQLQueryModifiers

if TYPE_CHECKING:
    from posthog.hogql.context import HogQLContext
    from posthog.hogql.ast import SelectQuery


class FieldOrTable(BaseModel):
    pass


class DatabaseField(FieldOrTable):
    """
    Base class for a field in a database table.
    """

    model_config = ConfigDict(extra="forbid")

    name: str
    array: Optional[bool] = None
    nullable: Optional[bool] = None


class IntegerDatabaseField(DatabaseField):
    pass


class FloatDatabaseField(DatabaseField):
    pass


class StringDatabaseField(DatabaseField):
    pass


class StringJSONDatabaseField(DatabaseField):
    pass


class StringArrayDatabaseField(DatabaseField):
    pass


class DateDatabaseField(DatabaseField):
    pass


class DateTimeDatabaseField(DatabaseField):
    pass


class BooleanDatabaseField(DatabaseField):
    pass


class ExpressionField(DatabaseField):
    expr: Expr


class FieldTraverser(FieldOrTable):
    model_config = ConfigDict(extra="forbid")

    chain: List[str]


class Table(FieldOrTable):
    fields: Dict[str, FieldOrTable]
    model_config = ConfigDict(extra="forbid")

    def has_field(self, name: str) -> bool:
        return name in self.fields

    def get_field(self, name: str) -> FieldOrTable:
        if self.has_field(name):
            return self.fields[name]
        raise Exception(f'Field "{name}" not found on table {self.__class__.__name__}')

    def to_printed_clickhouse(self, context: "HogQLContext") -> str:
        raise NotImplementedException("Table.to_printed_clickhouse not overridden")

    def to_printed_hogql(self) -> str:
        raise NotImplementedException("Table.to_printed_hogql not overridden")

    def avoid_asterisk_fields(self) -> List[str]:
        return []

    def get_asterisk(self):
        fields_to_avoid = self.avoid_asterisk_fields() + ["team_id"]
        asterisk: Dict[str, FieldOrTable] = {}
        for key, field in self.fields.items():
            if key in fields_to_avoid:
                continue
            if (
                isinstance(field, Table)
                or isinstance(field, LazyJoin)
                or isinstance(field, FieldTraverser)
                or isinstance(field, ExpressionField)
            ):
                pass  # ignore virtual tables and columns for now
            elif isinstance(field, DatabaseField):
                asterisk[key] = field
            else:
                raise HogQLException(f"Unknown field type {type(field).__name__} for asterisk")
        return asterisk


class LazyJoin(FieldOrTable):
    model_config = ConfigDict(extra="forbid")

    join_function: Callable[[str, str, Dict[str, Any], Dict[str, List[str | int]], "HogQLContext", "SelectQuery"], Any]
    join_table: Table
    from_field: str


class LazyTable(Table):
    """
    A table that is replaced with a subquery returned from `lazy_select(requested_fields: Dict[name, chain], modifiers: HogQLQueryModifiers)`
    """

    model_config = ConfigDict(extra="forbid")

    def lazy_select(self, requested_fields: Dict[str, List[str | int]], modifiers: HogQLQueryModifiers) -> Any:
        raise NotImplementedException("LazyTable.lazy_select not overridden")


class VirtualTable(Table):
    """
    A nested table that reuses the parent for storage. E.g. events.person.* fields with PoE enabled.
    """

    model_config = ConfigDict(extra="forbid")


class FunctionCallTable(Table):
    """
    A table that returns a function call, e.g. numbers(...) or s3(...). The team_id guard is NOT added for these.
    """

    name: str
    min_args: Optional[int] = None
    max_args: Optional[int] = None


class SavedQuery(Table):
    """
    A table that returns a subquery, e.g. my_saved_query -> (SELECT * FROM some_saved_table). The team_id guard is NOT added for the overall subquery
    """

    query: str
    name: str

    # Note: redundancy for safety. This validation is used in the data model already
    def to_printed_clickhouse(self, context):
        from posthog.warehouse.models import validate_saved_query_name

        validate_saved_query_name(self.name)
        return self.name

    def to_printed_hogql(self):
        from posthog.warehouse.models import validate_saved_query_name

        validate_saved_query_name(self.name)
        return self.name
