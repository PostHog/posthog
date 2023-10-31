from typing import Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from .ast import Expr


class HogQLException(Exception):
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


class SyntaxException(HogQLException):
    """The input does not conform to HogQL syntax."""

    pass


class QueryException(HogQLException):
    """The query invalid (though correct syntactically)."""

    pass


class NotImplementedException(HogQLException):
    """This feature isn't implemented in HogQL (yet)."""

    pass


class ParsingException(HogQLException):
    """An internal problem in the parser layer."""

    pass


class ResolverException(HogQLException):
    """An internal problem in the resolver layer."""

    pass
