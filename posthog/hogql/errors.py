from typing import Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from .ast import Expr

# Base


class BaseHogQLException(Exception):
    """Base exception for HogQL. These are exposed to the user."""

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


class ExposedHogQLException(BaseHogQLException):
    """An exception that can be exposed to the user."""

    pass


class InternalHogQLException(BaseHogQLException):
    """An internal exception in the HogQL engine."""

    pass


# Specific exceptions


class SyntaxException(ExposedHogQLException):
    """The input does not conform to HogQL syntax."""

    pass


class QueryException(ExposedHogQLException):
    """The query is invalid, though correct syntactically."""

    pass


class NotImplementedException(ExposedHogQLException):
    """This feature isn't implemented in HogQL (yet)."""

    pass


class ParsingException(InternalHogQLException):
    """Parsing failed."""

    pass


class ImpossibleASTException(InternalHogQLException):
    """Parsing or resolution resulted in an impossible AST."""

    pass


class ResolutionException(InternalHogQLException):
    """Resolution of a table/field/expression failed."""

    pass
