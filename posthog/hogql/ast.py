from enum import Enum
from typing import Any, Dict, List, Literal, Optional, Union

from pydantic import Extra
from pydantic import Field as PydanticField

from posthog.hogql.base import Type, Expr, CTE, ConstantType, UnknownType
from posthog.hogql.constants import ConstantDataType
from posthog.hogql.database.models import (
    FieldTraverser,
    LazyJoin,
    StringJSONDatabaseField,
    Table,
    VirtualTable,
    LazyTable,
    IntegerDatabaseField,
    StringDatabaseField,
    DateTimeDatabaseField,
    BooleanDatabaseField,
    DateDatabaseField,
    FloatDatabaseField,
    FieldOrTable,
    DatabaseField,
    StringArrayDatabaseField,
)
from posthog.hogql.errors import HogQLException, NotImplementedException

# :NOTE: when you add new AST fields or nodes, add them to CloningVisitor and TraversingVisitor in visitor.py as well.
# :NOTE2: also search for ":TRICKY:" in "resolver.py" when modifying SelectQuery or JoinExpr


class FieldAliasType(Type):
    alias: str
    type: Type

    def get_child(self, name: str) -> Type:
        return self.type.get_child(name)

    def has_child(self, name: str) -> bool:
        return self.type.has_child(name)


class BaseTableType(Type):
    def resolve_database_table(self) -> Table:
        raise NotImplementedException("BaseTableType.resolve_database_table not overridden")

    def has_child(self, name: str) -> bool:
        return self.resolve_database_table().has_field(name)

    def get_child(self, name: str) -> Type:
        if name == "*":
            return AsteriskType(table_type=self)
        if self.has_child(name):
            field = self.resolve_database_table().get_field(name)
            if isinstance(field, LazyJoin):
                return LazyJoinType(table_type=self, field=name, lazy_join=field)
            if isinstance(field, LazyTable):
                return LazyTableType(table=field)
            if isinstance(field, FieldTraverser):
                return FieldTraverserType(table_type=self, chain=field.chain)
            if isinstance(field, VirtualTable):
                return VirtualTableType(table_type=self, field=name, virtual_table=field)
            return FieldType(name=name, table_type=self)
        raise HogQLException(f"Field not found: {name}")


class TableType(BaseTableType):
    table: Table

    def resolve_database_table(self) -> Table:
        return self.table


class TableAliasType(BaseTableType):
    alias: str
    table_type: TableType

    def resolve_database_table(self) -> Table:
        return self.table_type.table


class LazyJoinType(BaseTableType):
    table_type: BaseTableType
    field: str
    lazy_join: LazyJoin

    def resolve_database_table(self) -> Table:
        return self.lazy_join.join_table


class LazyTableType(BaseTableType):
    table: LazyTable

    def resolve_database_table(self) -> Table:
        return self.table


class VirtualTableType(BaseTableType):
    table_type: BaseTableType
    field: str
    virtual_table: VirtualTable

    def resolve_database_table(self) -> Table:
        return self.virtual_table

    def has_child(self, name: str) -> bool:
        return self.virtual_table.has_field(name)


TableOrSelectType = Union[BaseTableType, "SelectUnionQueryType", "SelectQueryType", "SelectQueryAliasType"]


class SelectQueryType(Type):
    """Type and new enclosed scope for a select query. Contains information about all tables and columns in the query."""

    # all aliases a select query has access to in its scope
    aliases: Dict[str, FieldAliasType] = PydanticField(default_factory=dict)
    # all types a select query exports
    columns: Dict[str, Type] = PydanticField(default_factory=dict)
    # all from and join, tables and subqueries with aliases
    tables: Dict[str, TableOrSelectType] = PydanticField(default_factory=dict)
    ctes: Dict[str, CTE] = PydanticField(default_factory=dict)
    # all from and join subqueries without aliases
    anonymous_tables: List[Union["SelectQueryType", "SelectUnionQueryType"]] = PydanticField(default_factory=list)
    # the parent select query, if this is a lambda
    parent: Optional[Union["SelectQueryType", "SelectUnionQueryType"]] = None

    def get_alias_for_table_type(self, table_type: TableOrSelectType) -> Optional[str]:
        for key, value in self.tables.items():
            if value == table_type:
                return key
        return None

    def get_child(self, name: str) -> Type:
        if name == "*":
            return AsteriskType(table_type=self)
        if name in self.columns:
            return FieldType(name=name, table_type=self)
        raise HogQLException(f"Column not found: {name}")

    def has_child(self, name: str) -> bool:
        return name in self.columns


class SelectUnionQueryType(Type):
    types: List[SelectQueryType]

    def get_alias_for_table_type(self, table_type: TableOrSelectType) -> Optional[str]:
        return self.types[0].get_alias_for_table_type(table_type)

    def get_child(self, name: str) -> Type:
        return self.types[0].get_child(name)

    def has_child(self, name: str) -> bool:
        return self.types[0].has_child(name)


class SelectQueryAliasType(Type):
    alias: str
    select_query_type: SelectQueryType | SelectUnionQueryType

    def get_child(self, name: str) -> Type:
        if name == "*":
            return AsteriskType(table_type=self)
        if self.select_query_type.has_child(name):
            return FieldType(name=name, table_type=self)
        raise HogQLException(f"Field {name} not found on query with alias {self.alias}")

    def has_child(self, name: str) -> bool:
        return self.select_query_type.has_child(name)


SelectQueryType.update_forward_refs(SelectQueryAliasType=SelectQueryAliasType)


class IntegerType(ConstantType):
    data_type: ConstantDataType = PydanticField("int", const=True)

    def print_type(self) -> str:
        return "Integer"


class FloatType(ConstantType):
    data_type: ConstantDataType = PydanticField("float", const=True)

    def print_type(self) -> str:
        return "Float"


class StringType(ConstantType):
    data_type: ConstantDataType = PydanticField("str", const=True)

    def print_type(self) -> str:
        return "String"


class BooleanType(ConstantType):
    data_type: ConstantDataType = PydanticField("bool", const=True)

    def print_type(self) -> str:
        return "Boolean"


class DateType(ConstantType):
    data_type: ConstantDataType = PydanticField("date", const=True)

    def print_type(self) -> str:
        return "Date"


class DateTimeType(ConstantType):
    data_type: ConstantDataType = PydanticField("datetime", const=True)

    def print_type(self) -> str:
        return "DateTime"


class UUIDType(ConstantType):
    data_type: ConstantDataType = PydanticField("uuid", const=True)

    def print_type(self) -> str:
        return "UUID"


class ArrayType(ConstantType):
    data_type: ConstantDataType = PydanticField("array", const=True)
    item_type: ConstantType

    def print_type(self) -> str:
        return "Array"


class TupleType(ConstantType):
    data_type: ConstantDataType = PydanticField("tuple", const=True)
    item_types: List[ConstantType]

    def print_type(self) -> str:
        return "Tuple"


class CallType(Type):
    name: str
    arg_types: List[ConstantType]
    param_types: Optional[List[ConstantType]] = None
    return_type: ConstantType

    def resolve_constant_type(self) -> ConstantType:
        return self.return_type


class AsteriskType(Type):
    table_type: TableOrSelectType


class FieldTraverserType(Type):
    chain: List[str | int]
    table_type: TableOrSelectType


class FieldType(Type):
    name: str
    table_type: TableOrSelectType

    def resolve_database_field(self) -> Optional[FieldOrTable]:
        if isinstance(self.table_type, BaseTableType):
            table = self.table_type.resolve_database_table()
            if table is not None:
                return table.get_field(self.name)
        return None

    def is_nullable(self) -> bool:
        database_field = self.resolve_database_field()
        if isinstance(database_field, DatabaseField):
            return database_field.nullable
        return True

    def resolve_constant_type(self) -> ConstantType:
        database_field = self.resolve_database_field()
        if isinstance(database_field, IntegerDatabaseField):
            return IntegerType()
        elif isinstance(database_field, FloatDatabaseField):
            return FloatType()
        elif isinstance(database_field, StringDatabaseField):
            return StringType()
        elif isinstance(database_field, BooleanDatabaseField):
            return BooleanType()
        elif isinstance(database_field, DateTimeDatabaseField):
            return DateTimeType()
        elif isinstance(database_field, DateDatabaseField):
            return DateType()
        return UnknownType()

    def get_child(self, name: str | int) -> Type:
        database_field = self.resolve_database_field()
        if database_field is None:
            raise HogQLException(f'Can not access property "{name}" on field "{self.name}".')
        if isinstance(database_field, StringJSONDatabaseField):
            return PropertyType(chain=[name], field_type=self)
        if isinstance(database_field, StringArrayDatabaseField):
            return FieldType(chain=[name], field_type=self)
        raise HogQLException(
            f'Can not access property "{name}" on field "{self.name}" of type: {type(database_field).__name__}'
        )


class PropertyType(Type):
    chain: List[str | int]
    field_type: FieldType

    # The property has been moved into a field we query from a joined subquery
    joined_subquery: Optional[SelectQueryAliasType]
    joined_subquery_field_name: Optional[str]

    def get_child(self, name: str | int) -> "Type":
        return PropertyType(chain=self.chain + [name], field_type=self.field_type)

    def has_child(self, name: str | int) -> bool:
        return True

    class Config:
        # Without this, pydantic converts all integers in "chain" into strings, breaking array access
        smart_union = True


class LambdaArgumentType(Type):
    name: str


class Alias(Expr):
    alias: str
    expr: Expr


class ArithmeticOperationOp(str, Enum):
    Add = "+"
    Sub = "-"
    Mult = "*"
    Div = "/"
    Mod = "%"


class ArithmeticOperation(Expr):
    left: Expr
    right: Expr
    op: ArithmeticOperationOp


class And(Expr):
    class Config:
        extra = Extra.forbid

    type: Optional[ConstantType]
    exprs: List[Expr]


class Or(Expr):
    class Config:
        extra = Extra.forbid

    type: Optional[ConstantType]
    exprs: List[Expr]


class CompareOperationOp(str, Enum):
    Eq = "=="
    NotEq = "!="
    Gt = ">"
    GtEq = ">="
    Lt = "<"
    LtEq = "<="
    Like = "like"
    ILike = "ilike"
    NotLike = "not like"
    NotILike = "not ilike"
    In = "in"
    NotIn = "not in"
    InCohort = "in cohort"
    NotInCohort = "not in cohort"
    Regex = "=~"
    IRegex = "=~*"
    NotRegex = "!~"
    NotIRegex = "!~*"


class CompareOperation(Expr):
    left: Expr
    right: Expr
    op: CompareOperationOp
    type: Optional[ConstantType]


class Not(Expr):
    expr: Expr
    type: Optional[ConstantType]


class OrderExpr(Expr):
    expr: Expr
    order: Literal["ASC", "DESC"] = "ASC"


class ArrayAccess(Expr):
    array: Expr
    property: Expr


class Array(Expr):
    exprs: List[Expr]


class TupleAccess(Expr):
    tuple: Expr
    index: int


class Tuple(Expr):
    exprs: List[Expr]


class Lambda(Expr):
    args: List[str]
    expr: Expr


class Constant(Expr):
    value: Any


class Field(Expr):
    chain: List[str | int]


class Placeholder(Expr):
    field: str


class Call(Expr):
    name: str
    """Function name"""
    args: List[Expr]
    params: Optional[List[Expr]] = None
    """
    Parameters apply to some aggregate functions, see ClickHouse docs:
    https://clickhouse.com/docs/en/sql-reference/aggregate-functions/parametric-functions
    """
    distinct: bool = False


class JoinConstraint(Expr):
    expr: Expr


class JoinExpr(Expr):
    # :TRICKY: When adding new fields, make sure they're handled in visitor.py and resolver.py
    type: Optional[TableOrSelectType]

    join_type: Optional[str] = None
    table: Optional[Union["SelectQuery", "SelectUnionQuery", Field]] = None
    alias: Optional[str] = None
    table_final: Optional[bool] = None
    constraint: Optional["JoinConstraint"] = None
    next_join: Optional["JoinExpr"] = None
    sample: Optional["SampleExpr"] = None


class WindowFrameExpr(Expr):
    frame_type: Optional[Literal["CURRENT ROW", "PRECEDING", "FOLLOWING"]] = None
    frame_value: Optional[int] = None


class WindowExpr(Expr):
    partition_by: Optional[List[Expr]] = None
    order_by: Optional[List[OrderExpr]] = None
    frame_method: Optional[Literal["ROWS", "RANGE"]] = None
    frame_start: Optional[WindowFrameExpr] = None
    frame_end: Optional[WindowFrameExpr] = None


class WindowFunction(Expr):
    name: str
    args: Optional[List[Expr]] = None
    over_expr: Optional[WindowExpr] = None
    over_identifier: Optional[str] = None


class SelectQuery(Expr):
    # :TRICKY: When adding new fields, make sure they're handled in visitor.py and resolver.py
    type: Optional[SelectQueryType] = None
    ctes: Optional[Dict[str, CTE]] = None
    select: List[Expr]
    distinct: Optional[bool] = None
    select_from: Optional[JoinExpr] = None
    window_exprs: Optional[Dict[str, WindowExpr]] = None
    where: Optional[Expr] = None
    prewhere: Optional[Expr] = None
    having: Optional[Expr] = None
    group_by: Optional[List[Expr]] = None
    order_by: Optional[List[OrderExpr]] = None
    limit: Optional[Expr] = None
    limit_by: Optional[List[Expr]] = None
    limit_with_ties: Optional[bool] = None
    offset: Optional[Expr] = None


class SelectUnionQuery(Expr):
    type: Optional[SelectUnionQueryType] = None
    select_queries: List[SelectQuery]


class RatioExpr(Expr):
    left: Constant
    right: Optional[Constant] = None


class SampleExpr(Expr):
    # k or n
    sample_value: RatioExpr
    offset_value: Optional[RatioExpr]


JoinExpr.update_forward_refs(SampleExpr=SampleExpr)
JoinExpr.update_forward_refs(SelectUnionQuery=SelectUnionQuery)
JoinExpr.update_forward_refs(SelectQuery=SelectQuery)
