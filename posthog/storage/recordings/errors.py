class BlockFetchError(Exception):
    pass


class BlockDeletionNotSupportedError(Exception):
    """Raised when attempting to delete a recording on a deployment that doesn't support encrypted storage."""

    pass


class FileFetchError(Exception):
    pass


class FileUploadError(Exception):
    pass


class RecordingDeletedError(Exception):
    """Raised when attempting to access a recording that has been deleted."""

    def __init__(self, message: str, deleted_at: int | None = None):
        super().__init__(message)
        self.deleted_at = deleted_at
