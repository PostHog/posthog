"""An insight alert's `AlertCheck` rows, as the platform's history copies them.

The alert page reads a moved alert's checks only from the platform's history, so a check the insight
stack made before the platform's first check of the alert shows nowhere once its row is deleted. The
copy keeps what the page shows of it: the value, state, error and the detector's anomaly points,
which the platform keeps in `source_detail` under the keys it writes for its own checks.

Two things are left out. An investigation stays on the check row, because a copied one would join
the investigations the platform's claim and episode budget count. A delivery record stays too, as the
page shows none for a platform check.
"""

from collections.abc import Iterable
from typing import Any, Final
from uuid import UUID

from posthog.schema_enums import AlertState

from products.alerts.backend.models.alert import AlertCheck, AlertConfiguration
from products.alerts.backend.platform_cutover import PLATFORM_HANDOVER_STATE
from products.alerts.backend.platform_investigation_detail import SUPPRESSED_BY_AGENT_KEY
from products.alerts.backend.platform_source_cycle import ERROR_CODE_KEY
from products.alerts_platform.backend.facade.contracts import AlertEventKind, LegacyAlertHistory, LegacyHistoryEntry
from products.alerts_platform.backend.facade.enums import PlatformAlertState

_CHUNK: Final = 2_000

_DETAIL_FIELDS: Final = ("anomaly_scores", "triggered_points", "triggered_dates", "interval", "triggered_metadata")

LEFT_OUT_INVESTIGATION: Final = "investigation"
LEFT_OUT_DELIVERY: Final = "delivery record"


def team_alert_ids(team_id: int) -> Iterable[UUID]:
    return AlertConfiguration.objects.filter(team_id=team_id).order_by("id").values_list("id", flat=True).iterator()


def check_history(team_id: int, alert_id: UUID) -> LegacyAlertHistory:
    checks = AlertCheck.objects.filter(alert_configuration_id=alert_id, alert_configuration__team_id=team_id).order_by(
        "created_at", "id"
    )
    entries: list[LegacyHistoryEntry] = []
    left_out = {LEFT_OUT_INVESTIGATION: 0, LEFT_OUT_DELIVERY: 0}
    previous: PlatformAlertState | None = None
    for check in checks.iterator(chunk_size=_CHUNK):
        state = _platform_state(check.state)
        entries.append(
            LegacyHistoryEntry(
                legacy_id=check.id,
                kind=AlertEventKind.CHECK,
                occurred_at=check.created_at,
                # The oldest check has nothing before it, so it reads as moving nothing.
                previous_state=previous or state,
                state=state,
                value=check.calculated_value,
                error_message=_error_message(check.error),
                source_detail=_detail(check),
            )
        )
        previous = state
        if check.investigation_status is not None:
            left_out[LEFT_OUT_INVESTIGATION] += 1
        if check.targets_notified:
            left_out[LEFT_OUT_DELIVERY] += 1
    return LegacyAlertHistory(entries=tuple(entries), left_out=left_out)


def _platform_state(state: str) -> PlatformAlertState:
    if state == AlertState.SNOOZED:
        return PlatformAlertState.SNOOZED
    return PLATFORM_HANDOVER_STATE.get(state, PlatformAlertState.NOT_FIRING)


def _error_message(error: Any) -> str | None:
    message = error.get("message") if isinstance(error, dict) else None
    return message if isinstance(message, str) and message else None


def _detail(check: AlertCheck) -> dict[str, Any]:
    detail: dict[str, Any] = {field: getattr(check, field) for field in _DETAIL_FIELDS}
    if isinstance(check.error, dict):
        detail[ERROR_CODE_KEY] = check.error.get("code")
    detail[SUPPRESSED_BY_AGENT_KEY] = check.notification_suppressed_by_agent
    return {key: value for key, value in detail.items() if value}
