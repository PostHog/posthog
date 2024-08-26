from enum import StrEnum
from typing import Any, Literal, Optional, Union
from dataclasses import dataclass, field

from posthog.hogql.base import Type, Expr, CTE, ConstantType, UnknownType, AST
from posthog.hogql.constants import ConstantDataType, HogQLQuerySettings
from posthog.hogql.context import HogQLContext
from posthog.hogql.database.models import (
    FieldTraverser,
    LazyJoin,
    StringJSONDatabaseField,
    Table,
    VirtualTable,
    LazyTable,
    FieldOrTable,
    DatabaseField,
    StringArrayDatabaseField,
    ExpressionField,
)
from posthog.hogql.errors import NotImplementedError, QueryError, ResolutionError

# :NOTE: when you add new AST fields or nodes, add them to CloningVisitor and TraversingVisitor in visitor.py as well.
# :NOTE2: also search for ":TRICKY:" in "resolver.py" when modifying SelectQuery or JoinExpr


@dataclass(kw_only=True)
class Declaration(AST):
    pass


@dataclass(kw_only=True)
class VariableAssignment(Declaration):
    left: Expr
    right: Expr


@dataclass(kw_only=True)
class VariableDeclaration(Declaration):
    name: str
    expr: Optional[Expr] = None


@dataclass(kw_only=True)
class Statement(Declaration):
    pass


@dataclass(kw_only=True)
class ExprStatement(Statement):
    expr: Optional[Expr]


@dataclass(kw_only=True)
class ReturnStatement(Statement):
    expr: Optional[Expr]


@dataclass(kw_only=True)
class ThrowStatement(Statement):
    expr: Expr


@dataclass(kw_only=True)
class TryCatchStatement(Statement):
    try_stmt: Statement
    # var name (e), error type (RetryError), stmt ({})  # (e: RetryError) {}
    catches: list[tuple[Optional[str], Optional[str], Statement]]
    finally_stmt: Optional[Statement] = None


@dataclass(kw_only=True)
class IfStatement(Statement):
    expr: Expr
    then: Statement
    else_: Optional[Statement] = None


@dataclass(kw_only=True)
class WhileStatement(Statement):
    expr: Expr
    body: Statement


@dataclass(kw_only=True)
class ForStatement(Statement):
    initializer: Optional[VariableDeclaration | VariableAssignment | Expr]
    condition: Optional[Expr]
    increment: Optional[Expr]
    body: Statement


@dataclass(kw_only=True)
class ForInStatement(Statement):
    keyVar: Optional[str]
    valueVar: str
    expr: Expr
    body: Statement


@dataclass(kw_only=True)
class Function(Statement):
    name: str
    params: list[str]
    body: Statement


@dataclass(kw_only=True)
class Block(Statement):
    declarations: list[Declaration]


@dataclass(kw_only=True)
class Program(AST):
    declarations: list[Declaration]


@dataclass(kw_only=True)
class FieldAliasType(Type):
    alias: str
    type: Type

    def get_child(self, name: str, context: HogQLContext) -> Type:
        return self.type.get_child(name, context)

    def has_child(self, name: str, context: HogQLContext) -> bool:
        return self.type.has_child(name, context)

    def resolve_constant_type(self, context: HogQLContext) -> "ConstantType":
        return self.type.resolve_constant_type(context)

    def resolve_database_field(self, context: HogQLContext):
        if isinstance(self.type, FieldType):
            return self.type.resolve_database_field(context)
        if isinstance(self.type, PropertyType):
            return self.type.field_type.resolve_database_field(context)
        raise NotImplementedError("FieldAliasType.resolve_database_field not implemented")

    def resolve_table_type(self, context: HogQLContext):
        if isinstance(self.type, FieldType):
            return self.type.table_type
        if isinstance(self.type, PropertyType):
            return self.type.field_type.table_type
        raise NotImplementedError("FieldAliasType.resolve_table_type not implemented")


@dataclass(kw_only=True)
class BaseTableType(Type):
    def resolve_database_table(self, context: HogQLContext) -> Table:
        raise NotImplementedError("BaseTableType.resolve_database_table not overridden")

    def has_child(self, name: str, context: HogQLContext) -> bool:
        return self.resolve_database_table(context).has_field(name)

    def get_child(self, name: str, context: HogQLContext) -> Type:
        if name == "*":
            return AsteriskType(table_type=self)
        if self.has_child(name, context):
            field = self.resolve_database_table(context).get_field(name)
            if isinstance(field, LazyJoin):
                return LazyJoinType(table_type=self, field=name, lazy_join=field)
            if isinstance(field, LazyTable):
                return LazyTableType(table=field)
            if isinstance(field, FieldTraverser):
                return FieldTraverserType(table_type=self, chain=field.chain)
            if isinstance(field, VirtualTable):
                return VirtualTableType(table_type=self, field=name, virtual_table=field)
            if isinstance(field, ExpressionField):
                return ExpressionFieldType(
                    table_type=self, name=name, expr=field.expr, isolate_scope=field.isolate_scope or False
                )
            return FieldType(name=name, table_type=self)
        raise QueryError(f"Field not found: {name}")


TableOrSelectType = Union[
    BaseTableType, "SelectUnionQueryType", "SelectQueryType", "SelectQueryAliasType", "SelectViewType"
]


@dataclass(kw_only=True)
class TableType(BaseTableType):
    table: Table

    def resolve_database_table(self, context: HogQLContext) -> Table:
        return self.table


@dataclass(kw_only=True)
class TableAliasType(BaseTableType):
    alias: str
    table_type: TableType

    def resolve_database_table(self, context: HogQLContext) -> Table:
        return self.table_type.table


@dataclass(kw_only=True)
class LazyJoinType(BaseTableType):
    table_type: TableOrSelectType
    field: str
    lazy_join: LazyJoin

    def resolve_database_table(self, context: HogQLContext) -> Table:
        return self.lazy_join.resolve_table(context)

    def resolve_constant_type(self, context: HogQLContext) -> "ConstantType":
        return self.get_child(self.field, context).resolve_constant_type(context)


@dataclass(kw_only=True)
class LazyTableType(BaseTableType):
    table: LazyTable

    def resolve_database_table(self, context: HogQLContext) -> Table:
        return self.table


@dataclass(kw_only=True)
class VirtualTableType(BaseTableType):
    table_type: TableOrSelectType
    field: str
    virtual_table: VirtualTable

    def resolve_database_table(self, context: HogQLContext) -> Table:
        return self.virtual_table

    def has_child(self, name: str, context: HogQLContext) -> bool:
        return self.virtual_table.has_field(name)

    def resolve_constant_type(self, context: HogQLContext) -> "ConstantType":
        return self.get_child(self.field, context).resolve_constant_type(context)


@dataclass(kw_only=True)
class SelectQueryType(Type):
    """Type and new enclosed scope for a select query. Contains information about all tables and columns in the query."""

    # all aliases a select query has access to in its scope
    aliases: dict[str, FieldAliasType] = field(default_factory=dict)
    # all types a select query exports
    columns: dict[str, Type] = field(default_factory=dict)
    # all from and join, tables and subqueries with aliases
    tables: dict[str, TableOrSelectType] = field(default_factory=dict)
    ctes: dict[str, CTE] = field(default_factory=dict)
    # all from and join subqueries without aliases
    anonymous_tables: list[Union["SelectQueryType", "SelectUnionQueryType"]] = field(default_factory=list)
    # the parent select query, if this is a lambda
    parent: Optional[Union["SelectQueryType", "SelectUnionQueryType"]] = None

    def get_alias_for_table_type(self, table_type: TableOrSelectType) -> Optional[str]:
        for key, value in self.tables.items():
            if value == table_type:
                return key
        return None

    def get_child(self, name: str, context: HogQLContext) -> Type:
        if name == "*":
            return AsteriskType(table_type=self)
        if name in self.columns:
            return FieldType(name=name, table_type=self)
        raise QueryError(f"Column not found: {name}")

    def has_child(self, name: str, context: HogQLContext) -> bool:
        return name in self.columns

    def resolve_column_constant_type(self, name: str, context: HogQLContext) -> "ConstantType":
        field = self.columns.get(name)
        if field is None:
            raise QueryError(f"Constant type cant be resolved: {name}")

        return field.resolve_constant_type(context)

    def resolve_constant_type(self, context: HogQLContext) -> "ConstantType":
        # Used only for resolving the constant type of a `ast.Lambda` node or `SELECT 1` query
        return UnknownType()


@dataclass(kw_only=True)
class SelectUnionQueryType(Type):
    types: list[SelectQueryType]

    def get_alias_for_table_type(self, table_type: TableOrSelectType) -> Optional[str]:
        return self.types[0].get_alias_for_table_type(table_type)

    def get_child(self, name: str, context: HogQLContext) -> Type:
        return self.types[0].get_child(name, context)

    def has_child(self, name: str, context: HogQLContext) -> bool:
        return self.types[0].has_child(name, context)

    def resolve_column_constant_type(self, name: str, context: HogQLContext) -> "ConstantType":
        return self.types[0].resolve_column_constant_type(name, context)


@dataclass(kw_only=True)
class SelectViewType(Type):
    view_name: str
    alias: str
    select_query_type: SelectQueryType | SelectUnionQueryType

    def get_child(self, name: str, context: HogQLContext) -> Type:
        if name == "*":
            return AsteriskType(table_type=self)
        if self.select_query_type.has_child(name, context):
            return FieldType(name=name, table_type=self)
        if self.view_name:
            if context.database is None:
                raise ResolutionError("Database must be set for queries with views")

            field = context.database.get_table(self.view_name).get_field(name)

            if isinstance(field, LazyJoin):
                return LazyJoinType(table_type=self, field=name, lazy_join=field)
            if isinstance(field, LazyTable):
                return LazyTableType(table=field)
            if isinstance(field, FieldTraverser):
                return FieldTraverserType(table_type=self, chain=field.chain)
            if isinstance(field, VirtualTable):
                return VirtualTableType(table_type=self, field=name, virtual_table=field)
            if isinstance(field, ExpressionField):
                return ExpressionFieldType(
                    table_type=self, name=name, expr=field.expr, isolate_scope=field.isolate_scope or False
                )
            return FieldType(name=name, table_type=self)
        raise ResolutionError(f"Field {name} not found on view query with name {self.view_name}")

    def has_child(self, name: str, context: HogQLContext) -> bool:
        if self.view_name:
            if context.database is None:
                raise ResolutionError("Database must be set for queries with views")
            try:
                context.database.get_table(self.view_name).get_field(name)
                return True
            except Exception:
                pass

        return self.select_query_type.has_child(name, context)

    def resolve_column_constant_type(self, name: str, context: HogQLContext) -> "ConstantType":
        return self.select_query_type.resolve_column_constant_type(name, context)


@dataclass(kw_only=True)
class SelectQueryAliasType(Type):
    alias: str
    select_query_type: SelectQueryType | SelectUnionQueryType

    def get_child(self, name: str, context: HogQLContext) -> Type:
        if name == "*":
            return AsteriskType(table_type=self)
        if self.select_query_type.has_child(name, context):
            return FieldType(name=name, table_type=self)

        raise ResolutionError(f"Field {name} not found on query with alias {self.alias}")

    def has_child(self, name: str, context: HogQLContext) -> bool:
        return self.select_query_type.has_child(name, context)

    def resolve_column_constant_type(self, name: str, context: HogQLContext) -> "ConstantType":
        return self.select_query_type.resolve_column_constant_type(name, context)


@dataclass(kw_only=True)
class IntegerType(ConstantType):
    data_type: ConstantDataType = field(default="int", init=False)

    def print_type(self) -> str:
        return "Integer"


@dataclass(kw_only=True)
class FloatType(ConstantType):
    data_type: ConstantDataType = field(default="float", init=False)

    def print_type(self) -> str:
        return "Float"


@dataclass(kw_only=True)
class StringType(ConstantType):
    data_type: ConstantDataType = field(default="str", init=False)

    def print_type(self) -> str:
        return "String"


@dataclass(kw_only=True)
class BooleanType(ConstantType):
    data_type: ConstantDataType = field(default="bool", init=False)

    def print_type(self) -> str:
        return "Boolean"


@dataclass(kw_only=True)
class DateType(ConstantType):
    data_type: ConstantDataType = field(default="date", init=False)

    def print_type(self) -> str:
        return "Date"


@dataclass(kw_only=True)
class DateTimeType(ConstantType):
    data_type: ConstantDataType = field(default="datetime", init=False)

    def print_type(self) -> str:
        return "DateTime"


@dataclass(kw_only=True)
class UUIDType(ConstantType):
    data_type: ConstantDataType = field(default="uuid", init=False)

    def print_type(self) -> str:
        return "UUID"


@dataclass(kw_only=True)
class ArrayType(ConstantType):
    data_type: ConstantDataType = field(default="array", init=False)
    item_type: ConstantType = field(default_factory=UnknownType)

    def print_type(self) -> str:
        return "Array"


@dataclass(kw_only=True)
class TupleType(ConstantType):
    data_type: ConstantDataType = field(default="tuple", init=False)
    item_types: list[ConstantType]
    repeat: bool = False

    def print_type(self) -> str:
        return "Tuple"


@dataclass(kw_only=True)
class CallType(Type):
    name: str
    arg_types: list[ConstantType]
    param_types: Optional[list[ConstantType]] = None
    return_type: ConstantType

    def resolve_constant_type(self, context: HogQLContext) -> ConstantType:
        return self.return_type


@dataclass(kw_only=True)
class AsteriskType(Type):
    table_type: TableOrSelectType

    def resolve_constant_type(self, context: HogQLContext) -> ConstantType:
        return UnknownType()


@dataclass(kw_only=True)
class FieldTraverserType(Type):
    chain: list[str | int]
    table_type: TableOrSelectType

    def resolve_constant_type(self, context: HogQLContext) -> ConstantType:
        return UnknownType()


@dataclass(kw_only=True)
class ExpressionFieldType(Type):
    name: str
    expr: Expr
    table_type: TableOrSelectType
    # Pushes the parent table type to the scope when resolving any child fields
    isolate_scope: bool = False

    def resolve_constant_type(self, context: "HogQLContext") -> "ConstantType":
        if self.expr.type is not None:
            return self.expr.type.resolve_constant_type(context)
        return UnknownType()


@dataclass(kw_only=True)
class FieldType(Type):
    name: str
    table_type: TableOrSelectType

    def resolve_database_field(self, context: HogQLContext) -> Optional[FieldOrTable]:
        if isinstance(self.table_type, BaseTableType):
            table = self.table_type.resolve_database_table(context)
            if table is not None:
                return table.get_field(self.name)
        return None

    def is_nullable(self, context: HogQLContext) -> bool:
        database_field = self.resolve_database_field(context)
        if isinstance(database_field, DatabaseField):
            return database_field.nullable
        return True

    def resolve_constant_type(self, context: HogQLContext) -> ConstantType:
        if not isinstance(self.table_type, BaseTableType):
            return self.table_type.resolve_column_constant_type(self.name, context)

        table: Table = self.table_type.resolve_database_table(context)

        database_field = table.get_field(self.name)
        if isinstance(database_field, DatabaseField):
            return database_field.get_constant_type()

        raise NotImplementedError(
            f"FieldType.resolve_constant_type, for BaseTableType: unknown database_field type: {str(database_field.__class__)}"
        )

    def get_child(self, name: str | int, context: HogQLContext) -> Type:
        database_field = self.resolve_database_field(context)
        if database_field is None:
            raise ResolutionError(f'Can not access property "{name}" on field "{self.name}".')
        if isinstance(database_field, StringJSONDatabaseField):
            return PropertyType(chain=[name], field_type=self)
        if isinstance(database_field, StringArrayDatabaseField):
            return PropertyType(chain=[name], field_type=self)
        raise ResolutionError(
            f'Can not access property "{name}" on field "{self.name}" of type: {type(database_field).__name__}'
        )

    def resolve_table_type(self, context: HogQLContext):
        return self.table_type


@dataclass(kw_only=True)
class UnresolvedFieldType(Type):
    name: str

    def get_child(self, name: str | int, context: HogQLContext) -> "Type":
        raise QueryError(f"Unable to resolve field: {self.name}")

    def has_child(self, name: str | int, context: HogQLContext) -> bool:
        return False

    def resolve_constant_type(self, context: HogQLContext) -> ConstantType:
        return UnknownType()


@dataclass(kw_only=True)
class PropertyType(Type):
    chain: list[str | int]
    field_type: FieldType

    # The property has been moved into a field we query from a joined subquery
    joined_subquery: Optional[SelectQueryAliasType] = field(default=None, init=False)
    joined_subquery_field_name: Optional[str] = field(default=None, init=False)

    def get_child(self, name: str | int, context: HogQLContext) -> "Type":
        return PropertyType(chain=[*self.chain, name], field_type=self.field_type)

    def has_child(self, name: str | int, context: HogQLContext) -> bool:
        return True

    def resolve_constant_type(self, context: HogQLContext) -> ConstantType:
        if self.joined_subquery is not None and self.joined_subquery_field_name is not None:
            return self.joined_subquery.resolve_column_constant_type(self.joined_subquery_field_name, context)

        return self.field_type.resolve_constant_type(context)


@dataclass(kw_only=True)
class LambdaArgumentType(Type):
    name: str

    def resolve_constant_type(self, context: HogQLContext) -> ConstantType:
        return UnknownType()


@dataclass(kw_only=True)
class Alias(Expr):
    alias: str
    expr: Expr
    """
    Aliases are "hidden" if they're automatically created by HogQL when abstracting fields.
    E.g. "events.timestamp" gets turned into a "toTimeZone(events.timestamp, 'UTC') AS timestamp".
    Hidden aliases are printed only when printing the columns of a SELECT query in the ClickHouse dialect.
    """
    hidden: bool = False


class ArithmeticOperationOp(StrEnum):
    Add = "+"
    Sub = "-"
    Mult = "*"
    Div = "/"
    Mod = "%"


@dataclass(kw_only=True)
class ArithmeticOperation(Expr):
    left: Expr
    right: Expr
    op: ArithmeticOperationOp


@dataclass(kw_only=True)
class And(Expr):
    type: Optional[ConstantType] = None
    exprs: list[Expr]


@dataclass(kw_only=True)
class Or(Expr):
    exprs: list[Expr]
    type: Optional[ConstantType] = None


class CompareOperationOp(StrEnum):
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
    GlobalIn = "global in"
    NotIn = "not in"
    GlobalNotIn = "global not in"
    InCohort = "in cohort"
    NotInCohort = "not in cohort"
    Regex = "=~"
    IRegex = "=~*"
    NotRegex = "!~"
    NotIRegex = "!~*"


@dataclass(kw_only=True)
class CompareOperation(Expr):
    left: Expr
    right: Expr
    op: CompareOperationOp
    type: Optional[ConstantType] = None


@dataclass(kw_only=True)
class Not(Expr):
    expr: Expr
    type: Optional[ConstantType] = None


@dataclass(kw_only=True)
class OrderExpr(Expr):
    expr: Expr
    order: Literal["ASC", "DESC"] = "ASC"


@dataclass(kw_only=True)
class ArrayAccess(Expr):
    array: Expr
    property: Expr
    nullish: bool = False


@dataclass(kw_only=True)
class Array(Expr):
    exprs: list[Expr]


@dataclass(kw_only=True)
class Dict(Expr):
    items: list[tuple[Expr, Expr]]


@dataclass(kw_only=True)
class TupleAccess(Expr):
    tuple: Expr
    index: int
    nullish: bool = False


@dataclass(kw_only=True)
class Tuple(Expr):
    exprs: list[Expr]


@dataclass(kw_only=True)
class Lambda(Expr):
    args: list[str]
    expr: Expr | Block


@dataclass(kw_only=True)
class Constant(Expr):
    value: Any


@dataclass(kw_only=True)
class Field(Expr):
    chain: list[str | int]


@dataclass(kw_only=True)
class Placeholder(Expr):
    chain: list[str | int]

    @property
    def field(self):
        return ".".join(str(chain) for chain in self.chain)


@dataclass(kw_only=True)
class Call(Expr):
    name: str
    """Function name"""
    args: list[Expr]
    params: Optional[list[Expr]] = None
    """
    Parameters apply to some aggregate functions, see ClickHouse docs:
    https://clickhouse.com/docs/en/sql-reference/aggregate-functions/parametric-functions
    """
    distinct: bool = False


@dataclass(kw_only=True)
class ExprCall(Expr):
    expr: Expr
    args: list[Expr]


@dataclass(kw_only=True)
class JoinConstraint(Expr):
    expr: Expr
    constraint_type: Literal["ON", "USING"]


@dataclass(kw_only=True)
class JoinExpr(Expr):
    # :TRICKY: When adding new fields, make sure they're handled in visitor.py and resolver.py
    type: Optional[TableOrSelectType] = None

    join_type: Optional[str] = None
    table: Optional[Union["SelectQuery", "SelectUnionQuery", Field]] = None
    table_args: Optional[list[Expr]] = None
    alias: Optional[str] = None
    table_final: Optional[bool] = None
    constraint: Optional["JoinConstraint"] = None
    next_join: Optional["JoinExpr"] = None
    sample: Optional["SampleExpr"] = None


@dataclass(kw_only=True)
class WindowFrameExpr(Expr):
    frame_type: Optional[Literal["CURRENT ROW", "PRECEDING", "FOLLOWING"]] = None
    frame_value: Optional[int] = None


@dataclass(kw_only=True)
class WindowExpr(Expr):
    partition_by: Optional[list[Expr]] = None
    order_by: Optional[list[OrderExpr]] = None
    frame_method: Optional[Literal["ROWS", "RANGE"]] = None
    frame_start: Optional[WindowFrameExpr] = None
    frame_end: Optional[WindowFrameExpr] = None


@dataclass(kw_only=True)
class WindowFunction(Expr):
    name: str
    args: Optional[list[Expr]] = None
    exprs: Optional[list[Expr]] = None
    over_expr: Optional[WindowExpr] = None
    over_identifier: Optional[str] = None


@dataclass(kw_only=True)
class SelectQuery(Expr):
    # :TRICKY: When adding new fields, make sure they're handled in visitor.py and resolver.py
    type: Optional[SelectQueryType] = None
    ctes: Optional[dict[str, CTE]] = None
    select: list[Expr]
    distinct: Optional[bool] = None
    select_from: Optional[JoinExpr] = None
    array_join_op: Optional[str] = None
    array_join_list: Optional[list[Expr]] = None
    window_exprs: Optional[dict[str, WindowExpr]] = None
    where: Optional[Expr] = None
    prewhere: Optional[Expr] = None
    having: Optional[Expr] = None
    group_by: Optional[list[Expr]] = None
    order_by: Optional[list[OrderExpr]] = None
    limit: Optional[Expr] = None
    limit_by: Optional[list[Expr]] = None
    limit_with_ties: Optional[bool] = None
    offset: Optional[Expr] = None
    settings: Optional[HogQLQuerySettings] = None
    view_name: Optional[str] = None


@dataclass(kw_only=True)
class SelectUnionQuery(Expr):
    type: Optional[SelectUnionQueryType] = None
    select_queries: list[SelectQuery]


@dataclass(kw_only=True)
class RatioExpr(Expr):
    left: Constant
    right: Optional[Constant] = None


@dataclass(kw_only=True)
class SampleExpr(Expr):
    # k or n
    sample_value: RatioExpr
    offset_value: Optional[RatioExpr] = None


@dataclass(kw_only=True)
class HogQLXAttribute(AST):
    name: str
    value: Any


@dataclass(kw_only=True)
class HogQLXTag(AST):
    kind: str
    attributes: list[HogQLXAttribute]

    def to_dict(self):
        return {
            "kind": self.kind,
            **{a.name: a.value for a in self.attributes},
        }
