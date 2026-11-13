"""Cross-product value contracts exposed by data_catalog."""

from datetime import datetime
from uuid import UUID

from pydantic.dataclasses import dataclass

from .enums import JudgeRelation, ShapeOutcome, UsageSnapshotStatus


@dataclass(frozen=True)
class MetricListFilters:
    """Filters the metric list applies, with or without a search."""

    status: str | None = None
    definition_kind: str | None = None


@dataclass(frozen=True)
class MetricSummary:
    id: UUID
    name: str
    display_name: str
    definition_kind: str | None
    referenced_table_names: list[str]


@dataclass(frozen=True)
class HogQLMetricDefinition:
    query: str
    values: dict[str, object]


@dataclass(frozen=True)
class MetricRead:
    summary: MetricSummary
    hogql_definition: HogQLMetricDefinition | None


@dataclass(frozen=True)
class MetricBulkOwnerChange:
    updated_ids: list[UUID]
    skipped_ids: list[UUID]


@dataclass(frozen=True)
class MetricRunCounts:
    """Runs of one catalog metric in the scan window, counted from the run event."""

    metric_id: UUID
    # Keyed by the run event's `source` (web, mcp, slack, ...), so a new surface needs no contract
    # change. Scout runs never appear here; they are in `scout_runs`.
    direct_runs: dict[str, int]
    direct_people: int
    scout_runs: int


@dataclass(frozen=True)
class AdjustedRun:
    """One agent query the judge matched to a catalog metric, and whether the agent read that metric first."""

    metric_id: UUID
    read_metric_first: bool
    relation: JudgeRelation
    intent: str
    sql: str
    reasoning: str
    occurred_at: datetime
    session_id: str | None
    is_scout: bool


@dataclass(frozen=True)
class TopicCoverage:
    """What a topic's sessions that asked for a metric ended up with. Each session counts once."""

    metric: int
    table: int
    nothing: int


@dataclass(frozen=True)
class TopicDefinition:
    title: str
    description: str


@dataclass(frozen=True)
class TopicCluster:
    title: str
    description: str
    session_count: int
    people: int
    coverage: TopicCoverage


@dataclass(frozen=True)
class TopicSessionCounts:
    """What the sampled sessions did with data. Only analysis sessions fall into topics."""

    analysis: int
    lookup: int
    automation: int
    unclear: int
    unread: int
    coverage_unchecked: int = 0


@dataclass(frozen=True)
class TableSource:
    """A table or view that agents found through its description and then queried, across the whole window."""

    name: str
    sessions: int
    people: int


@dataclass(frozen=True)
class UncoveredGroup:
    """A recurring query shape, grouped by measure fingerprint, with its catalog outcome.

    People and runs leave out scouts (scheduled agents).
    """

    fingerprint_digest: str
    measure: str
    outcome: ShapeOutcome
    matched_metric_id: UUID | None
    distinct_people: int
    runs: int
    sample_sql: str
    draft_name: str | None
    draft_description: str | None


@dataclass(frozen=True)
class UsageSnapshotPayload:
    """The stored body of a usage snapshot. Each scan step writes its own section, so a section
    stays None until its step has run."""

    metric_runs: list[MetricRunCounts] | None = None
    # Session ids that one agent conversation spans, for conversations that span more than one. The
    # API does not return this section; later steps read it to count and match per conversation.
    conversations: list[list[str]] | None = None
    adjusted_runs: list[AdjustedRun] | None = None
    topics: list[TopicCluster] | None = None
    # The whole list, including topics with no sessions this scan, so the next scan keeps them.
    topic_definitions: list[TopicDefinition] | None = None
    topic_sessions: TopicSessionCounts | None = None
    table_sources: list[TableSource] | None = None
    uncovered: list[UncoveredGroup] | None = None


@dataclass(frozen=True)
class UsageSnapshotSummary:
    id: UUID
    status: UsageSnapshotStatus
    error_message: str
    window_start: datetime
    window_end: datetime
    judge_model: str
    computed_at: datetime | None
    created_at: datetime


@dataclass(frozen=True)
class UsageSnapshotDetail(UsageSnapshotSummary):
    payload: UsageSnapshotPayload


@dataclass(frozen=True)
class MetricUsage:
    """One metric's slice of a snapshot, assembled at read time."""

    metric_id: UUID
    snapshot_id: UUID
    window_start: datetime
    window_end: datetime
    computed_at: datetime | None
    runs: MetricRunCounts | None
    adjusted_runs: list[AdjustedRun]
