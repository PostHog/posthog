from abc import ABC
from typing import TYPE_CHECKING, Optional

if TYPE_CHECKING:
    from .ast import Expr

# Base


class BaseHogQLError(Exception, ABC):
    message: str
    start: Optional[int]
    end: Optional[int]

    def __init__(
        self,
        message: str,
        *,
        start: Optional[int] = None,
        end: Optional[int] = None,
        node: Optional["Expr"] = None,
    ):
        super().__init__(message)
        if node is not None and node.start is not None and node.end is not None:
            self.start = node.start
            self.end = node.end
        else:
            self.start = start
            self.end = end


# Exposed vs. internal


class ExposedHogQLError(BaseHogQLError):
    """An exception that can be exposed to the user."""

    pass


class InternalHogQLError(BaseHogQLError):
    """An internal exception in the HogQL engine."""

    pass


# Specific exceptions


class SyntaxError(ExposedHogQLError):
    """The input does not conform to HogQL syntax."""

    pass


class QueryError(ExposedHogQLError):
    """The query is invalid, though correct syntactically."""

    pass


class NotImplementedError(InternalHogQLError):
    """This feature isn't implemented in HogQL (yet)."""

    pass


class ParsingError(InternalHogQLError):
    """Parsing failed."""

    pass


class ImpossibleASTError(InternalHogQLError):
    """Parsing or resolution resulted in an impossible AST."""

    pass


class ResolutionError(InternalHogQLError):
    """Resolution of a table/field/expression failed."""

    pass
