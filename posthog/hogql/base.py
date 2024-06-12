import re
from dataclasses import dataclass, field

from typing import TYPE_CHECKING, Literal, Optional

from posthog.hogql.constants import ConstantDataType
from posthog.hogql.errors import NotImplementedError

if TYPE_CHECKING:
    from posthog.hogql.context import HogQLContext

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
        raise NotImplementedError(f"{visitor.__class__.__name__} has no method {method_name}")


@dataclass(kw_only=True)
class Type(AST):
    def get_child(self, name: str, context: "HogQLContext") -> "Type":
        raise NotImplementedError("Type.get_child not overridden")

    def has_child(self, name: str, context: "HogQLContext") -> bool:
        return self.get_child(name, context) is not None

    def resolve_constant_type(self, context: "HogQLContext") -> "ConstantType":
        raise NotImplementedError(f"{self.__class__.__name__}.resolve_constant_type not overridden")

    def resolve_column_constant_type(self, name: str, context: "HogQLContext") -> "ConstantType":
        raise NotImplementedError(f"{self.__class__.__name__}.resolve_column_constant_type not overridden")


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
    nullable: bool = field(default=True)

    def resolve_constant_type(self, context: "HogQLContext") -> "ConstantType":
        return self

    def print_type(self) -> str:
        raise NotImplementedError("ConstantType.print_type not implemented")


@dataclass(kw_only=True)
class UnknownType(ConstantType):
    data_type: ConstantDataType = field(default="unknown", init=False)

    def print_type(self) -> str:
        return "Unknown"
