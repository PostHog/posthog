"""Per-job HTTP context.

The activity that runs a warehouse-source sync sets a `JobContext` once at
its entry point. The tracked HTTP transport reads it on every request to
attach `team_id`, `source_type`, `external_data_schema_id`,
`external_data_source_id`, and `external_data_job_id` to logs, metrics and
sample-capture decisions.

Stored in a `contextvars.ContextVar` so it propagates across the source
generator's thread-pool boundary — see `pipelines/pipeline/pipeline.py`'s
`copy_context()` snapshot, which already preserves contextvars when calls
hop into the executor.
"""

from __future__ import annotations

import contextvars
import dataclasses
from collections.abc import Iterator
from contextlib import contextmanager
from typing import TYPE_CHECKING

from structlog.contextvars import bind_contextvars, unbind_contextvars

if TYPE_CHECKING:
    import uuid


@dataclasses.dataclass(frozen=True)
class JobContext:
    team_id: int
    source_type: str
    external_data_source_id: str
    external_data_schema_id: str
    external_data_job_id: str

    def as_log_fields(self) -> dict[str, int | str]:
        return {
            "team_id": self.team_id,
            "source_type": self.source_type,
            "external_data_source_id": self.external_data_source_id,
            "external_data_schema_id": self.external_data_schema_id,
            "external_data_job_id": self.external_data_job_id,
        }


_current_job_context: contextvars.ContextVar[JobContext | None] = contextvars.ContextVar(
    "data_imports_http_job_context", default=None
)


_BOUND_LOG_FIELD_NAMES: tuple[str, ...] = (
    "source_type",
    "external_data_source_id",
    "external_data_schema_id",
    "external_data_job_id",
)


def current_job_context() -> JobContext | None:
    return _current_job_context.get()


def _make_context(
    *,
    team_id: int,
    source_type: str,
    external_data_source_id: str | uuid.UUID,
    external_data_schema_id: str | uuid.UUID,
    external_data_job_id: str,
) -> JobContext:
    return JobContext(
        team_id=team_id,
        source_type=source_type,
        external_data_source_id=str(external_data_source_id),
        external_data_schema_id=str(external_data_schema_id),
        external_data_job_id=external_data_job_id,
    )


def bind_job_context(
    *,
    team_id: int,
    source_type: str,
    external_data_source_id: str | uuid.UUID,
    external_data_schema_id: str | uuid.UUID,
    external_data_job_id: str,
) -> JobContext:
    """Set the current `JobContext` and bind matching structlog contextvars.

    Mirrors the existing pattern in `import_data_activity_sync` where
    `bind_contextvars(team_id=...)` is called without an explicit unbind —
    each activity invocation rebinds before doing work. The contextvar is
    per-task / per-thread, so concurrent activities don't leak.
    """
    ctx = _make_context(
        team_id=team_id,
        source_type=source_type,
        external_data_source_id=external_data_source_id,
        external_data_schema_id=external_data_schema_id,
        external_data_job_id=external_data_job_id,
    )
    _current_job_context.set(ctx)
    bind_contextvars(
        source_type=ctx.source_type,
        external_data_source_id=ctx.external_data_source_id,
        external_data_schema_id=ctx.external_data_schema_id,
        external_data_job_id=ctx.external_data_job_id,
    )
    return ctx


@contextmanager
def scoped_job_context(
    *,
    team_id: int,
    source_type: str,
    external_data_source_id: str | uuid.UUID,
    external_data_schema_id: str | uuid.UUID,
    external_data_job_id: str,
) -> Iterator[JobContext]:
    """Context-manager variant for tests / synthetic call sites.

    Resets the contextvar and unbinds structlog contextvars on exit so
    test isolation isn't dependent on subsequent activities overwriting
    state.
    """
    ctx = _make_context(
        team_id=team_id,
        source_type=source_type,
        external_data_source_id=external_data_source_id,
        external_data_schema_id=external_data_schema_id,
        external_data_job_id=external_data_job_id,
    )
    token = _current_job_context.set(ctx)
    bind_contextvars(
        source_type=ctx.source_type,
        external_data_source_id=ctx.external_data_source_id,
        external_data_schema_id=ctx.external_data_schema_id,
        external_data_job_id=ctx.external_data_job_id,
    )
    try:
        yield ctx
    finally:
        _current_job_context.reset(token)
        unbind_contextvars(*_BOUND_LOG_FIELD_NAMES)
