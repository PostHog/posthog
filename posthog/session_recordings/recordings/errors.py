class BlockFetchError(Exception):
    """Raised when a recording block can't be fetched from the Recording API.

    `status_code` carries the upstream HTTP status when known (e.g. 403 for an
    access refusal), so callers can tell a permission denial from a transient
    failure instead of treating every cause the same way.
    """

    def __init__(self, message: str, status_code: int | None = None):
        super().__init__(message)
        self.status_code = status_code


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
