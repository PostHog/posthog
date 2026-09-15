"""Per-team cap on how many enabled AI-detector alerts a team can have.

Every check of an AI-detector alert costs a model call, so the cap is the cost
control for the type. It lives in the `alerts-llm-detector` flag payload rather than
in code so the launch posture is tunable without a deploy, the same way the Signals
scout budgets work (`products/signals/backend/scout_harness/team_limits.py`).
"""

import json

from django.db import connection

import posthoganalytics

from posthog.schema import DetectorType

from posthog.exceptions_capture import capture_exception

LLM_DETECTOR_FLAG = "alerts-llm-detector"

# Key inside the flag payload that overrides `DEFAULT_MAX_LLM_ALERTS_PER_TEAM`.
PAYLOAD_MAX_ALERTS_KEY = "max_llm_alerts_per_team"

# Applies when the payload is absent, malformed, or unreadable. Deliberately small:
# a team that wants more asks, and the flag grants it with no deploy.
DEFAULT_MAX_LLM_ALERTS_PER_TEAM = 5

_LLM_ALERT_LIMIT_LOCK_NAMESPACE = 1_277_970_509


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
