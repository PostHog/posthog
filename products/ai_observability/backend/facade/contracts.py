from datetime import datetime
from typing import Annotated, Any, Literal, get_args

from pydantic import BaseModel, ConfigDict, Field
from pydantic.alias_generators import to_camel

from posthog.dataclasses import frozen


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


class TraceGit(Contract):
    branch: str = Field(description="The git branch checked out when the trace ran.")
    repo: str | None = Field(description="The repository as owner/name, or null when the branch's event has none.")


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
    git: TraceGit | None = Field(
        description="The branch the trace's work ran on: the latest stamped branch other than main or master, else "
        "the first stamp. Null when no event carries a branch."
    )


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
EvaluationRollupOutcome = Literal["pass", "fail", "unrated"]


class TraceEvaluationResult(Contract):
    id: str
    evaluation_id: str | None
    evaluation_name: str
    target_node_id: str = Field(
        description="The tree node the result grades: the generation's event uuid, or the trace id for a trace-level result."
    )
    outcome: EvaluationOutcome
    label: str = Field(description='What the result says, such as "True", "0.82", "Positive" or "Skipped".')
    score: float | None = Field(description="The numeric result of a numeric evaluation, null for every other type.")
    reasoning: str | None
    timestamp: datetime
    is_backfill: bool


class TraceNodeEvaluationRollup(Contract):
    node_id: str = Field(description="The tree node the results grade.")
    outcome: EvaluationRollupOutcome = Field(
        description="Fail if any evaluation fails on the node, else pass if any passes, else unrated."
    )


class TraceEvaluationSummary(Contract):
    """Counts the latest run of each evaluation on each node, by when the run started, so re-runs and backfills
    count once. Inconclusive results count as unrated. Computed over the results returned, at most 250."""

    passed: int
    failed: int
    unrated: int
    nodes: list[TraceNodeEvaluationRollup] = Field(description="One entry per node with results, sorted by node id.")


class TraceEvaluationResults(Contract):
    results: list[TraceEvaluationResult]
    summary: TraceEvaluationSummary


class TraceCluster(Contract):
    run_id: str = Field(
        description="The clustering run that put the trace in this cluster. The cluster page is addressed by this id and the cluster id."
    )
    run_at: datetime = Field(description="When the run finished.")
    job_id: str | None = Field(description="The clustering job the run belongs to, null for a run without a job.")
    job_name: str | None
    cluster_id: int = Field(description="The cluster's id within its run. -1 is the run's outliers.")
    title: str | None
    description: str | None
    is_outlier: bool = Field(description="The trace fit no cluster in this run.")


class TraceClusters(Contract):
    clusters: list[TraceCluster] = Field(
        description="The clusters that list the trace: for each clustering job, the newest scheduled run that lists it. "
        "Manual runs are left out. Clusters come before outliers, then newest first."
    )


class TraceFeedbackScore(Contract):
    id: str
    name: str | None
    value: str = Field(
        description="The score as text: a string as sent, any other value as compact JSON, such as 0, false or 4.5."
    )
    node_id: str = Field(
        description="The tree node the score targets: the step's event uuid, or the trace id for a trace-level score."
    )
    timestamp: datetime


class TraceFeedbackText(Contract):
    kind: Literal["text"]
    id: str
    text: str
    node_id: str = Field(
        description="The tree node the feedback targets: the step's event uuid, or the trace id for trace-level feedback."
    )
    timestamp: datetime


class TraceSurvey(Contract):
    id: str
    name: str | None = Field(description="Null when the survey no longer exists.")


class TraceThumbsAnswer(Contract):
    kind: Literal["thumbs"]
    question: str
    up: bool


class TraceRatingAnswer(Contract):
    kind: Literal["rating"]
    question: str
    value: str
    scale: int | None
    lower_label: str | None
    upper_label: str | None


class TraceChoiceAnswer(Contract):
    kind: Literal["choice"]
    question: str
    choices: list[str]


class TraceTextAnswer(Contract):
    kind: Literal["text"]
    question: str
    text: str


TraceSurveyAnswer = Annotated[
    TraceThumbsAnswer | TraceRatingAnswer | TraceChoiceAnswer | TraceTextAnswer, Field(discriminator="kind")
]


class TraceSurveyResponse(Contract):
    kind: Literal["survey"]
    id: str
    node_id: str = Field(
        description="The tree node the response targets: the trace id, as a survey response covers the whole trace."
    )
    timestamp: datetime
    survey: TraceSurvey
    answers: list[TraceSurveyAnswer]
    complete: bool = Field(description="False when the user left the survey before its end.")
    unavailable: Literal["survey_not_found", "no_questions"] | None = Field(
        description="Why the answers cannot be shown: the survey was deleted, or it has no questions."
    )


class TraceUnansweredSurvey(Contract):
    survey: TraceSurvey
    timestamp: datetime = Field(description="When the survey was first shown.")


TraceSurveyResponsesStatus = Literal["ok", "failed", "not_permitted"]


TraceFeedbackResponse = Annotated[TraceFeedbackText | TraceSurveyResponse, Field(discriminator="kind")]


class TraceFeedbackSummary(Contract):
    total: int = Field(description="Scores plus responses.")
    thumbs_up: int = Field(description="Thumbs up answers to 2-point survey rating questions.")
    thumbs_down: int = Field(description="Thumbs down answers to 2-point survey rating questions.")


class TraceFeedback(Contract):
    scores: list[TraceFeedbackScore] = Field(description="Oldest first.")
    responses: list[TraceFeedbackResponse] = Field(description="What users said, oldest first.")
    unanswered: list[TraceUnansweredSurvey] = Field(
        description="Surveys shown with the trace and not answered, oldest first."
    )
    survey_responses_status: TraceSurveyResponsesStatus = Field(
        description="ok when survey responses are included, failed when the survey read failed, not_permitted when the token lacks the survey:read and query:read scopes."
    )
    summary: TraceFeedbackSummary


class TraceSearchMatch(Contract):
    node_id: str = Field(description="A step whose stored data contains the query. The root's id is the trace id.")
    count: int = Field(
        description="How many times the query occurs in the step's stored inputs, outputs, state, tools, name, model, provider and error, ignoring case. Keys of the stored JSON count too."
    )


class TraceSearchResults(Contract):
    total: int = Field(description="Occurrences of the query across every matching step.")
    matches: list[TraceSearchMatch] = Field(
        description="Matching steps in tree order, the root first. Steps without a match are left out."
    )


TraceSummaryStatus = Literal["pending", "ready", "failed"]
TraceSummaryFailureReason = Literal[
    "trace_not_found", "too_large", "timeout", "provider_error", "not_approved", "access_changed", "error"
]


@frozen
class TraceSummaryJob:
    """What the trace summary job needs to write one summary. Ids only, so the workflow history stays small.
    `requested_at` is when the pending entry the job fills was written."""

    team_id: int
    trace_id: str
    timestamp_hint: datetime | None
    fingerprint: str
    requester_id: int
    requested_at: datetime


class TraceSummaryItem(Contract):
    text: str
    node_id: str | None = Field(description="The step the item refers to, or null when it names none.")


class TraceSummaryContent(Contract):
    title: str
    bullets: list[TraceSummaryItem]
    notes: list[TraceSummaryItem] = Field(description="Details worth a second look, or empty.")
    flow: str = Field(description="The main steps of the trace as a small text diagram.")
    model: str = Field(description="The model that wrote the summary.")
    generated_at: datetime


class TraceSummaryFailure(Contract):
    reason: TraceSummaryFailureReason
    message: str = Field(description="Why the summary failed, ready to show to the user.")


class TraceSummary(Contract):
    status: TraceSummaryStatus = Field(description="`pending` while the summary is written, then `ready` or `failed`.")
    content: TraceSummaryContent | None = Field(description="The summary when `status` is `ready`, else null.")
    failure: TraceSummaryFailure | None = Field(description="Why it failed when `status` is `failed`, else null.")


@frozen
class TraceSummaryRun:
    """What one run of the trace summary job did, for usage reporting."""

    status: Literal["ready", "failed"]
    failure_reason: TraceSummaryFailureReason | None
    duration_ms: int
    input_characters: int
    model: str
    was_sampled: bool
    distinct_id: str
    groups: dict[str, str]


class TracePullRequest(Contract):
    repo_owner: str = Field(description="The owner of the pull request's repository.")
    repo_name: str = Field(description="The name of the pull request's repository.")
    number: int = Field(description="The pull request number.")
    title: str | None = Field(description="The pull request title, or null when the synced data has none.")


class TracePullRequestLookup(Contract):
    pull_request: TracePullRequest | None = Field(
        description="The pull request the trace's git branch belongs to, ranked by engineering analytics, or null "
        "when the trace has no branch, the project has no GitHub source, or no pull request matches."
    )


TraceExportStatus = Literal["pending", "complete", "failed"]
TRACE_EXPORT_STATUSES: tuple[TraceExportStatus, ...] = get_args(TraceExportStatus)


class TraceExport(Contract):
    id: int = Field(description="The export id, used to read its status and download the file.")
    status: TraceExportStatus = Field(description="Whether the file is still being written, ready, or failed.")
    filename: str = Field(description="The name the downloaded JSON file gets.")
    created_at: datetime = Field(description="When the export was requested.")
    expires_after: datetime | None = Field(description="When the file is deleted.")
    exception: str | None = Field(description="Why the export failed, null unless status is failed.")


class TraceExportFile(Contract):
    trace: Trace = Field(description="The trace as the trace endpoint returns it.")
    truncated: bool = Field(
        description="True when the trace has more events than an export reads. The file then holds the earliest "
        "events only, and leaves out the later steps."
    )
    nodes: list[TraceNodeDetail] = Field(
        description="Every node with its event properties as ingested, inputs and outputs included: the root first, "
        "then the tree in pre-order."
    )


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
    entries: list[PassRateOverviewEntry] = Field(
        description="Pass rate evaluations with results in the period, paused ones included, lowest rate first."
    )
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
    totals: OverviewTotals = Field(
        description="Totals over every evaluation's results in the period, paused ones included."
    )
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
