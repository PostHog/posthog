import datetime
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Literal, Optional, cast

from pydantic import (
    BaseModel,
    ConfigDict,
    Field as PydanticField,
)

from posthog.hogql.base import Expr
from posthog.hogql.constants import HogQLQuerySettings
from posthog.hogql.errors import NotImplementedError, ResolutionError

# Import Workload at module level for Pydantic (needed at runtime)
from posthog.clickhouse.workload import Workload

if TYPE_CHECKING:
    from posthog.hogql.ast import JoinExpr, LazyJoinType, SelectQuery
    from posthog.hogql.base import ConstantType
    from posthog.hogql.context import HogQLContext


# Trim pydantic's default per-node pickle state to just __dict__ and rebuild the bookkeeping on load.
# This improves performance by 20-40%
def _slim_pickle_getstate(model: BaseModel) -> dict[Any, Any]:
    if model.__pydantic_extra__ is None and model.__pydantic_private__ is None:
        return cast("dict[Any, Any]", model.__dict__)
    return BaseModel.__getstate__(model)


def _slim_pickle_setstate(model: BaseModel, state: dict[Any, Any]) -> None:
    if "__pydantic_fields_set__" in state:  # pydantic's full state — restore verbatim
        BaseModel.__setstate__(model, state)
        return
    object.__setattr__(model, "__dict__", state)
    object.__setattr__(model, "__pydantic_fields_set__", set(state))
    object.__setattr__(model, "__pydantic_extra__", None)
    object.__setattr__(model, "__pydantic_private__", None)


class FieldOrTable(BaseModel):
    hidden: bool = False
    # Optional human/agent-facing description of this table or column. Surfaced through the
    # `system.information_schema` tables so agents can discover and disambiguate the schema.
    description: Optional[str] = None

    def __getstate__(self) -> dict[Any, Any]:
        return _slim_pickle_getstate(self)

    def __setstate__(self, state: dict[Any, Any]) -> None:
        _slim_pickle_setstate(self, state)


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


class MapStringDatabaseField(StringJSONDatabaseField):
    """A physical ClickHouse `Map(String, String)` column presented like a JSON blob.

    Behaves as JSON for resolution, lowering, and property-group routing (suffix-keyed maps such as logs
    `attributes_map_str`), but a key with no precomputed column is read via a native Map subscript instead of
    JSONExtract — which ClickHouse rejects on a Map. See `clickhouse_property_resolution._substitute_value_read`.
    """


class StructDatabaseField(DatabaseField):
    fields: dict[str, "DatabaseField"] = PydanticField(default_factory=dict)

    def get_constant_type(self) -> "ConstantType":
        from posthog.hogql.ast import TupleType

        return TupleType(
            nullable=self.is_nullable(),
            item_types=[field.get_constant_type() for field in self.fields.values()],
            field_names=list(self.fields.keys()),
        )


class StringArrayDatabaseField(DatabaseField):
    def get_constant_type(self) -> "ConstantType":
        from posthog.hogql.ast import StringArrayType

        return StringArrayType(nullable=self.is_nullable())

    def default_value(self) -> Any:
        return ""


class FloatArrayDatabaseField(DatabaseField):
    def get_constant_type(self) -> "ConstantType":
        from posthog.hogql.ast import ArrayType, FloatType

        return ArrayType(nullable=self.is_nullable(), item_type=FloatType(nullable=False))

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
    name: str | None = None
    fields: dict[str, FieldOrTable]
    top_level_settings: Optional[HogQLQuerySettings] = None
    workload: Optional[Workload] = None
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

    def get_predicates(self) -> list[Expr]:
        return []

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


class TableNode(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: Literal["root"] | str = "root"  # Default to root for ease of use
    table: FieldOrTable | None = None
    children: dict[str, "TableNode"] = {}
    # When True, the table is reachable by the resolver (so other tables can reference it
    # via subqueries) but is omitted from the SQL editor schema and autocomplete lists.
    hidden: bool = False
    # When True, this node may be reached by a case-insensitive name match (used for Snowflake,
    # which stores identifiers uppercase but resolves unquoted names case-insensitively). Only
    # opt-in nodes participate in the fallback, so ClickHouse/event tables stay exact-match.
    case_insensitive: bool = False

    def __getstate__(self) -> dict[Any, Any]:
        return _slim_pickle_getstate(self)

    def __setstate__(self, state: dict[Any, Any]) -> None:
        _slim_pickle_setstate(self, state)

    def get(self) -> FieldOrTable:
        """
        Evaluates and returns the table currently associated with this node.
        Raises `ResolutionError` if the table is not set.
        """
        if self.table is None:
            raise ResolutionError(f"Table is not set at `{self.name}`")

        return self.table

    def _match_child(self, name: str) -> Optional["TableNode"]:
        child = self.children.get(name)
        if child is not None:
            return child
        # Fall back to a case-insensitive match, but only to children that opt in — keeps
        # ClickHouse/event tables exact-match while letting Snowflake schemas/tables resolve
        # the way Snowflake itself does (unquoted identifiers fold case).
        target = name.lower()
        for key, node in self.children.items():
            if node.case_insensitive and key.lower() == target:
                return node
        return None

    # NOTE: This only returns True if the path we pass in
    # is a valid path to a child table - not just any path.
    def has_child(self, path: list[str]) -> bool:
        if len(path) == 0:
            return self.table is not None

        first, *rest_of_path = path
        child = self._match_child(first)
        if child is None:
            return False

        return child.has_child(rest_of_path)

    def get_child(self, path: list[str]) -> "TableNode":
        if len(path) == 0:
            return self

        first, *rest_of_path = path
        child = self._match_child(first)
        if child is None:
            raise ResolutionError(f"Unknown table `{first}`.")

        return child.get_child(rest_of_path)

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

    def resolve_visible_table_names(self) -> list[str]:
        """Same as `resolve_all_table_names` but skips nodes marked `hidden=True`.

        Use this for surfaces aimed at users (SQL editor schema sidebar, autocomplete,
        access-control allowlists). The resolver itself should keep using
        `resolve_all_table_names` so that hidden tables remain reachable via
        subqueries — they're just kept out of the catalog.
        """
        names: list[str] = []

        if self.table is not None and not self.hidden:
            names.append(self.name)

        for child in self.children.values():
            if child.hidden:
                continue
            child_names = child.resolve_visible_table_names()

            if self.name == "root":
                names.extend(child_names)
            else:
                names.extend([f"{self.name}.{x}" for x in child_names])

        return names

    @staticmethod
    def create_nested_for_chain(chain: list[str], table: Table, *, case_insensitive: bool = False) -> "TableNode":
        assert len(chain) > 0

        # Create a deeply nested table node structure
        start: TableNode = TableNode(name=chain[0], case_insensitive=case_insensitive)
        current: TableNode = start
        for name in chain[1:]:
            child = TableNode(name=name, case_insensitive=case_insensitive)
            current.add_child(child)
            current = child

        # Add the table at the end
        current.table = table

        return start


class LazyJoin(FieldOrTable):
    model_config = ConfigDict(extra="forbid")

    # A lazy join is described entirely as plain, serializable data: a `resolver` tag naming a
    # join recipe in the registry, plus JSON-able `resolver_params` for anything the recipe
    # needs at resolution time. Keeping the LazyJoin free of closures is what makes the whole
    # Database serializable and cacheable.
    resolver: str
    resolver_params: dict[str, Any] = PydanticField(default_factory=dict)
    join_table: Table | str
    from_field: list[str | int]
    to_field: Optional[list[str | int]] = None

    def resolve_table(self, context: "HogQLContext") -> Table:
        if isinstance(self.join_table, Table):
            return self.join_table

        if context.database is None:
            raise ResolutionError("Database is not set")

        return context.database.get_table(self.join_table)

    def resolve_join_to_add(
        self, join_to_add: "LazyJoinToAdd", context: "HogQLContext", node: "SelectQuery"
    ) -> "JoinExpr":
        from posthog.hogql.database.lazy_join_registry import get_lazy_join_resolver  # noqa: PLC0415 — circular import

        return get_lazy_join_resolver(self.resolver)(join_to_add, context, node)


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

    # Currently only storing metadata related to the managed viewset, but we can expand this in the future
    # to store any arbitrary data on this that can then be used to check what a specific saved query is about
    metadata: dict[str, Any] = {}

    # Note: redundancy for safety. This validation is used in the data model already
    def to_printed_clickhouse(self, context):
        from products.data_modeling.backend.facade.models import validate_saved_query_name

        validate_saved_query_name(self.name)
        return self.name

    def to_printed_hogql(self):
        from products.data_modeling.backend.facade.models import validate_saved_query_name

        validate_saved_query_name(self.name)
        return self.name
