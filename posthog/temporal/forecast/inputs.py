from dataclasses import dataclass

DEFAULT_LOOKBACK_WINDOW = 180


@dataclass
class ForecastWorkflowInputs:
    team_id: int
    alert_id: str
    insight_id: int
    series_indices: list[int]
    confidence_level: float
    forecast_horizon: int
    min_historical_points: int
    lookback_window: int = DEFAULT_LOOKBACK_WINDOW


@dataclass
class FetchHistoricalDataInputs:
    team_id: int
    insight_id: int
    series_indices: list[int]
    min_historical_points: int
    lookback_window: int = DEFAULT_LOOKBACK_WINDOW


@dataclass
class HistoricalDataResult:
    series_index: int
    breakdown_value: dict | None
    timestamps: list[str]
    values: list[float]


@dataclass
class GenerateForecastInputs:
    historical_data: list[dict]
    confidence_level: float
    forecast_horizon: int


@dataclass
class ForecastPrediction:
    series_index: int
    breakdown_value: dict | None
    forecast_timestamp: str
    predicted_value: float
    lower_bound: float
    upper_bound: float
    confidence_level: float
    historical_data_hash: str


@dataclass
class StoreForecastInputs:
    team_id: int
    alert_id: str
    forecasts: list[dict]


@dataclass
class ForecastWorkflowResult:
    success: bool
    forecast_count: int
    error: str | None = None


@dataclass
class BackfillForecastWorkflowInputs:
    team_id: int
    alert_id: str
    insight_id: int
    series_index: int
    confidence_level: float
    max_forecasts: int = DEFAULT_LOOKBACK_WINDOW
    min_context: int = 14
    lookback_window: int = DEFAULT_LOOKBACK_WINDOW


@dataclass
class BackfillForecastInputs:
    """Inputs for the backfill forecast generation activity."""

    team_id: int
    alert_id: str
    series_index: int
    confidence_level: float
    historical_values: list[float]
    timestamps: list[str]
    breakdown_value: dict | None
    max_forecasts: int
    min_context: int
    lookback_window: int


@dataclass
class BackfillForecastWorkflowResult:
    success: bool
    forecasts_created: int
    checks_created: int
    error: str | None = None
