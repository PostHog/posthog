class BlockFetchError(Exception):
    pass


class BlockListingError(Exception):
    """Raised when a recording's block listing could not be fetched.

    Distinct from an empty listing: here we don't know whether the recording has blocks,
    so callers must not report the recording as missing.
    """


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
