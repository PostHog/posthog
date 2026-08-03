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

    def __init__(
        self,
        message: str,
        *,
        start: Optional[int] = None,
        end: Optional[int] = None,
        node: Optional["Expr"] = None,
    ):
        super().__init__(_humanize_parser_message(message), start=start, end=end, node=node)


def _humanize_parser_message(message: str) -> str:
    # cpp-json (ANTLR) and rust-py word running off the end of the query differently;
    # collapse both into a single human-readable message.
    if "mismatched input '<EOF>' expecting" in message or "unexpected token in expression: Eof" in message:
        return "Unexpected end of query. Check for a missing closing bracket, quote, or clause."
    return message


class QueryError(ExposedHogQLError):
    """The query is invalid, though correct syntactically."""

    pass


class TableAccessDeniedError(QueryError):
    """The user has no access to the table (raised by Database.get_table)."""

    # Surfaces as the error code on API responses (see posthog/api/query.py), so clients can tell a
    # denial from any other query error without matching on the message.
    code_name = "table_access_denied"

    table_name: str

    def __init__(self, table_name: str):
        super().__init__(f"You don't have access to table `{table_name}`.")
        self.table_name = table_name


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
