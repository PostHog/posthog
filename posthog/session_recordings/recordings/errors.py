class BlockFetchError(Exception):
    pass


class RecordingBlockFetchError(Exception):
    """Raised when one or more recording blocks could not be fetched from the recording-api.

    Represents a transient / recoverable failure (recording-api returning a non-404/410 error,
    a timeout, or an S3 / decompress failure) rather than a client error, so callers should
    surface a retriable response instead of a blanket 500.
    """

    def __init__(self, message: str, failed_block_indices: list[int] | None = None) -> None:
        super().__init__(message)
        self.failed_block_indices = failed_block_indices or []


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
