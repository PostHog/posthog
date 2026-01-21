import dataclasses


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
