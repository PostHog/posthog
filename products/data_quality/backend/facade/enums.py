"""
Exported enums for data_quality.

The pure, Django-free types other layers (presentation, information_schema loaders, MCP tooling)
share. Internal-only constants stay in the implementation.
"""

from enum import StrEnum


class CreatedSource(StrEnum):
    """Who authored a check, for review context."""

    USER = "user"
    AI_GENERATED = "ai_generated"


class CheckType(StrEnum):
    """Assertion a data quality check makes about its subject.

    Each value has a matching ``CheckTypeSpec`` in the check registry, which owns the config
    schema and the HogQL compilation. Adding a type means adding a spec, not a migration.
    """

    NOT_NULL = "not_null"
    UNIQUE = "unique"
    ACCEPTED_VALUES = "accepted_values"
    RELATIONSHIPS = "relationships"
    ROW_COUNT = "row_count"
    FRESHNESS = "freshness"
    CUSTOM_SQL = "custom_sql"


class CheckSeverity(StrEnum):
    """How loudly a failing check speaks. Only ``error`` failures notify and mark a subject failing."""

    ERROR = "error"
    WARN = "warn"


class CheckRunStatus(StrEnum):
    """Outcome of one check execution.

    ``failed`` means the assertion found failing rows; ``errored`` means the query could not be
    compiled or executed, which is a different problem and never notifies as a data failure.
    """

    PASSED = "passed"
    FAILED = "failed"
    ERRORED = "errored"
    SKIPPED = "skipped"


class SuiteRunStatus(StrEnum):
    """Lifecycle of a batch of check executions."""

    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    EMPTY = "empty"


class SuiteRunTrigger(StrEnum):
    """What started a suite run.

    Every automatic trigger is an event on the subject's own data -- a materialization or a source
    sync completing. Checks have no independent schedule.
    """

    MANUAL = "manual"
    MATERIALIZATION = "materialization"
    SOURCE_SYNC = "source_sync"


class SubjectType(StrEnum):
    """Kind of catalog object a check targets.

    On the check itself the subject is a foreign key (``saved_query`` for views, ``table`` for
    warehouse tables); run history denormalizes it as loose ``(subject_type, subject_uuid, name)``
    tuples so it outlives hard deletes.
    """

    TABLE = "table"
    VIEW = "view"


class SubjectRelation(StrEnum):
    """Whether a stamped subject is the run's own (``declared``) or one it read besides it (``referenced``)."""

    DECLARED = "declared"
    REFERENCED = "referenced"


class SubjectStatus(StrEnum):
    """Whether the subject a check points at still resolves."""

    ACTIVE = "active"
    ORPHANED = "orphaned"


class SubjectHealth(StrEnum):
    """Rollup of a subject's latest check results, shared by the REST endpoint and system table."""

    HEALTHY = "healthy"
    WARN = "warn"
    FAILING = "failing"
    ERRORING = "erroring"
    UNKNOWN = "unknown"
