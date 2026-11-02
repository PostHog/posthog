class MissingRequiredInputsError(RuntimeError):
    """We are unable to recover due to some input being missing.

    This exists to signal an impossible runtime state. At the time of writing,
    it should not be possible to get into this state, but if we ever see this,
    it's likely a signal of a bug.
    """

    pass


class UnsupportedColumnTypeError(Exception):
    """Keep retryable so exports can recover when missing type mappings are added."""

    def __init__(self, destination: str, column: str, column_type: object) -> None:
        self.destination = destination
        self.column = column
        self.column_type = str(column_type)
        super().__init__(
            f"Column '{column}' has type '{column_type}', which {destination} batch exports cannot store. "
            f"Change the query to return a type {destination} supports, for example by casting the column to "
            "a string."
        )
