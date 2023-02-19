import re
from enum import Enum
from typing import Any, Dict, List, Literal, Optional, Union

from pydantic import BaseModel, Extra
from pydantic import Field as PydanticField

from posthog.hogql.database import DatabaseField, JoinedTable, StringJSONDatabaseField, Table

# NOTE: when you add new AST fields or nodes, add them to the Visitor classes in visitor.py as well!

camel_case_pattern = re.compile(r"(?<!^)(?=[A-Z])")


class AST(BaseModel):
    class Config:
        extra = Extra.forbid

    def accept(self, visitor):
        camel_case_name = camel_case_pattern.sub("_", self.__class__.__name__).lower()
        method_name = "visit_{}".format(camel_case_name)
        if hasattr(visitor, method_name):
            visit = getattr(visitor, method_name)
            return visit(self)
        if hasattr(visitor, "visit_unknown"):
            return visitor.visit_unknown(self)
        raise ValueError(f"Visitor has no method {method_name}")


class Symbol(AST):
    def get_child(self, name: str) -> "Symbol":
        raise NotImplementedError("Symbol.get_child not overridden")

    def has_child(self, name: str) -> bool:
        return self.get_child(name) is not None


class FieldAliasSymbol(Symbol):
    name: str
    symbol: Symbol

    def get_child(self, name: str) -> Symbol:
        return self.symbol.get_child(name)

    def has_child(self, name: str) -> bool:
        return self.symbol.has_child(name)


class TableSymbol(Symbol):
    table: Table

    def has_child(self, name: str) -> bool:
        return self.table.has_field(name)

    def get_child(self, name: str) -> Symbol:
        if name == "*":
            return SplashSymbol(table=self)
        if self.has_child(name):
            field = self.table.get_field(name)
            if isinstance(field, JoinedTable):
                return LazyTableSymbol(table=self, field=name, joined_table=field)
            return FieldSymbol(name=name, table=self)
        raise ValueError(f"Field not found: {name}")


class TableAliasSymbol(Symbol):
    name: str
    table: TableSymbol

    def has_child(self, name: str) -> bool:
        return self.table.has_child(name)

    def get_child(self, name: str) -> Symbol:
        if name == "*":
            return SplashSymbol(table=self)
        if self.has_child(name):
            table: Union[TableSymbol, TableAliasSymbol] = self
            while isinstance(table, TableAliasSymbol):
                table = table.table
            field = table.table.get_field(name)

            if isinstance(field, JoinedTable):
                return LazyTableSymbol(table=self, field=name, joined_table=field)
            return FieldSymbol(name=name, table=self)
        raise ValueError(f"Field not found: {name}")


class LazyTableSymbol(Symbol):
    table: Union[TableSymbol, TableAliasSymbol, "LazyTableSymbol"]
    field: str
    joined_table: JoinedTable

    def has_child(self, name: str) -> bool:
        return self.joined_table.table.has_field(name)

    def get_child(self, name: str) -> Symbol:
        if name == "*":
            return SplashSymbol(table=self)
        if self.has_child(name):
            field = self.joined_table.table.get_field(name)
            if isinstance(field, JoinedTable):
                return LazyTableSymbol(table=self, field=name, joined_table=field)
            return FieldSymbol(name=name, table=self)
        raise ValueError(f"Field not found: {name}")


class SelectQuerySymbol(Symbol):
    # all aliases a select query has access to in its scope
    aliases: Dict[str, FieldAliasSymbol] = PydanticField(default_factory=dict)
    # all symbols a select query exports
    columns: Dict[str, Symbol] = PydanticField(default_factory=dict)
    # all from and join, tables and subqueries with aliases
    tables: Dict[
        str, Union[TableSymbol, TableAliasSymbol, LazyTableSymbol, "SelectQuerySymbol", "SelectQueryAliasSymbol"]
    ] = PydanticField(default_factory=dict)
    # all from and join subqueries without aliases
    anonymous_tables: List["SelectQuerySymbol"] = PydanticField(default_factory=list)

    def key_for_table(
        self,
        table: Union[TableSymbol, TableAliasSymbol, LazyTableSymbol, "SelectQuerySymbol", "SelectQueryAliasSymbol"],
    ) -> Optional[str]:
        for key, value in self.tables.items():
            if value == table:
                return key
        return None

    def get_child(self, name: str) -> Symbol:
        if name in self.columns:
            return FieldSymbol(name=name, table=self)
        raise ValueError(f"Column not found: {name}")

    def has_child(self, name: str) -> bool:
        return name in self.columns


class SelectQueryAliasSymbol(Symbol):
    name: str
    symbol: SelectQuerySymbol

    def get_child(self, name: str) -> Symbol:
        if self.symbol.has_child(name):
            return FieldSymbol(name=name, table=self)
        raise ValueError(f"Field {name} not found on query with alias {self.name}")

    def has_child(self, name: str) -> bool:
        return self.symbol.has_child(name)


SelectQuerySymbol.update_forward_refs(SelectQueryAliasSymbol=SelectQueryAliasSymbol)


class CallSymbol(Symbol):
    name: str
    args: List[Symbol]


class ConstantSymbol(Symbol):
    value: Any


class SplashSymbol(Symbol):
    table: Union[TableSymbol, TableAliasSymbol, LazyTableSymbol, SelectQuerySymbol, SelectQueryAliasSymbol]


class FieldSymbol(Symbol):
    name: str
    table: Union[TableSymbol, TableAliasSymbol, LazyTableSymbol, SelectQuerySymbol, SelectQueryAliasSymbol]

    def resolve_database_field(self) -> Optional[Union[DatabaseField, Table]]:
        table_symbol = self.table
        while isinstance(table_symbol, TableAliasSymbol):
            table_symbol = table_symbol.table
        if isinstance(table_symbol, TableSymbol):
            return table_symbol.table.get_field(self.name)
        return None

    def get_child(self, name: str) -> Symbol:
        database_field = self.resolve_database_field()
        if database_field is None:
            raise ValueError(f'Can not access property "{name}" on field "{self.name}".')
        if isinstance(database_field, JoinedTable):
            return FieldSymbol(name=name, table=LazyTableSymbol(table=self, field=name, joined_table=database_field))
        if isinstance(database_field, StringJSONDatabaseField):
            return PropertySymbol(name=name, parent=self)
        raise ValueError(
            f'Can not access property "{name}" on field "{self.name}" of type: {type(database_field).__name__}'
        )


class PropertySymbol(Symbol):
    name: str
    parent: FieldSymbol


class Expr(AST):
    symbol: Optional[Symbol]


class Alias(Expr):
    alias: str
    expr: Expr


class BinaryOperationType(str, Enum):
    Add = "+"
    Sub = "-"
    Mult = "*"
    Div = "/"
    Mod = "%"


class BinaryOperation(Expr):
    left: Expr
    right: Expr
    op: BinaryOperationType


class And(Expr):
    class Config:
        extra = Extra.forbid

    exprs: List[Expr]


class Or(Expr):
    class Config:
        extra = Extra.forbid

    exprs: List[Expr]


class CompareOperationType(str, Enum):
    Eq = "=="
    NotEq = "!="
    Gt = ">"
    GtE = ">="
    Lt = "<"
    LtE = "<="
    Like = "like"
    ILike = "ilike"
    NotLike = "not like"
    NotILike = "not ilike"
    In = "in"
    NotIn = "not in"


class CompareOperation(Expr):
    left: Expr
    right: Expr
    op: CompareOperationType


class Not(Expr):
    expr: Expr


class OrderExpr(Expr):
    expr: Expr
    order: Literal["ASC", "DESC"] = "ASC"


class Constant(Expr):
    value: Any


class Field(Expr):
    chain: List[str]


class Placeholder(Expr):
    field: str


class Call(Expr):
    name: str
    args: List[Expr]


class JoinExpr(Expr):
    join_type: Optional[str] = None
    table: Optional[Union["SelectQuery", Field]] = None
    alias: Optional[str] = None
    table_final: Optional[bool] = None
    constraint: Optional[Expr] = None
    next_join: Optional["JoinExpr"] = None


class SelectQuery(Expr):
    symbol: Optional[SelectQuerySymbol] = None

    select: List[Expr]
    distinct: Optional[bool] = None
    select_from: Optional[JoinExpr] = None
    where: Optional[Expr] = None
    prewhere: Optional[Expr] = None
    having: Optional[Expr] = None
    group_by: Optional[List[Expr]] = None
    order_by: Optional[List[OrderExpr]] = None
    limit: Optional[Expr] = None
    limit_by: Optional[List[Expr]] = None
    limit_with_ties: Optional[bool] = None
    offset: Optional[Expr] = None


JoinExpr.update_forward_refs(SelectQuery=SelectQuery)
JoinExpr.update_forward_refs(JoinExpr=JoinExpr)
