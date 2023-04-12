class HogQLException(Exception):
    """An exception in the HogQL layer. This is exposed to the user."""

    pass


class SyntaxException(HogQLException):
    line: int
    column: int

    def __init__(self, message: str, *, line: int, column: int):
        super().__init__(message)
        self.line = line
        self.column = column

    def __str__(self):
        return f"Syntax error at line {self.line}, column {self.column}: {super().__str__()}"


class ResolverException(HogQLException):
    pass


class ParserException(HogQLException):
    pass


class NotImplementedException(HogQLException):
    pass
