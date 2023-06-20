import re
from pydantic import BaseModel, Extra
from typing import Literal, Optional

from posthog.hogql.constants import ConstantDataType
from posthog.hogql.errors import NotImplementedException
from pydantic import Field as PydanticField


# Given a string like "CorrectHorseBS", match the "H" and "B", so that we can convert this to "correct_horse_bs"
camel_case_pattern = re.compile(r"(?<!^)(?<![A-Z])(?=[A-Z])")


class AST(BaseModel):
    start: Optional[int] = None
    end: Optional[int] = None

    class Config:
        extra = Extra.forbid

    def accept(self, visitor):
        camel_case_name = camel_case_pattern.sub("_", self.__class__.__name__).lower()
        method_name = f"visit_{camel_case_name}"
        if hasattr(visitor, method_name):
            visit = getattr(visitor, method_name)
            return visit(self)
        if hasattr(visitor, "visit_unknown"):
            return visitor.visit_unknown(self)
        raise NotImplementedException(f"Visitor has no method {method_name}")


class Type(AST):
    def get_child(self, name: str) -> "Type":
        raise NotImplementedException("Type.get_child not overridden")

    def has_child(self, name: str) -> bool:
        return self.get_child(name) is not None

    def resolve_constant_type(self) -> Optional["ConstantType"]:
        return UnknownType()


class Expr(AST):
    type: Optional[Type] = None


class CTE(Expr):
    """A common table expression."""

    name: str
    expr: Expr
    # Whether the CTE is an inlined column "WITH 1 AS a" or a subquery "WITH a AS (SELECT 1)"
    cte_type: Literal["column", "subquery"]


class ConstantType(Type):
    data_type: ConstantDataType

    def resolve_constant_type(self) -> "ConstantType":
        return self


class UnknownType(ConstantType):
    data_type: ConstantDataType = PydanticField("unknown", const=True)
