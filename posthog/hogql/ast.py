from __future__ import annotations

from enum import Enum
from typing import Any, List, Optional

from pydantic import BaseModel, Extra


class AST(BaseModel):
    class Config:
        extra = Extra.forbid


class Expr(AST):
    pass


class Column(AST):
    expr: Expr
    alias: Optional[str] = None


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


class BooleanOperationType(str, Enum):
    And = "and"
    Or = "or"


class BooleanOperation(Expr):
    class Config:
        extra = Extra.forbid

    op: BooleanOperationType
    values: List[Expr]


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


class CompareOperation(Expr):
    left: Expr
    right: Expr
    op: CompareOperationType


class NotOperation(Expr):
    expr: Expr


class Constant(Expr):
    value: Any


class FieldAccess(Expr):
    field: str


class FieldAccessChain(Expr):
    chain: List[str]


class Call(Expr):
    name: str
    args: List[Expr]


class Select(Expr):
    columns: List[Column]
    where: Optional[Expr] = None
    prewhere: Optional[Expr] = None
    having: Optional[Expr] = None
