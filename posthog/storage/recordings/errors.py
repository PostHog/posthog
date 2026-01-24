from typing import Optional


class BlockFetchError(Exception):
    pass


class FileFetchError(Exception):
    pass


class FileUploadError(Exception):
    pass


class RecordingDeletedError(Exception):
    """Raised when attempting to access a recording that has been deleted."""

    def __init__(self, message: str, deleted_at: Optional[int] = None):
        super().__init__(message)
        self.deleted_at = deleted_at
