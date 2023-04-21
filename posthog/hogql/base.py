import re
from pydantic import BaseModel, Extra
from typing import Literal, Optional

from posthog.hogql.constants import ConstantDataType
from posthog.hogql.errors import NotImplementedException

camel_case_pattern = re.compile(r"(?<!^)(?=[A-Z])")


class AST(BaseModel):
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
        from posthog.hogql.ast import UnknownType

        return UnknownType()


class ConstantType(Type):
    data_type: ConstantDataType

    def resolve_constant_type(self) -> "ConstantType":
        return self


class Expr(AST):
    type: Optional[Type]


class Macro(Expr):
    name: str
    expr: Expr
    # Whether the macro is an inlined column "WITH 1 AS a" or a subquery "WITH a AS (SELECT 1)"
    macro_format: Literal["column", "subquery"]
