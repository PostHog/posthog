"""What the insight alert API shows for an alert the platform owns.

After the shadow the insight stack stops checking a moved alert, so its row and its checks stop
moving. The platform's runtime rows and check history say where the alert stands instead.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import UTC, datetime, timedelta
from typing import Final
from uuid import NAMESPACE_URL, uuid5

from posthog.exceptions_capture import capture_exception
from posthog.utils import ensure_utc

from products.alerts.backend.insight_alert_state_machine import apply_platform_state
from products.alerts.backend.models.alert import AlertCheck, AlertConfiguration
from products.alerts.backend.platform_cutover import insight_state_of_platform
from products.alerts_platform.backend.facade.api import (
    check_page_by_legacy_id,
    history_by_legacy_id,
    runtime_by_legacy_id,
)
from products.alerts_platform.backend.facade.contracts import PlatformCheckEntry

# Long enough to hold the last check of a monthly alert.
LAST_CHECK_WINDOW: Final = timedelta(days=32)
_EARLIEST: Final = datetime(1970, 1, 1, tzinfo=UTC)
_LATEST: Final = datetime(2100, 1, 1, tzinfo=UTC)


def with_platform_runtime(alerts: Sequence[AlertConfiguration], *, now: datetime) -> None:
    """Shows each moved alert's state, schedule and last check as the platform has them, in place.

    One Postgres query, and one ClickHouse query when the alerts include a moved one. A ClickHouse
    failure leaves the last check as the insight row has it, and the response still goes out.
    """
    moved = [alert for alert in alerts if alert.platform_owned]
    if not moved:
        return
    team_id = moved[0].team_id
    alert_ids = [alert.id for alert in moved]
    runtime = runtime_by_legacy_id(team_id=team_id, legacy_configuration_ids=alert_ids)
    try:
        history = history_by_legacy_id(
            team_id=team_id, legacy_configuration_ids=alert_ids, since=now - LAST_CHECK_WINDOW, until=now
        )
    except Exception as error:
        capture_exception(error, additional_properties={"team_id": team_id})
        history = {}
    for alert in moved:
        if (alert_runtime := runtime.get(alert.id)) is not None:
            apply_platform_state(
                alert, insight_state_of_platform(alert_runtime.state, snoozed_until=alert.snoozed_until, at=now)
            )
            alert.next_check_at = alert_runtime.next_check_at
            alert.last_notified_at = alert_runtime.last_notified_at
        if (alert_history := history.get(alert.id)) is not None:
            alert.last_checked_at = ensure_utc(alert_history.last_checked_at)
            # Annotated from the alert's own checks, which stop once the shadow ends.
            alert.last_value = alert_history.last_value  # type: ignore[attr-defined]


def platform_checks(
    alert: AlertConfiguration, *, since: datetime | None, until: datetime | None, limit: int, offset: int
) -> tuple[int, list[AlertCheck]] | None:
    """A page of a moved alert's checks in `[since, until]`, newest first, with how many the window holds.

    None when the alert's own checks are the ones to show: the platform does not own it, or its
    history could not be read.
    """
    if not alert.platform_owned:
        return None
    try:
        page = check_page_by_legacy_id(
            team_id=alert.team_id,
            legacy_configuration_id=alert.id,
            since=since or _EARLIEST,
            # The platform's window leaves out its end, and the API's keeps a check made at that moment.
            until=until + timedelta(microseconds=1) if until is not None else _LATEST,
            limit=limit,
            offset=offset,
        )
    except Exception as error:
        capture_exception(error, additional_properties={"alert_configuration_id": str(alert.id)})
        return None
    if page is None:
        return None
    return page.total, [_as_check(alert, check) for check in page.checks]


def _as_check(alert: AlertConfiguration, check: PlatformCheckEntry) -> AlertCheck:
    # Never saved. It carries what the check serializer shows, with an id that stays the same on every read.
    return AlertCheck(
        id=uuid5(NAMESPACE_URL, f"{alert.id}|{check.evaluation_key}"),
        alert_configuration=alert,
        created_at=ensure_utc(check.occurred_at),
        calculated_value=check.value,
        condition=alert.condition,
        state=insight_state_of_platform(check.state, snoozed_until=None, at=check.occurred_at),
        error={"message": check.error_message} if check.error_message else None,
        targets_notified={},
    )
