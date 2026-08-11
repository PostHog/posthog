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


# Both parser backends (the antlr-based cpp parser and the hand-rolled rust parser) report
# syntax failures with terse, low-level wording, and the rust backend even Debug-prints internal
# token kinds like ``Keyword(With)``. A message starting with one of these prefixes is such a
# low-level string, safe to swap for guidance a person can act on.
HOGQL_PARSE_ERROR_PREFIXES = (
    "no viable alternative",
    "trailing tokens after expression",
    "unexpected token in expression",
    "mismatched input",
)


def humanize_hogql_parse_error(message: str) -> str:
    """Turn a low-level HogQL parser error into one a person writing SQL can act on.

    Returns the message unchanged when it isn't a known low-level parser string, so
    semantic errors (unknown table, bad function) pass through as written.
    """
    # cpp and rust word an unexpected end of input differently; collapse both.
    if "mismatched input '<EOF>' expecting" in message or "unexpected token in expression: Eof" in message:
        return "Unexpected end of query. Check for a missing table, column, bracket, or quote."
    if message.startswith(HOGQL_PARSE_ERROR_PREFIXES):
        return (
            "This isn't valid HogQL. Check for a typo, a missing comma or operator, "
            "or a reserved word used as a column or alias without quotes."
        )
    return message
