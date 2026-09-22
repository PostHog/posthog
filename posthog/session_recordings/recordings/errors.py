class BlockFetchError(Exception):
    pass


class RecordingApiConfigurationError(RuntimeError):
    """The caller cannot reach recording-api because a setting is missing. Retries cannot fix it, so
    callers that tolerate a failed call must still let this one through."""


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
