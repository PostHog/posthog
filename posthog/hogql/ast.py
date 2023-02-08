import re
from enum import Enum
from typing import Any, List, Literal, Optional, Union

from pydantic import BaseModel, Extra

# NOTE: when you add new AST fields or nodes, add them to EverythingVisitor as well!

camel_case_pattern = re.compile(r"(?<!^)(?=[A-Z])")


class AST(BaseModel):
    class Config:
        extra = Extra.forbid

    def accept(self, visitor):
        camel_case_name = camel_case_pattern.sub("_", self.__class__.__name__).lower()
        method_name = "visit_{}".format(camel_case_name)
        visit = getattr(visitor, method_name)
        return visit(self)


class Expr(AST):
    pass


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
