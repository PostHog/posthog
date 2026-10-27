from datetime import datetime
from typing import Annotated, Any, Literal, get_args

from pydantic import BaseModel, ConfigDict, Field
from pydantic.alias_generators import to_camel


class Contract(BaseModel):
    # Without `json_schema_serialization_defaults_required`, fields with defaults generate as optional in TypeScript.
    model_config = ConfigDict(
        alias_generator=to_camel,
        populate_by_name=True,
        frozen=True,
        json_schema_serialization_defaults_required=True,
    )


TraceNodeKind = Literal["trace", "span", "generation", "embedding"]
TRACE_NODE_KINDS: tuple[TraceNodeKind, ...] = get_args(TraceNodeKind)


class TraceNodeStats(Contract):
    cost_usd: float | None
    input_tokens: int | None
    output_tokens: int | None
    cache_read_tokens: int | None
    cache_write_tokens: int | None
    latency_ms: float | None


class TraceNode(Contract):
    id: str
    kind: TraceNodeKind
    name: str
    model: str | None
    stats: TraceNodeStats
    has_error: bool
    children: list["TraceNode"]


class TraceTimelineRow(Contract):
    id: str
    kind: TraceNodeKind
    name: str
    depth: int
    start_ms: float
    duration_ms: float | None
    has_error: bool


class TracePerson(Contract):
    distinct_id: str
    label: str


class Trace(Contract):
    id: str
    name: str | None
    created_at: datetime
    session_id: str | None
    person: TracePerson | None
    totals: TraceNodeStats
    has_error: bool
    error_count: int
    tree: list[TraceNode]
    timeline: list[TraceTimelineRow]
    total_ms: float
    thread_node_ids: list[str]
    default_node_id: str
    node_ids_by_alias: dict[str, str]


class TraceNodeIOKeys(Contract):
    input: str | None
    output: str | None
    tools: str | None


class TraceNodeMetadata(Contract):
    provider: str | None
    temperature: float | None
    session_id: str | None
    prompt_name: str | None
    prompt_version: float | None


class TraceNodeEvent(Contract):
    name: str
    uuid: str
    timestamp: datetime
    properties: dict[str, Any] = Field(
        description="The event's properties as ingested, including its input and output values."
    )
    io_keys: TraceNodeIOKeys = Field(
        description="Which keys of `properties` hold the node's input, output and tools, or null when it has none."
    )


class TraceNodeDetail(Contract):
    id: str
    kind: TraceNodeKind
    error: str | None
    metadata: TraceNodeMetadata
    event: TraceNodeEvent | None


class EvaluationPassFilters(Contract):
    """HogQL conditions over `$ai_evaluation` events, built from each evaluation's current output config."""

    graded: str  # The run counts toward a pass rate.
    passed: str  # The run passed. Implies `graded`.


# HogQL filter keys that stand in for `EvaluationPassFilters` in a stored filter, so that the stored filter holds no
# evaluation rules and always grades with the current ones. `resolve_evaluation_pass_markers` replaces them at query time.
EVALUATION_GRADED_MARKER = "aiEvaluationGraded()"
EVALUATION_PASSED_MARKER = "aiEvaluationPassed()"


EvaluationOutcome = Literal["pass", "fail", "inconclusive", "unrated"]


class TraceEvaluationResult(Contract):
    id: str
    evaluation_id: str | None
    evaluation_name: str
    target_node_id: str = Field(
        description="The tree node the result grades: the generation's event uuid, or the trace id for a trace-level result."
    )
    outcome: EvaluationOutcome
    label: str = Field(description='What the result says, such as "True", "0.82", "Positive" or "Skipped".')
    reasoning: str | None
    timestamp: datetime
    is_backfill: bool


class TraceEvaluationResults(Contract):
    results: list[TraceEvaluationResult]


AttentionReason = Literal["errored", "silent", "worse"]
BucketStatus = Literal["none", "dip", "normal"]
Interval = Literal["hour", "day"]
ChangeUnit = Literal["pp", "points"]


class PassFailCounts(Contract):
    passed: int
    failed: int


class ScoreScale(Contract):
    min: float
    max: float


class ScoreDistribution(Contract):
    mean: float
    scale: ScoreScale | None = Field(description="The configured score bounds, or null when the evaluation sets none.")


class PassRateSummary(Contract):
    kind: Literal["pass_rate"]
    passed: int
    failed: int
    previous: PassFailCounts | None = Field(
        description="Counts in the previous period, or null when it graded too few to compare."
    )
    score: ScoreDistribution | None = Field(description="The score of numeric evaluations with a passing rule.")


class ScoreSummary(Contract):
    kind: Literal["score"]
    score: ScoreDistribution | None = Field(description="Null when the current period scored nothing.")
    previous_mean: float | None


class CategoryCount(Contract):
    key: str
    label: str
    count: int
    previous_share: float | None = Field(
        description=(
            "Percentage of the previous period's graded runs with this category, or null when it graded too few to compare."
        )
    )


class CategoriesSummary(Contract):
    kind: Literal["categories"]
    multiple: bool
    categories: list[CategoryCount] = Field(description="Sorted by count, most frequent first.")
    no_categories_count: int = Field(description="Multiple-selection runs that returned no category.")


class SentimentSummary(Contract):
    kind: Literal["sentiment"]
    positive: int
    neutral: int
    negative: int
    previous_negative_share: float | None


ResultSummary = Annotated[
    PassRateSummary | ScoreSummary | CategoriesSummary | SentimentSummary, Field(discriminator="kind")
]


class ResultChange(Contract):
    value: float = Field(description="Signed difference against the previous period, rounded for display.")
    unit: ChangeUnit
    subject: str | None = Field(description="What changed when it is not the headline, such as a category label.")


class EvaluationResultTrend(Contract):
    values: list[float | None] = Field(
        description="Headline value per bucket, aligned with the overview's `buckets`. Null where nothing was graded."
    )
    volume: list[int] = Field(description="Graded runs per bucket.")


class EvaluationResult(Contract):
    id: str
    name: str
    directory_name: str | None
    evaluation_type: str
    output_type: str
    enabled: bool
    status_reason: str | None = Field(
        description="Why the evaluation stopped with an error, as an evaluation status reason, or null when it has none."
    )
    created_by: str | None
    graded_count: int
    previous_graded_count: int | None = Field(description="Graded runs in the previous period, or null when none.")
    not_applicable_count: int
    skipped_count: int = Field(description="Runs skipped before scoring.")
    last_run_at: datetime | None = Field(description="The latest graded run in the current or previous period.")
    summary: ResultSummary
    trend: EvaluationResultTrend
    change: ResultChange | None = Field(description="Change against the previous period, or null when not comparable.")
    low_evidence: bool
    attention_reasons: list[AttentionReason]
    bucket_status: list[BucketStatus] = Field(
        description="Each bucket against the previous period. A bucket with too few graded runs to judge is never a dip."
    )
    tracked_category: str | None = Field(description="Key of the category a categorical evaluation's trend follows.")


class PeriodComparison(Contract):
    """The same figure for both periods, over only the evaluations with results in both."""

    current: float
    previous: float


class PassRateOverviewEntry(Contract):
    evaluation_id: str
    rate: float
    low_evidence: bool


class PassRateOverview(Contract):
    entries: list[PassRateOverviewEntry] = Field(description="Enabled pass rate evaluations, lowest rate first.")
    median: float | None = Field(description="Median of the per-evaluation pass rates without low evidence.")
    median_comparison: PeriodComparison | None = Field(
        description="Median pass rate in each period, over evaluations with results in both. Null when none has."
    )
    median_trend: list[float | None] = Field(description="Median pass rate per bucket, aligned with `buckets`.")


class OverviewSentiment(Contract):
    evaluation_id: str
    negative_share: float
    previous_share: float | None


class OverviewTotals(Contract):
    graded: int
    graded_comparison: PeriodComparison | None = Field(
        description="Graded runs in each period, over evaluations with results in both. Null when none has."
    )
    graded_trend: list[int]
    sentiment: OverviewSentiment | None


class OverviewPeriodFields(Contract):
    start: datetime = Field(description="Start of the period, in the project's timezone.")
    end: datetime = Field(description="End of the period, exclusive.")


class EvaluationsOverview(OverviewPeriodFields):
    previous_start: datetime
    previous_end: datetime = Field(
        description="End of the previous period. While the current period runs, the previous one stops at the same "
        "point, so both cover the same length of time."
    )
    interval: Interval = Field(description="`hour` for a period of two days or less, else `day`.")
    buckets: list[datetime] = Field(
        description="Start of each bucket, in the project's timezone. Every series is aligned with it. The first "
        "bucket can start before `start`."
    )
    evaluations: list[EvaluationResult]
    totals: OverviewTotals = Field(description="Totals over the enabled evaluations.")
    pass_rate_overview: PassRateOverview


class EvaluationRun(Contract):
    timestamp: datetime
    outcome: Literal["passed", "failed"] | None = Field(
        description="Null when the evaluation has no passing rule, or the run was not graded by it."
    )
    reasoning: str | None = Field(description="The evaluator's reasoning, cut to about 1,000 characters.")
    target_event_id: str | None = Field(description="The generation the run graded. Null for trace and session runs.")
    trace_id: str | None


class EvaluationRuns(Contract):
    results: list[EvaluationRun] = Field(description="Newest first.")


class ScoreBucket(Contract):
    label: str
    count: int


class ScoreHistogram(Contract):
    scale: ScoreScale
    buckets: list[ScoreBucket] = Field(
        description="One bucket per integer on a small integer scale, else ten equal buckets across the scale."
    )
