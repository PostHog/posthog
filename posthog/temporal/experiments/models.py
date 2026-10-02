import dataclasses

from posthog.dataclasses import frozen

# Temporal retry ceiling for the per-metric calc activities. Shared with the activity code, which emits the
# terminal `experiment metric error` analytics event only on the final attempt — keep the RetryPolicy in
# workflows.py and this constant in lockstep or terminal failures get emitted early / not at all.
TIMESERIES_METRIC_MAX_ATTEMPTS = 3


@frozen(frozen=False)
class HourlyRunTotals:
    """Counts accumulated across the continue-as-new legs of one hourly run."""

    total: int = 0
    succeeded: int = 0
    failed: int = 0
    published: int = 0


@frozen
class HourlyRunContinuation:
    """Progress a continue-as-new leg starts from.

    run_started_at is the first leg's workflow.now(). The publish activity only accepts points with
    query_to >= run_started_at, and the regular and saved workflows share one recalculation row per run
    through it, so every leg must carry the original value, never its own clock."""

    after_experiment_id: int
    run_started_at: str  # ISO 8601
    totals: HourlyRunTotals


@frozen
class MetricsPageInput:
    """Input to the paged discovery activities."""

    hour: int  # 0-23, which hour's teams to process
    after_experiment_id: int  # cursor, 0 on the first page
    page_size: int  # experiments per page, not metrics


@frozen
class ExperimentRegularMetricsWorkflowInputs:
    """Input to the hourly workflow."""

    hour: int  # 0-23, which hour's teams to process
    # Set only on continue-as-new legs.
    continuation: HourlyRunContinuation | None = None


@frozen
class ExperimentRegularMetricInput:
    """Input to calculate a single experiment-metric."""

    experiment_id: int
    metric_uuid: str
    fingerprint: str
    # Defaulted so histories recorded before the field existed still decode during replay.
    team_id: int | None = None


@dataclasses.dataclass
class ExperimentRegularMetricResult:
    """Result from calculating a single experiment-metric."""

    experiment_id: int
    metric_uuid: str
    fingerprint: str
    success: bool
    error_message: str | None = None


@frozen
class RegularMetricsPage:
    """One discovery page of regular metrics, grouped by whole experiments."""

    metrics: list[ExperimentRegularMetricInput]
    # Id of the last experiment the page included when more experiments may remain (full page, or the
    # page ended early on the metric budget), else None. Derived from experiments included, not
    # metrics returned: a page whose experiments all have zero eligible metrics still advances it.
    next_after_experiment_id: int | None


@frozen
class ExperimentSavedMetricsWorkflowInputs:
    """Input to the hourly saved metrics workflow."""

    hour: int  # 0-23, which hour's teams to process
    # Set only on continue-as-new legs.
    continuation: HourlyRunContinuation | None = None


@frozen
class ExperimentSavedMetricInput:
    """Input to calculate a single experiment-saved metric."""

    experiment_id: int
    metric_uuid: str
    fingerprint: str
    team_id: int | None = None


@dataclasses.dataclass
class ExperimentSavedMetricResult:
    """Result from calculating a single experiment-saved metric."""

    experiment_id: int
    metric_uuid: str
    fingerprint: str
    success: bool
    error_message: str | None = None


@frozen
class SavedMetricsPage:
    """One discovery page of saved metrics, grouped by whole experiments."""

    metrics: list[ExperimentSavedMetricInput]
    # Same cursor semantics as RegularMetricsPage.next_after_experiment_id.
    next_after_experiment_id: int | None


@dataclasses.dataclass
class ExperimentTimeseriesRecalculationWorkflowInputs:
    """Input to the timeseries recalculation workflow."""

    recalculation_id: str  # UUID as string
