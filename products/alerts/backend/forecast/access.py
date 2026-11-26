"""The rules for putting an alert on the forecast detector and for running its checks.

The detector is behind the `alerts-forecast-detector` flag for internal use. The flag is checked
on every path that calls the gateway: the alert writers through ``admit_llm_alert_write``, and
the scorer on each scheduled check, so turning the flag off stops the calls.
"""

from typing import Any

import posthoganalytics

from posthog.schema import AlertCalculationInterval, DetectorType

from products.alerts.backend.judge.contract import ForecastDetectorUnavailableError

FORECAST_DETECTOR_FLAG = "alerts-forecast-detector"

FORECAST_DETECTOR_ROLLOUT_MESSAGE = "The forecast detector is not enabled for your account."

FORECAST_DETECTOR_CONSENT_MESSAGE = (
    "The forecast detector sends this insight's data to a model, and AI data processing is turned off "
    "for your organization. Turn it on in organization settings to use this detector."
)

FORECAST_DETECTOR_REAL_TIME_MESSAGE = (
    "The forecast detector cannot run on the real-time cadence. Pick a slower interval, or use a statistical detector."
)

FORECAST_DETECTOR_NO_CREATOR_MESSAGE = (
    "This alert has no creator to check the forecast detector's access for, which happens when that person was "
    "deleted. Recreate the alert to use the forecast detector."
)


def is_forecast_detector_config(detector_config: Any) -> bool:
    return isinstance(detector_config, dict) and detector_config.get("type") == DetectorType.FORECAST.value


def forecast_detector_access_error(*, distinct_id: str, organization: Any) -> str | None:
    """The message to show when this person cannot use the forecast detector in this organization.

    Scoped to the alert's organization, not the person's current one, so a member of several
    organizations cannot borrow a flag-on organization to use the detector in a flag-off one.
    The rollout flag and AI data processing approval are independent, so both are tested.
    """
    enabled = posthoganalytics.feature_enabled(
        FORECAST_DETECTOR_FLAG,
        distinct_id,
        groups={"organization": str(organization.id)},
    )
    if enabled is None:
        raise ForecastDetectorUnavailableError("The forecast detector could not check rollout access.")
    if not enabled:
        return FORECAST_DETECTOR_ROLLOUT_MESSAGE
    if organization.is_ai_data_processing_approved is not True:
        return FORECAST_DETECTOR_CONSENT_MESSAGE
    return None


def forecast_detector_interval_error(calculation_interval: Any) -> str | None:
    """The message to show when a forecast alert is put on the real-time cadence.

    The real-time evaluate budget is too short for a gateway call that can take most of a minute
    when the model is cold.
    """
    if calculation_interval == AlertCalculationInterval.REAL_TIME:
        return FORECAST_DETECTOR_REAL_TIME_MESSAGE
    return None
