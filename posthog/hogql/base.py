import re
from dataclasses import dataclass, field

from typing import Literal, Optional

from posthog.hogql.constants import ConstantDataType
from posthog.hogql.errors import NotImplementedException


# Given a string like "CorrectHorseBS", match the "H" and "B", so that we can convert this to "correct_horse_bs"
camel_case_pattern = re.compile(r"(?<!^)(?<![A-Z])(?=[A-Z])")


@dataclass(kw_only=True)
class AST:
    start: Optional[int] = field(default=None)
    end: Optional[int] = field(default=None)

    # This is part of the visitor pattern from visitor.py.
    def accept(self, visitor):
        name = camel_case_pattern.sub("_", self.__class__.__name__).lower()

        # NOTE: Sync with ./test/test_visitor.py#test_hogql_visitor_naming_exceptions
        replacements = {"hog_qlxtag": "hogqlx_tag", "hog_qlxattribute": "hogqlx_attribute", "uuidtype": "uuid_type"}
        for old, new in replacements.items():
            name = name.replace(old, new)
        method_name = f"visit_{name}"
        if hasattr(visitor, method_name):
            visit = getattr(visitor, method_name)
            return visit(self)
        if hasattr(visitor, "visit_unknown"):
            return visitor.visit_unknown(self)
        raise NotImplementedException(f"Visitor has no method {method_name}")


@dataclass(kw_only=True)
class Type(AST):
    def get_child(self, name: str) -> "Type":
        raise NotImplementedException("Type.get_child not overridden")

    def has_child(self, name: str) -> bool:
        return self.get_child(name) is not None

    def resolve_constant_type(self) -> Optional["ConstantType"]:
        return UnknownType()


@dataclass(kw_only=True)
class Expr(AST):
    type: Optional[Type] = field(default=None)


@dataclass(kw_only=True)
class CTE(Expr):
    """A common table expression."""

    name: str
    expr: Expr
    # Whether the CTE is an inlined column "WITH 1 AS a" or a subquery "WITH a AS (SELECT 1)"
    cte_type: Literal["column", "subquery"]


@dataclass(kw_only=True)
class ConstantType(Type):
    data_type: ConstantDataType

    def resolve_constant_type(self) -> "ConstantType":
        return self

    def print_type(self) -> str:
        raise NotImplementedException("ConstantType.print_type not implemented")


@dataclass(kw_only=True)
class UnknownType(ConstantType):
    data_type: ConstantDataType = field(default="unknown", init=False)

    def print_type(self) -> str:
        return "Unknown"
