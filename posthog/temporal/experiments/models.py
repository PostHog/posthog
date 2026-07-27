import dataclasses

# Temporal retry ceiling for the per-metric calc activities. Shared with the activity code, which emits the
# terminal `experiment metric error` analytics event only on the final attempt — keep the RetryPolicy in
# workflows.py and this constant in lockstep or terminal failures get emitted early / not at all.
TIMESERIES_METRIC_MAX_ATTEMPTS = 3


@dataclasses.dataclass
class ExperimentRegularMetricsWorkflowInputs:
    """Input to the hourly workflow."""

    hour: int  # 0-23, which hour's teams to process


@dataclasses.dataclass
class ExperimentRegularMetricInput:
    """Input to calculate a single experiment-metric."""

    experiment_id: int
    metric_uuid: str
    fingerprint: str


@dataclasses.dataclass
class ExperimentRegularMetricResult:
    """Result from calculating a single experiment-metric."""

    experiment_id: int
    metric_uuid: str
    fingerprint: str
    success: bool
    error_message: str | None = None


@dataclasses.dataclass
class ExperimentSavedMetricsWorkflowInputs:
    """Input to the hourly saved metrics workflow."""

    hour: int  # 0-23, which hour's teams to process


@dataclasses.dataclass
class ExperimentSavedMetricInput:
    """Input to calculate a single experiment-saved metric."""

    experiment_id: int
    metric_uuid: str
    fingerprint: str


@dataclasses.dataclass
class ExperimentSavedMetricResult:
    """Result from calculating a single experiment-saved metric."""

    experiment_id: int
    metric_uuid: str
    fingerprint: str
    success: bool
    error_message: str | None = None


@dataclasses.dataclass
class ExperimentTimeseriesRecalculationWorkflowInputs:
    """Input to the timeseries recalculation workflow."""

    recalculation_id: str  # UUID as string
