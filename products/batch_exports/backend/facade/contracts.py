"""
Contract types for batch_exports.

Stable, framework-free dataclasses defining what this product hands to the rest of the
codebase. No Django or DRF imports, and enums are flattened to their ``str`` value, so a
consumer never needs a model class to read a batch export. A consumer that writes one of
those values imports the enum from ``facade/enums.py``.

The fields are the ones consumers read today and nothing more. An encrypted model field
never crosses whole, because reading one decrypts it; ``BatchExportDetail`` documents the
case that matters here.

Most contracts use ``pydantic.dataclasses.dataclass`` — same syntax and
``is_dataclass()`` compatibility as the stdlib variant, with runtime validation on
construction, so a mapper mistake surfaces at the boundary instead of as a malformed
payload later. ``AWSCredentials`` is the exception and is documented at its definition.
"""

import datetime as dt
from dataclasses import (
    dataclass as stdlib_dataclass,
    field,
)
from uuid import UUID

from pydantic.dataclasses import dataclass

# The Django model label of BatchExport, for consumers that report on models by name.
BATCH_EXPORT_MODEL_LABEL = "batch_exports.BatchExport"


class InvalidBatchExportFilters(ValueError):
    """Raised when event filters are not a list of filters a batch export can apply."""


class UnsupportedDestinationTestError(ValueError):
    """Raised when a destination type has no connection test."""


class UnsupportedHogQLQueryError(Exception):
    """Raised when a HogQL query cannot be used to power a batch export."""


class FileDownloadNotFoundError(LookupError):
    """Raised when a file download run, or the file a request names, does not exist for the team.

    The message, when there is one, says which file index is out of range.
    """


class InvalidFileDownloadRequestError(ValueError):
    """Raised when a file download cannot do what was asked, for example download a run that has not finished."""


class TooManyConcurrentFileDownloadsError(Exception):
    """Raised when a team already has the maximum number of file downloads starting or running."""


class FileDownloadStartError(Exception):
    """Raised when the workflow of a new file download does not start. The run is saved as failed."""


class BatchExportNotFoundError(LookupError):
    """Raised when the team has no batch export with the id a request names."""


class BatchExportRunNotFoundError(LookupError):
    """Raised when a batch export of the team has no run with the id a request names."""


class BatchExportBackfillNotFoundError(LookupError):
    """Raised when a batch export of the team has no backfill with the id a request names."""


class InvalidBatchExportRunRequestError(ValueError):
    """Raised when a run cannot do what was asked, for example cancel a run that has finished."""


class InvalidBackfillRequestError(ValueError):
    """Raised when a backfill cannot do what was asked, for example start over a range that is not valid.

    The message says what is wrong with the request.
    """


class TooManyConcurrentBackfillsError(Exception):
    """Raised when a team already has the maximum number of backfills starting or running."""


@dataclass(frozen=True)
class BatchExportRef:
    """The bare identity of a batch export, for listing it by name."""

    id: UUID
    name: str


@dataclass(frozen=True)
class BatchExportDetail:
    """A scheduled batch export and the destination it writes to.

    The destination's stored config is deliberately absent. It decrypts on read, so it
    holds that destination's credentials: passwords, private keys, tokens. Only the two
    event filters a consumer reads are lifted out of it.
    """

    id: UUID
    team_id: int
    name: str
    interval: str
    paused: bool
    created_at: dt.datetime
    last_updated_at: dt.datetime
    destination_type: str
    exclude_events: tuple[str, ...]
    include_events: tuple[str, ...]


@dataclass(frozen=True)
class BatchExportBackfillSummary:
    """One backfill of a batch export."""

    id: UUID
    status: str
    start_at: dt.datetime | None
    adjusted_start_at: dt.datetime | None
    created_at: dt.datetime
    last_updated_at: dt.datetime


@dataclass(frozen=True)
class BatchExportRunSummary:
    """One run of a batch export, over one data interval."""

    id: UUID
    status: str
    latest_error: str | None
    data_interval_start: dt.datetime | None
    data_interval_end: dt.datetime | None
    finished_at: dt.datetime | None
    created_at: dt.datetime
    last_updated_at: dt.datetime


@dataclass(frozen=True)
class BatchExportRunFailure:
    """A failed run, with the export and team a failure notification needs."""

    run_id: UUID
    team_id: int
    export_id: UUID
    export_name: str
    last_updated_at: dt.datetime


@dataclass(frozen=True)
class FailedBatchExportRun:
    """The latest run of an export, when that run failed."""

    export_id: UUID
    export_name: str
    error: str | None
    failed_at: dt.datetime | None


@dataclass(frozen=True)
class TeamTotal:
    """One row of a per-team aggregate."""

    team_id: int
    total: int


@dataclass(frozen=True)
class DestinationTestStepResult:
    """The outcome of one destination test step. ``message`` explains a failure."""

    status: str
    message: str | None


@dataclass(frozen=True)
class DestinationTestStep:
    """One check in a destination's connection test. ``result`` is None until the step runs."""

    name: str
    description: str
    result: DestinationTestStepResult | None


@dataclass(frozen=True)
class DestinationTest:
    """The ordered checks that test a connection to a destination.

    Each step depends on the steps before it, so a client runs them in order.
    """

    steps: tuple[DestinationTestStep, ...]


@dataclass(frozen=True)
class FileDownloadRequest:
    """What to export to a downloadable file, as a person asked for it.

    ``include_events`` and ``exclude_events`` apply to the ``events`` model only. ``hogql_query``
    and ``hogql_modifiers`` apply to the ``hogql`` model only, and that model needs only the
    interval bounds its query references.
    """

    model: str
    format: str
    compression: str | None
    max_size_mb: int | None
    data_interval_start: dt.datetime | None
    data_interval_end: dt.datetime | None
    include_events: tuple[str, ...] | None = None
    exclude_events: tuple[str, ...] | None = None
    hogql_query: str | None = None
    hogql_modifiers: dict[str, object] | None = None


@dataclass(frozen=True)
class FileDownloadRun:
    """A file download run, with the status a person sees.

    ``files`` holds the ids of the downloadable files, in download order. It is None until the
    run completes and its files are ready. A completed run that exported rows reports
    ``Running`` until then, because its files are written after the run completes.
    """

    id: UUID
    status: str
    error: str | None
    files: tuple[UUID, ...] | None
    records_completed: int | None


# The fields a page of runs or backfills can be ordered by, as the API's `ordering` parameter names them.
BATCH_EXPORT_RUN_ORDERING_FIELDS = ("created_at", "data_interval_start")
BATCH_EXPORT_BACKFILL_ORDERING_FIELDS = ("created_at", "start_at")


@dataclass(frozen=True)
class ListPageBound:
    """Where a page of an ordered list starts.

    Only the items whose first ordering field sorts before ``value`` (when ``before``) or after
    it (otherwise) are on the page. ``value`` is the field's value as text, as an API cursor carries it.
    """

    value: str
    before: bool


@dataclass(frozen=True)
class ListPage:
    """One page of an ordered list.

    ``ordering`` names the fields to sort by, most significant first. A leading ``-`` sorts that
    field in descending order. The page skips ``offset`` items past ``bound`` and holds at most
    ``limit`` items.
    """

    ordering: tuple[str, ...]
    bound: ListPageBound | None
    offset: int
    limit: int


@dataclass(frozen=True)
class DatetimeRange:
    """A range of time that includes both of its ends."""

    start: dt.datetime
    end: dt.datetime


@dataclass(frozen=True)
class BatchExportRunFilters:
    """Which runs of a batch export to list. A filter left empty does not apply.

    ``data_interval`` keeps the runs whose whole data interval is inside the range.
    """

    statuses: tuple[str, ...] = ()
    created: DatetimeRange | None = None
    data_interval: DatetimeRange | None = None


@dataclass(frozen=True)
class BatchExportRunDetail:
    """One run of a batch export, with every field the API shows.

    A run belongs to a scheduled batch export or to an on-demand one, never to both.
    """

    id: UUID
    status: str
    records_completed: int | None
    records_failed: int | None
    latest_error: str | None
    data_interval_start: dt.datetime | None
    data_interval_end: dt.datetime | None
    cursor: str | None
    created_at: dt.datetime
    finished_at: dt.datetime | None
    last_updated_at: dt.datetime
    records_total_count: int | None
    bytes_exported: int | None
    batch_export_id: UUID | None
    batch_export_on_demand_id: UUID | None
    backfill_id: UUID | None


@dataclass(frozen=True)
class BatchExportBackfillProgress:
    """How far a backfill has got. ``progress`` is the finished share of the runs, from 0 to 1."""

    total_runs: int | None
    finished_runs: int | None
    progress: float | None


@dataclass(frozen=True)
class BatchExportBackfillDetail:
    """One backfill of a batch export, with every field the API shows.

    ``progress`` is None when it has no meaning: the backfill did not complete and is not
    running, or it is one run over all data.
    """

    id: UUID
    team_id: int
    batch_export_id: UUID
    start_at: dt.datetime | None
    end_at: dt.datetime | None
    status: str
    created_at: dt.datetime
    finished_at: dt.datetime | None
    last_updated_at: dt.datetime
    total_records_count: int | None
    adjusted_start_at: dt.datetime | None
    progress: BatchExportBackfillProgress | None


@dataclass(frozen=True)
class BatchExportBackfillStart:
    """A backfill that started, and the destination type of the batch export it fills."""

    backfill_id: str
    destination_type: str


@stdlib_dataclass(frozen=True)
class AWSCredentials:
    """An AWS key pair, optionally temporary.

    A stdlib dataclass rather than a pydantic one: this crosses the Temporal payload
    boundary on every S3 and Redshift export, and callers build it positionally, so it
    stays as plain a dataclass as the rest of the Temporal inputs in ``service.py``.
    The secret key and the session token stay out of ``repr``, so they cannot reach a
    log line. The access key id identifies the credential rather than authenticating
    it, so it stays visible for debugging.
    """

    aws_access_key_id: str
    aws_secret_access_key: str = field(repr=False)
    aws_session_token: str | None = field(default=None, repr=False)
    expiration: dt.datetime | None = field(default=None)

    @property
    def expiry_time(self) -> str | None:
        """ISO-8601 expiration time for temporary credentials, if available."""
        if self.expiration is None:
            return None
        return self.expiration.isoformat()
