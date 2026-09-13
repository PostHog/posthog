class BlockFetchError(Exception):
    """Raised when a recording block cannot be read.

    `retriable` is False when a second attempt cannot change the result, for example
    when the Recording API says the block does not exist.
    """

    def __init__(self, message: str, *, retriable: bool = True):
        super().__init__(message)
        self.retriable = retriable


class FileFetchError(Exception):
    pass


class FileUploadError(Exception):
    pass


class RecordingDeletedError(Exception):
    """Raised when attempting to access a recording that has been deleted."""

    def __init__(self, message: str, deleted_at: int | None = None, deleted_by: str | None = None):
        super().__init__(message)
        self.deleted_at = deleted_at
        self.deleted_by = deleted_by
