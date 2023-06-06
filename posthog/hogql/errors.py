from typing import Optional


class HogQLException(Exception):
    """Base exception for HogQL. These are exposed to the user."""

    start: Optional[int]
    end: Optional[int]

    def __init__(self, message: str, *, start: Optional[int] = None, end: Optional[int] = None):
        super().__init__(message)
        self.start = start
        self.end = end


class SyntaxException(HogQLException):
    """Invalid HogQL syntax."""

    line: int
    column: int

    def __init__(self, message: str, *, line: int, column: int):
        super().__init__(message)
        self.line = line
        self.column = column

    def __str__(self):
        return f"Syntax error at line {self.line}, column {self.column}: {super().__str__()}"


class QueryException(HogQLException):
    """The query invalid (though correct syntactically)."""

    pass


class NotImplementedException(HogQLException):
    """This feature isn't implemented in HogQL (yet)."""

    pass


class ResolverException(HogQLException):
    """An internal problem in the resolver layer."""

    pass
