import re
from enum import Enum
from typing import Any, Dict, List, Literal, Optional, Union

from pydantic import BaseModel, Extra

from posthog.hogql.constants import EVENT_FIELDS

# NOTE: when you add new AST fields or nodes, add them to CloningVisitor as well!

camel_case_pattern = re.compile(r"(?<!^)(?=[A-Z])")


class AST(BaseModel):
    class Config:
        extra = Extra.forbid

    def accept(self, visitor):
        camel_case_name = camel_case_pattern.sub("_", self.__class__.__name__).lower()
        method_name = "visit_{}".format(camel_case_name)
        visit = getattr(visitor, method_name)
        return visit(self)


class Symbol(AST):
    print_name: Optional[str]

    def get_child(self, name: str) -> "Symbol":
        raise NotImplementedError()

    def has_child(self, name: str) -> bool:
        return self.get_child(name) is not None


class ColumnAliasSymbol(Symbol):
    name: str
    symbol: "Symbol"

    def get_child(self, name: str) -> "Symbol":
        return self.symbol.get_child(name)

    def has_child(self, name: str) -> bool:
        return self.symbol.has_child(name)


class TableAliasSymbol(Symbol):
    name: str
    symbol: "Symbol"

    def get_child(self, name: str) -> "Symbol":
        return self.symbol.get_child(name)

    def has_child(self, name: str) -> bool:
        return self.symbol.has_child(name)


class TableSymbol(Symbol):
    table_name: Literal["events"]

    def has_child(self, name: str) -> bool:
        if self.table_name == "events":
            return name in EVENT_FIELDS
        else:
            raise NotImplementedError(f"Can not resolve table: {self.table_name}")

    def get_child(self, name: str) -> "Symbol":
        if self.table_name == "events":
            if name in EVENT_FIELDS:
                return FieldSymbol(name=name, table=self)
            raise NotImplementedError(f"Event field not found: {name}")
        else:
            raise NotImplementedError(f"Can not resolve table: {self.table_name}")


class SelectQuerySymbol(Symbol):
    # all aliases a select query has access to in its scope
    aliases: Dict[str, Symbol]
    # all symbols a select query exports
    columns: Dict[str, Symbol]
    # all tables we join in this query on which we look for aliases
    tables: Dict[str, Symbol]

    def get_child(self, name: str) -> "Symbol":
        if name in self.columns:
            return self.columns[name]
        raise NotImplementedError(f"Column not found: {name}")

    def has_child(self, name: str) -> bool:
        return name in self.columns


class FieldSymbol(Symbol):
    name: str
    table: TableSymbol

    def get_child(self, name: str) -> "Symbol":
        if self.table.table_name == "events":
            if self.name == "properties":
                raise NotImplementedError(f"Property symbol resolution not implemented yet")
            else:
                raise NotImplementedError(f"Can not resolve field {self.name} on table events")
        else:
            raise NotImplementedError(f"Can not resolve fields on table: {self.name}")


class ConstantSymbol(Symbol):
    value: Any


class PropertySymbol(Symbol):
    name: str
    field: FieldSymbol


class Expr(AST):
    symbol: Optional[Symbol]


ColumnAliasSymbol.update_forward_refs(Expr=Expr)
TableAliasSymbol.update_forward_refs(Expr=Expr)
SelectQuerySymbol.update_forward_refs(Expr=Expr)


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
    table: Optional[Union["SelectQuery", Field]] = None
    table_final: Optional[bool] = None
    alias: Optional[str] = None
    join_type: Optional[str] = None
    join_constraint: Optional[Expr] = None
    join_expr: Optional["JoinExpr"] = None


class SelectQuery(Expr):
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
