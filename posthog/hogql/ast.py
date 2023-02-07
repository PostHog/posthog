from __future__ import annotations

from enum import Enum
from typing import Any, List, Literal, Optional, Union, cast

from pydantic import BaseModel, Extra


class AST(BaseModel):
    class Config:
        extra = Extra.forbid

    def children(self) -> List[AST]:
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


class JoinExpr(Expr):
    table: Optional[Union["SelectQuery", Field]] = None
    table_final: Optional[bool] = None
    alias: Optional[str] = None
    join_type: Optional[str] = None
    join_constraint: Optional[Expr] = None
    join_expr: Optional["JoinExpr"] = None

    def children(self) -> List[AST]:
        return (
            cast(List[AST], [self.table] if self.table else [])
            + cast(List[AST], [self.join_constraint] if self.join_expr else [])
            + cast(List[AST], [self.join_expr] if self.join_expr else [])
        )


class SelectQuery(Expr):
    select: List[Expr]
    select_from: Optional[JoinExpr] = None
    where: Optional[Expr] = None
    prewhere: Optional[Expr] = None
    having: Optional[Expr] = None
    group_by: Optional[List[Expr]] = None
    order_by: Optional[List[OrderExpr]] = None
    limit: Optional[int] = None
    offset: Optional[int] = None
    distinct: Optional[bool] = None

    def children(self) -> List[AST]:
        return (
            cast(List[AST], self.select)
            + cast(List[AST], [self.select_from] if self.select_from else [])
            + cast(List[AST], [self.where] if self.where else [])
            + cast(List[AST], [self.prewhere] if self.prewhere else [])
            + cast(List[AST], [self.having] if self.having else [])
            + cast(List[AST], self.group_by or [])
            + cast(List[AST], self.order_by or [])
        )


JoinExpr.update_forward_refs(SelectQuery=SelectQuery)
JoinExpr.update_forward_refs(JoinExpr=JoinExpr)
