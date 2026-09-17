"""
Contract types for batch_exports.

Stable, framework-free dataclasses defining what this product hands to the rest of the
codebase. No Django or DRF imports, and enums are flattened to their ``str`` value, so a
consumer never needs a model class to read a batch export.

The fields are the ones consumers read today and nothing more. Destination secrets stay
out: only ``destination_type`` and the stored ``destination_config`` cross, and the
config is already redacted by the destination's ``secret_fields`` before it is shown.

Most contracts use ``pydantic.dataclasses.dataclass`` — same syntax and
``is_dataclass()`` compatibility as the stdlib variant, with runtime validation on
construction, so a mapper mistake surfaces at the boundary instead of as a malformed
payload later. ``AWSCredentials`` is the exception and is documented at its definition.
"""

import datetime as dt
from collections.abc import Mapping
from dataclasses import (
    dataclass as stdlib_dataclass,
    field,
)
from uuid import UUID

from pydantic.dataclasses import dataclass

# The Django model label of BatchExport, for consumers that report on models by name.
BATCH_EXPORT_MODEL_LABEL = "batch_exports.BatchExport"


@dataclass(frozen=True)
class BatchExportRef:
    """The bare identity of a batch export, for listing it by name."""

    id: UUID
    name: str


@dataclass(frozen=True)
class BatchExportDetail:
    """A scheduled batch export and the destination it writes to."""

    id: UUID
    team_id: int
    name: str
    interval: str
    paused: bool
    created_at: dt.datetime
    last_updated_at: dt.datetime
    destination_type: str
    destination_config: Mapping[str, object]


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
    data_interval_end: dt.datetime
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


@stdlib_dataclass(frozen=True)
class AWSCredentials:
    """An AWS key pair, optionally temporary.

    A stdlib dataclass rather than a pydantic one: this crosses the Temporal payload
    boundary on every S3 and Redshift export, and callers build it positionally, so it
    stays as plain a dataclass as the rest of the Temporal inputs in ``service.py``.
    The key and token are kept out of ``repr`` so they cannot reach a log line.
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
