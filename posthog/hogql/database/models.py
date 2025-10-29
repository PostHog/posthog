import datetime
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Literal, Optional

from pydantic import BaseModel, ConfigDict

from posthog.hogql.base import Expr
from posthog.hogql.errors import NotImplementedError, ResolutionError

if TYPE_CHECKING:
    from posthog.hogql.ast import LazyJoinType, SelectQuery
    from posthog.hogql.base import ConstantType
    from posthog.hogql.context import HogQLContext


class FieldOrTable(BaseModel):
    hidden: bool = False


class DatabaseField(FieldOrTable):
    """
    Base class for a field in a database table.
    """

    model_config = ConfigDict(extra="forbid")

    name: str
    array: Optional[bool] = None
    nullable: Optional[bool] = None

    def is_nullable(self) -> bool:
        return not not self.nullable

    def get_constant_type(self) -> "ConstantType":
        from posthog.hogql.ast import UnknownType

        return UnknownType()

    def default_value(self) -> Any:
        return 0


class IntegerDatabaseField(DatabaseField):
    def get_constant_type(self) -> "ConstantType":
        from posthog.hogql.ast import IntegerType

        return IntegerType(nullable=self.is_nullable())


class FloatDatabaseField(DatabaseField):
    def get_constant_type(self) -> "ConstantType":
        from posthog.hogql.ast import FloatType

        return FloatType(nullable=self.is_nullable())


class DecimalDatabaseField(DatabaseField):
    def get_constant_type(self) -> "ConstantType":
        from posthog.hogql.ast import DecimalType

        return DecimalType(nullable=self.is_nullable())


class StringDatabaseField(DatabaseField):
    def get_constant_type(self) -> "ConstantType":
        from posthog.hogql.ast import StringType

        return StringType(nullable=self.is_nullable())

    def default_value(self) -> Any:
        return ""


class UnknownDatabaseField(DatabaseField):
    def get_constant_type(self) -> "ConstantType":
        from posthog.hogql.ast import UnknownType

        return UnknownType(nullable=self.is_nullable())


class StringJSONDatabaseField(DatabaseField):
    def get_constant_type(self) -> "ConstantType":
        from posthog.hogql.ast import StringJSONType

        return StringJSONType(nullable=self.is_nullable())

    def default_value(self) -> Any:
        return ""


class StringArrayDatabaseField(DatabaseField):
    def get_constant_type(self) -> "ConstantType":
        from posthog.hogql.ast import StringArrayType

        return StringArrayType(nullable=self.is_nullable())

    def default_value(self) -> Any:
        return ""


class FloatArrayDatabaseField(DatabaseField):
    def get_constant_type(self) -> "ConstantType":
        from posthog.hogql.ast import FloatType

        return FloatType(nullable=self.is_nullable())

    def default_value(self) -> Any:
        return ""


class DateDatabaseField(DatabaseField):
    def get_constant_type(self) -> "ConstantType":
        from posthog.hogql.ast import DateType

        return DateType(nullable=self.is_nullable())

    def default_value(self) -> Any:
        return datetime.date.fromtimestamp(0)


class DateTimeDatabaseField(DatabaseField):
    def get_constant_type(self) -> "ConstantType":
        from posthog.hogql.ast import DateTimeType

        return DateTimeType(nullable=self.is_nullable())

    def default_value(self) -> Any:
        return datetime.datetime.fromtimestamp(0)


class BooleanDatabaseField(DatabaseField):
    def get_constant_type(self) -> "ConstantType":
        from posthog.hogql.ast import BooleanType

        return BooleanType(nullable=self.is_nullable())

    def default_value(self) -> Any:
        return False


class UUIDDatabaseField(DatabaseField):
    def get_constant_type(self) -> "ConstantType":
        from posthog.hogql.ast import UUIDType

        return UUIDType(nullable=self.is_nullable())

    def default_value(self) -> Any:
        return "00000000-0000-0000-0000-000000000000"


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


class TableNode(
    BaseModel,
):
    model_config = ConfigDict(extra="forbid")

    name: Literal["root"] | str = "root"  # Default to root for ease of use
    table: FieldOrTable | None = None
    children: dict[str, "TableNode"] = {}

    def get(self) -> FieldOrTable:
        """
        Evaluates and returns the table currently associated with this node.
        Raises `ResolutionError` if the table is not set.
        """
        if self.table is None:
            raise ResolutionError(f"Table is not set at `{self.name}`")

        return self.table

    # NOTE: This only returns True if the path we pass in
    # is a valid path to a child table - not just any path.
    def has_child(self, path: list[str]) -> bool:
        if len(path) == 0:
            return self.table is not None

        first, *rest_of_path = path
        if first not in self.children:
            return False

        return self.children[first].has_child(rest_of_path)

    def get_child(self, path: list[str]) -> "TableNode":
        if len(path) == 0:
            return self

        first, *rest_of_path = path
        if first not in self.children:
            raise ResolutionError(f"Unknown child `{first}` at `{self.name}`.")

        return self.children[first].get_child(rest_of_path)

    def add_child(
        self,
        child: "TableNode",
        *,
        table_conflict_mode: Literal["override", "ignore"] = "ignore",
        children_conflict_mode: Literal["override", "merge", "ignore"] = "merge",
    ):
        # If there's a conflict, we act according to the conflict modes
        if child.name in self.children:
            if children_conflict_mode == "override":
                self.children[child.name] = child
            elif children_conflict_mode == "merge":
                self.children[child.name].merge_with(
                    child, table_conflict_mode=table_conflict_mode, children_conflict_mode=children_conflict_mode
                )
            elif children_conflict_mode == "ignore":
                pass

            return

        self.children[child.name] = child

    def merge_with(
        self,
        other: "TableNode",
        *,
        table_conflict_mode: Literal["override", "ignore"] = "ignore",
        children_conflict_mode: Literal["override", "merge", "ignore"] = "merge",
    ):
        if other.table is not None:
            if self.table is None:  # Easy case, just set it
                self.table = other.table
            else:  # We have a conflict so check conflict mode to decide what to do here
                if table_conflict_mode == "override":
                    self.table = other.table
                elif table_conflict_mode == "ignore":
                    pass

        for child in other.children.values():
            self.add_child(
                child, table_conflict_mode=table_conflict_mode, children_conflict_mode=children_conflict_mode
            )

    def resolve_all_table_names(self) -> list[str]:
        names: list[str] = []

        if self.table is not None:
            names.append(self.name)

        for child in self.children.values():
            child_names = child.resolve_all_table_names()

            # The root node should NOT include itself in the names
            if self.name == "root":
                names.extend(child_names)
            else:
                names.extend([f"{self.name}.{x}" for x in child_names])

        return names

    @staticmethod
    def create_nested_for_chain(chain: list[str], table: Table) -> "TableNode":
        assert len(chain) > 0

        # Create a deeply nested table node structure
        start: TableNode = TableNode(name=chain[0])
        current: TableNode = start
        for name in chain[1:]:
            child = TableNode(name=name)
            current.add_child(child)
            current = child

        # Add the table at the end
        current.table = table

        return start


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
    requires_args: bool = True
    min_args: Optional[int] = None
    max_args: Optional[int] = None


class DANGEROUS_NoTeamIdCheckTable(Table):
    """Don't use this other than referencing tables that contain no user data"""

    pass


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
