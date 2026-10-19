from functools import cache
from typing import TYPE_CHECKING

import numpy as np

from posthog.hogql.errors import QueryError
from posthog.hogql.functions.forecast import ForecastCall

from posthog.ph_client import feature_enabled_or_false

if TYPE_CHECKING:
    from timestral import TimestralForecaster

    from posthog.models.team import Team

MODEL = "mistralai/Timestral-28M"
MAX_CONTEXT = 32768
QUANTILES = (0.1, 0.5, 0.9)


def validate_forecast_access(team: "Team") -> None:
    if not feature_enabled_or_false(
        "hogql-forecast",
        str(team.uuid),
        groups={"organization": str(team.organization_id), "project": str(team.id)},
        group_properties={"organization": {"id": str(team.organization_id)}, "project": {"id": str(team.id)}},
        send_feature_flag_events=False,
    ):
        raise QueryError("forecast is not available for this project yet.")


@cache
def _model() -> "TimestralForecaster":
    from timestral import TimestralForecaster  # noqa: PLC0415 — keeps torch off the HogQL import path

    return TimestralForecaster.from_pretrained(MODEL, device="cpu")


def evaluate_forecast(spec: ForecastCall, values: list[object]) -> list[object]:
    series = {
        i: [np.nan if x is None else x for x in value[-MAX_CONTEXT:]]
        for i, value in enumerate(values)
        if isinstance(value, list | tuple) and len(value) >= 2
    }
    out: list[object] = [[] for _ in values]
    if not series:
        return out
    # One batch for every row. Timestral reads NaN as missing, so shorter series are padded on the left.
    width = max(len(s) for s in series.values())
    context = np.full((len(series), width), np.nan)
    try:
        for row, s in enumerate(series.values()):
            context[row, width - len(s) :] = s
    except (TypeError, ValueError) as error:
        raise QueryError("forecast values must be an array of numbers.") from error
    result = _model().forecast(context, prediction_length=spec.horizon)
    bands = np.stack([np.asarray(result.quantile(q)).reshape(len(series), spec.horizon) for q in QUANTILES], axis=-1)
    for row, i in enumerate(series):
        out[i] = [tuple(float(v) for v in step) for step in bands[row]]
    return out
