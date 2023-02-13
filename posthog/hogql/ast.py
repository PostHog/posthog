import re
from enum import Enum
from typing import Any, Dict, List, Literal, Optional, Union

from pydantic import BaseModel, Extra

from posthog.hogql.database import StringJSONValue, Table

# NOTE: when you add new AST fields or nodes, add them to CloningVisitor as well!

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
        raise ValueError("Visitor has no method visit_constant")


class Symbol(AST):
    def get_child(self, name: str) -> "Symbol":
        raise NotImplementedError()

    def has_child(self, name: str) -> bool:
        return self.get_child(name) is not None


class ColumnAliasSymbol(Symbol):
    name: str
    symbol: Symbol

    def get_child(self, name: str) -> Symbol:
        return self.symbol.get_child(name)

    def has_child(self, name: str) -> bool:
        return self.symbol.has_child(name)


class TableSymbol(Symbol):
    table: Table

    def has_child(self, name: str) -> bool:
        return name in self.table.__fields__

    def get_child(self, name: str) -> Symbol:
        if self.has_child(name):
            return FieldSymbol(name=name, table=self)
        raise ValueError(f"Field not found: {name}")


class TableAliasSymbol(Symbol):
    name: str
    table: TableSymbol

    def has_child(self, name: str) -> bool:
        return self.table.has_child(name)

    def get_child(self, name: str) -> Symbol:
        if self.has_child(name):
            return FieldSymbol(name=name, table=self)
        return self.table.get_child(name)


class SelectQueryAliasSymbol(Symbol):
    name: str
    symbol: Symbol

    def get_child(self, name: str) -> Symbol:
        if self.symbol.has_child(name):
            return FieldSymbol(name=name, table=self)
        raise ValueError(f"Field not found: {name}")

    def has_child(self, name: str) -> bool:
        return self.symbol.has_child(name)


class SelectQuerySymbol(Symbol):
    # all aliases a select query has access to in its scope
    aliases: Dict[str, ColumnAliasSymbol]
    # all symbols a select query exports
    columns: Dict[str, Symbol]
    # all from and join, tables and subqueries with aliases
    tables: Dict[str, Union[TableSymbol, TableAliasSymbol, "SelectQuerySymbol", SelectQueryAliasSymbol]]
    # all from and join subqueries without aliases
    anonymous_tables: List["SelectQuerySymbol"]

    def get_child(self, name: str) -> Symbol:
        if name in self.columns:
            return FieldSymbol(name=name, table=self)
        raise ValueError(f"Column not found: {name}")

    def has_child(self, name: str) -> bool:
        return name in self.columns


SelectQuerySymbol.update_forward_refs(SelectQuerySymbol=SelectQuerySymbol)


class CallSymbol(Symbol):
    name: str
    args: List[Symbol]


class FieldSymbol(Symbol):
    name: str
    table: Union[TableSymbol, TableAliasSymbol, SelectQuerySymbol, SelectQueryAliasSymbol]

    def get_child(self, name: str) -> Symbol:
        table_symbol = self.table
        while isinstance(table_symbol, TableAliasSymbol):
            table_symbol = table_symbol.table

        if isinstance(table_symbol, TableSymbol):
            db_table = table_symbol.table
            if isinstance(db_table, Table):
                if self.name in db_table.__fields__ and isinstance(
                    db_table.__fields__[self.name].default, StringJSONValue
                ):
                    return PropertySymbol(name=name, field=self)
        raise ValueError(f"Can not access property {name} on field {self.name}.")


class ConstantSymbol(Symbol):
    value: Any


class PropertySymbol(Symbol):
    name: str
    field: FieldSymbol


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
