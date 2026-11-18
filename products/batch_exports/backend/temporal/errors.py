class MissingRequiredInputsError(RuntimeError):
    """We are unable to recover due to some input being missing.

    This exists to signal an impossible runtime state. At the time of writing,
    it should not be possible to get into this state, but if we ever see this,
    it's likely a signal of a bug.
    """

    pass


class ColumnTypeMappingError(TypeError):
    def __init__(self, destination: str, column: str, column_type: object) -> None:
        self.destination = destination
        self.column = column
        self.column_type = str(column_type)
        super().__init__(f"No {destination} type mapping for column '{column}' with Arrow type '{column_type}'.")


class UnsupportedColumnTypeError(Exception):
    """We tried to export a type that `destination` does not support.

    This should only be possible with HogQL batch exports that take an arbitrary
    query with arbitrary types. Pre-defined models use well-known queries that
    should always be compatible.
    """

    def __init__(self, destination: str, column: str, column_type: object) -> None:
        self.destination = destination
        self.column = column
        self.column_type = str(column_type)
        super().__init__(
            f"Column '{column}' has type '{column_type}', which cannot be exported to {destination} "
            f"without loss of data. Change the query to return a type {destination} supports "
            "by casting the column to a different type."
        )
