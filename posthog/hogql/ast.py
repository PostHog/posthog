import re
from enum import Enum
from typing import Any, List, Literal, cast

from pydantic import BaseModel, Extra

camel_case_pattern = re.compile(r"(?<!^)(?=[A-Z])")


class AST(BaseModel):
    class Config:
        extra = Extra.forbid

    def accept(self, visitor):
        camel_case_name = camel_case_pattern.sub("_", self.__class__.__name__).lower()
        method_name = "visit_{}".format(camel_case_name)
        visit = getattr(visitor, method_name)
        return visit(self)

    def children(self) -> List["AST"]:
        raise NotImplementedError("AST.children() not implemented")


class Expr(AST):
    pass


class Alias(Expr):
    alias: str
    expr: Expr

    def children(self) -> List[AST]:
        return cast(List[AST], [self.expr])


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

    def children(self) -> List[AST]:
        return cast(List[AST], [self.left, self.right])


class And(Expr):
    class Config:
        extra = Extra.forbid

    exprs: List[Expr]

    def children(self) -> List[AST]:
        return cast(List[AST], self.exprs)


class Or(Expr):
    class Config:
        extra = Extra.forbid

    exprs: List[Expr]

    def children(self) -> List[AST]:
        return cast(List[AST], self.exprs)


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

    def children(self) -> List[AST]:
        return cast(List[AST], [self.left, self.right])


class Not(Expr):
    expr: Expr

    def children(self) -> List[AST]:
        return cast(List[AST], [self.expr])


class OrderExpr(Expr):
    expr: Expr
    order: Literal["ASC", "DESC"] = "ASC"

    def children(self) -> List[AST]:
        return cast(List[AST], [self.expr])


class Constant(Expr):
    value: Any

    def children(self) -> List[AST]:
        return cast(List[AST], [])


class Field(Expr):
    chain: List[str]

    def children(self) -> List[AST]:
        return cast(List[AST], [])


class Placeholder(Expr):
    field: str

    def children(self) -> List[AST]:
        return cast(List[AST], [])


class Call(Expr):
    name: str
    args: List[Expr]

    def children(self) -> List[AST]:
        return cast(List[AST], self.args)
