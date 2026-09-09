"""Per-team cap on how many enabled AI-detector alerts a team can have.

Every check of an AI-detector alert costs a model call, so the cap is the cost
control for the type. It lives in the `alerts-llm-detector` flag payload rather than
in code so the launch posture is tunable without a deploy, the same way the Signals
scout budgets work (`products/signals/backend/scout_harness/team_limits.py`).
"""

import json
from typing import Any

from django.db import connection

import posthoganalytics

from posthog.schema import AlertCalculationInterval, DetectorType

from posthog.exceptions_capture import capture_exception

LLM_DETECTOR_FLAG = "alerts-llm-detector"

# Key inside the flag payload that overrides `DEFAULT_MAX_LLM_ALERTS_PER_TEAM`.
PAYLOAD_MAX_ALERTS_KEY = "max_llm_alerts_per_team"

# Applies when the payload is absent, malformed, or unreadable. Deliberately small:
# a team that wants more asks, and the flag grants it with no deploy.
DEFAULT_MAX_LLM_ALERTS_PER_TEAM = 5

_LLM_ALERT_LIMIT_LOCK_NAMESPACE = 1_277_970_509

# A model call per tick on the finest cadence is a cost profile we don't want to ship
# before there's a budget model, and the real-time evaluate budget (3 minutes, 2 attempts)
# leaves little room for one.
LLM_DETECTOR_REAL_TIME_MESSAGE = (
    "The AI detector cannot run on the real-time cadence. Pick a slower interval, or use a statistical detector."
)

LLM_DETECTOR_CONSENT_MESSAGE = (
    "The AI detector sends this insight's data to a model, and AI data processing is turned off "
    "for your organization. Turn it on in organization settings to use this detector."
)


def is_llm_detector_config(detector_config: Any) -> bool:
    return isinstance(detector_config, dict) and detector_config.get("type") == DetectorType.LLM.value


def llm_detector_interval_error(calculation_interval: Any) -> str | None:
    """The message to show when an AI-detector alert is put on the real-time cadence."""
    if calculation_interval == AlertCalculationInterval.REAL_TIME:
        return LLM_DETECTOR_REAL_TIME_MESSAGE
    return None


def llm_alert_limit_error(*, team_id: int, exclude_alert_id: str | None) -> str | None:
    """The message to show when enabling one more AI-detector alert would pass the team cap.

    Call inside a transaction that holds ``lock_llm_alert_limit`` for the team, and only
    when the write would add an enabled AI alert: an alert that is already enabled and
    already AI-judged adds no spend, so editing it must never trip the cap, even when the
    cap was lowered beneath the current count.
    """
    cap = max_llm_alerts_per_team()
    existing = count_enabled_llm_alerts(team_id=team_id, exclude_alert_id=exclude_alert_id)
    if existing >= cap:
        return (
            f"This project already has {existing} of {cap} alerts using the AI detector. "
            "Turn one off, or ask us to raise the limit."
        )
    return None


def lock_llm_alert_limit(*, team_id: int) -> None:
    """Serialize the count and write for one team's enabled AI alerts."""
    with connection.cursor() as cursor:
        cursor.execute("SELECT pg_advisory_xact_lock(%s, %s)", [_LLM_ALERT_LIMIT_LOCK_NAMESPACE, team_id])


# Fixed distinct_id for the payload read — the cap is per team, not per person, and the
# flag must be served for this id for the payload to be readable at all.
_PAYLOAD_DISTINCT_ID = "internal_alerts_llm_detector_limits"


def max_llm_alerts_per_team() -> int:
    """The cap, from the flag payload, falling back to the code default.

    A read error never blocks alert editing: it resolves to the default, which is
    stricter than any value the payload is likely to carry.
    """
    payload = _read_payload()
    raw = (payload or {}).get(PAYLOAD_MAX_ALERTS_KEY)
    if isinstance(raw, bool) or not isinstance(raw, int) or raw < 0:
        return DEFAULT_MAX_LLM_ALERTS_PER_TEAM
    return raw


def count_enabled_llm_alerts(*, team_id: int, exclude_alert_id: str | None = None) -> int:
    """How many enabled AI-detector alerts the team already has.

    ``exclude_alert_id`` leaves the alert being edited out of its own count, so saving an
    unrelated change to an existing AI alert while the team sits at the cap still works.
    """
    # Imported here to keep this module importable from the serializer without pulling the
    # alert model's own import graph into every reader of the cap.
    from products.alerts.backend.models.alert import AlertConfiguration  # noqa: PLC0415

    queryset = AlertConfiguration.objects.filter(
        team_id=team_id, enabled=True, detector_config__type=DetectorType.LLM.value
    )
    if exclude_alert_id is not None:
        queryset = queryset.exclude(id=exclude_alert_id)
    return queryset.count()


def _read_payload() -> dict | None:
    try:
        payload = posthoganalytics.get_feature_flag_payload(LLM_DETECTOR_FLAG, _PAYLOAD_DISTINCT_ID, match_value=True)
        if isinstance(payload, str):
            payload = json.loads(payload)
        return payload if isinstance(payload, dict) else None
    except Exception as error:
        capture_exception(error)
        return None
