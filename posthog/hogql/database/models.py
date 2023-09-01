from typing import Any, Callable, Dict, List, Optional, TYPE_CHECKING
from pydantic import BaseModel, Extra

from posthog.hogql.errors import HogQLException, NotImplementedException

if TYPE_CHECKING:
    from posthog.hogql.context import HogQLContext
    from posthog.hogql.base import ConstantType


class FieldOrTable(BaseModel):
    pass


class DatabaseField(FieldOrTable):
    """
    Base class for a field in a database table.
    """

    class Config:
        extra = Extra.forbid

    name: str
    array: Optional[bool] = None
    nullable: Optional[bool] = None

    def is_nullable(self) -> bool:
        return not not self.nullable

    def get_constant_type(self) -> "ConstantType":
        from posthog.hogql.ast import UnknownType

        return UnknownType(nullable=self.is_nullable())


class IntegerDatabaseField(DatabaseField):
    def get_constant_type(self) -> "ConstantType":
        from posthog.hogql.ast import FloatType

        return FloatType(nullable=self.is_nullable())


class FloatDatabaseField(DatabaseField):
    def get_constant_type(self) -> "ConstantType":
        from posthog.hogql.ast import IntegerType

        return IntegerType(nullable=self.is_nullable())


class StringDatabaseField(DatabaseField):
    def get_constant_type(self) -> "ConstantType":
        from posthog.hogql.ast import StringType

        return StringType(nullable=self.is_nullable())


class StringJSONDatabaseField(DatabaseField):
    pass


class StringArrayDatabaseField(DatabaseField):
    pass


class DateDatabaseField(DatabaseField):
    def get_constant_type(self) -> "ConstantType":
        from posthog.hogql.ast import DateType

        return DateType(nullable=self.is_nullable())


class DateTimeDatabaseField(DatabaseField):
    def get_constant_type(self) -> "ConstantType":
        from posthog.hogql.ast import DateTimeType

        return DateTimeType(nullable=self.is_nullable())


class BooleanDatabaseField(DatabaseField):
    def get_constant_type(self) -> "ConstantType":
        from posthog.hogql.ast import BooleanType

        return BooleanType(nullable=self.is_nullable())


class FieldTraverser(FieldOrTable):
    class Config:
        extra = Extra.forbid

    chain: List[str]


class Table(FieldOrTable):
    fields: Dict[str, FieldOrTable]

    class Config:
        extra = Extra.forbid

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
            if isinstance(field, DatabaseField):
                asterisk[key] = field
            elif isinstance(field, Table) or isinstance(field, LazyJoin) or isinstance(field, FieldTraverser):
                pass  # ignore virtual tables for now
            else:
                raise HogQLException(f"Unknown field type {type(field).__name__} for asterisk")
        return asterisk


class LazyJoin(FieldOrTable):
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
