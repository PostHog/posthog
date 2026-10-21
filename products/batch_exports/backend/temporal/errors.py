class MissingRequiredInputsError(RuntimeError):
    """We are unable to recover due to some input being missing.

    This exists to signal an impossible runtime state. At the time of writing,
    it should not be possible to get into this state, but if we ever see this,
    it's likely a signal of a bug.
    """

    pass


class UnsupportedColumnTypeError(Exception):
    """Raised when a column has no type the destination can store.

    A destination maps every column of the record batch schema to one of its own types. The
    `hogql` model lets a query return any type ClickHouse has, so a query can produce a column
    that a destination has no mapping for.

    The condition is permanent, because the same query returns the same column type on every
    run. Each destination that raises this must therefore name it in its
    `NON_RETRYABLE_ERROR_TYPES`, so the run reports this message instead of retrying until the
    export is paused. The lists match on the class name, so a rename of this class has to
    update them too.
    """

    def __init__(self, destination: str, column: str, column_type: object) -> None:
        super().__init__(
            f"Column '{column}' has type '{column_type}', which {destination} batch exports cannot store. "
            f"Change the query to return a type {destination} supports, for example by casting the column to "
            "a string."
        )
