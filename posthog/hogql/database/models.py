from dataclasses import dataclass, field
from typing import Any, Optional, TYPE_CHECKING
from collections.abc import Callable
from pydantic import ConfigDict, BaseModel

from posthog.hogql.base import Expr
from posthog.hogql.errors import ResolutionError, NotImplementedError

if TYPE_CHECKING:
    from posthog.hogql.context import HogQLContext
    from posthog.hogql.ast import SelectQuery, LazyJoinType
    from posthog.hogql.base import ConstantType


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
    hidden: bool = False

    def is_nullable(self) -> bool:
        return not not self.nullable

    def get_constant_type(self) -> "ConstantType":
        from posthog.hogql.ast import UnknownType

        return UnknownType()


class IntegerDatabaseField(DatabaseField):
    def get_constant_type(self) -> "ConstantType":
        from posthog.hogql.ast import IntegerType

        return IntegerType(nullable=self.is_nullable())


class FloatDatabaseField(DatabaseField):
    def get_constant_type(self) -> "ConstantType":
        from posthog.hogql.ast import FloatType

        return FloatType(nullable=self.is_nullable())


class StringDatabaseField(DatabaseField):
    def get_constant_type(self) -> "ConstantType":
        from posthog.hogql.ast import StringType

        return StringType(nullable=self.is_nullable())


class StringJSONDatabaseField(DatabaseField):
    def get_constant_type(self) -> "ConstantType":
        from posthog.hogql.ast import StringType

        return StringType(nullable=self.is_nullable())


class StringArrayDatabaseField(DatabaseField):
    def get_constant_type(self) -> "ConstantType":
        from posthog.hogql.ast import StringType

        return StringType(nullable=self.is_nullable())


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


class ExpressionField(DatabaseField):
    expr: Expr
    # Pushes the parent table type to the scope when resolving any child fields
    isolate_scope: Optional[bool] = None


class FieldTraverser(FieldOrTable):
    model_config = ConfigDict(extra="forbid")

    chain: list[str | int]


class Table(FieldOrTable):
    fields: dict[str, FieldOrTable]
    model_config = ConfigDict(extra="forbid")

    def has_field(self, name: str | int) -> bool:
        return str(name) in self.fields

    def get_field(self, name: str | int) -> FieldOrTable:
        name = str(name)
        if self.has_field(name):
            return self.fields[name]
        raise Exception(f'Field "{name}" not found on table {self.__class__.__name__}')

    def to_printed_clickhouse(self, context: "HogQLContext") -> str:
        raise NotImplementedError("Table.to_printed_clickhouse not overridden")

    def to_printed_hogql(self) -> str:
        raise NotImplementedError("Table.to_printed_hogql not overridden")

    def avoid_asterisk_fields(self) -> list[str]:
        return []

    def get_asterisk(self):
        if isinstance(self, FunctionCallTable):
            fields_to_avoid = self.avoid_asterisk_fields()
        else:
            fields_to_avoid = [*self.avoid_asterisk_fields(), "team_id"]

        asterisk: dict[str, FieldOrTable] = {}
        for key, field_ in self.fields.items():
            if key in fields_to_avoid:
                continue
            if isinstance(field_, Table) or isinstance(field_, LazyJoin) or isinstance(field_, FieldTraverser):
                pass  # ignore virtual tables and columns for now
            elif isinstance(field_, DatabaseField):
                if not field_.hidden:  # Skip over hidden field
                    asterisk[key] = field_
            else:
                raise ResolutionError(f"Unknown field type {type(field_).__name__} for asterisk")
        return asterisk


class LazyJoin(FieldOrTable):
    model_config = ConfigDict(extra="forbid")

    join_function: Callable[["LazyJoinToAdd", "HogQLContext", "SelectQuery"], Any]
    join_table: Table | str
    from_field: list[str | int]
    to_field: Optional[list[str | int]] = None

    def resolve_table(self, context: "HogQLContext") -> Table:
        if isinstance(self.join_table, Table):
            return self.join_table

        if context.database is None:
            raise ResolutionError("Database is not set")

        return context.database.get_table(self.join_table)


class LazyTable(Table):
    """
    A table that is replaced with a subquery returned from `lazy_select(requested_fields: Dict[name, chain], modifiers: HogQLQueryModifiers, node: SelectQuery)`
    """

    model_config = ConfigDict(extra="forbid")

    def lazy_select(
        self,
        table_to_add: "LazyTableToAdd",
        context: "HogQLContext",
        node: "SelectQuery",
    ) -> Any:
        raise NotImplementedError("LazyTable.lazy_select not overridden")


@dataclass
class LazyTableToAdd:
    lazy_table: LazyTable
    fields_accessed: dict[str, list[str | int]] = field(default_factory=dict)


@dataclass
class LazyJoinToAdd:
    from_table: str
    to_table: str
    lazy_join: LazyJoin
    lazy_join_type: "LazyJoinType"
    fields_accessed: dict[str, list[str | int]] = field(default_factory=dict)


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

    id: str
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
