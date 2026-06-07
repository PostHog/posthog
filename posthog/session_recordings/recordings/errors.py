class BlockFetchError(Exception):
    """Base for a single recording block failing to fetch from the recording-api.

    Never raised directly — callers raise a concrete subclass so that "terminal" vs
    "transient" is an explicit choice rather than the default behaviour of a bare
    ``except BlockFetchError``. The base exists so broad callers (e.g. the export
    activity) can still catch any block-fetch failure with one handler.
    """


class TransientBlockFetchError(BlockFetchError):
    """A recording block failed for a recoverable reason (recording-api 5xx, network
    timeout / connection failure).

    Retriable: the caller should surface a retriable response (503) so the block can be
    fetched again, in contrast to the terminal BlockNotFoundError.
    """


class BlockNotFoundError(BlockFetchError):
    """A specific recording block is permanently missing (recording-api 404).

    Terminal, unlike TransientBlockFetchError: the block is gone and retrying will never
    recover it, so callers must surface a non-retriable response (404) rather than the
    retriable 503 used for transient failures.
    """


class SnapshotRequestFailedError(Exception):
    """Raised when one or more recording blocks could not be fetched for a snapshot request.

    Represents a transient / recoverable failure (recording-api returning a 5xx, or a network
    timeout / connection failure) rather than a client error, so callers should surface a
    retriable response instead of a blanket 500.
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
