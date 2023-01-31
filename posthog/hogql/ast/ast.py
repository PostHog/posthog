from __future__ import annotations

from enum import Enum
from typing import Any, List, Optional

from pydantic import BaseModel, Extra


class AST(BaseModel):
    class Config:
        extra = Extra.forbid


class Expr(AST):
    pass


class Parens(Expr):
    expr: Expr


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


class BooleanOpeartion(Expr):
    class Config:
        extra = Extra.forbid

    values: List[Expr]
    op: BooleanOperationType


class CompareOperationType(str, Enum):
    Eq = "=="
    NotEq = "!="
    Gt = ">"
    GtE = ">="
    Lt = "<"
    LtE = "<="


class CompareOperation(Expr):
    left: Expr
    right: Expr
    op: CompareOperationType


class UnaryOperationType(str, Enum):
    Not = "not"
    USub = "-"


class UnaryOperation(Expr):
    op: UnaryOperationType
    operand: Expr


class Constant(Expr):
    value: Any


class Attribute(Expr):
    attr: str
    value: Expr


class Call(Expr):
    func: Expr
    args: List[Expr]


class Name(Expr):
    id: str
