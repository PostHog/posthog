"""What the insight alert API shows for an alert the platform owns.

After the shadow the insight stack stops checking a moved alert, so its row and its checks stop
moving. The platform's runtime rows and check history say where the alert stands instead.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import UTC, datetime, timedelta
from typing import Final
from uuid import NAMESPACE_URL, UUID, uuid5

from posthog.exceptions_capture import capture_exception
from posthog.schema_enums import AlertState
from posthog.utils import ensure_utc

from products.alerts.backend.facade.contracts import (
    MovedAlertCheck,
    MovedAlertCheckPage,
    MovedAlertLastCheck,
    MovedAlertRuntime,
    MovedAlertStatus,
)
from products.alerts.backend.models.alert import AlertConfiguration
from products.alerts.backend.platform_cutover import insight_state_of_platform
from products.alerts_platform.backend.facade.api import (
    check_page_by_legacy_id,
    last_check_by_legacy_id,
    runtime_by_legacy_id,
)
from products.alerts_platform.backend.facade.contracts import PlatformCheckEntry
from products.alerts_platform.backend.facade.enums import PlatformAlertOwner, PlatformAlertState

_EARLIEST: Final = datetime(1970, 1, 1, tzinfo=UTC)
_LATEST: Final = datetime(2100, 1, 1, tzinfo=UTC)


def moved_alert_statuses(*, team_id: int, alert_ids: Sequence[UUID], now: datetime) -> dict[UUID, MovedAlertStatus]:
    """Each moved alert's state, schedule and last check as the platform has them.

    Alerts the platform does not own are left out. Up to three Postgres queries and one ClickHouse
    query. A ClickHouse failure leaves out the last check, and the response still goes out.
    """
    snoozed_until = dict(
        AlertConfiguration.objects.filter(
            team_id=team_id, id__in=alert_ids, owner=PlatformAlertOwner.PLATFORM
        ).values_list("id", "snoozed_until")
    )
    if not snoozed_until:
        return {}
    moved = list(snoozed_until)
    runtime = runtime_by_legacy_id(team_id=team_id, legacy_configuration_ids=moved)
    try:
        last_checks = last_check_by_legacy_id(team_id=team_id, legacy_configuration_ids=moved)
    except Exception as error:
        capture_exception(error, additional_properties={"team_id": team_id})
        last_checks = {}
    statuses = {}
    for alert_id in moved:
        alert_runtime = runtime.get(alert_id)
        last_check = last_checks.get(alert_id)
        statuses[alert_id] = MovedAlertStatus(
            runtime=MovedAlertRuntime(
                state=insight_state_of_platform(alert_runtime.state, snoozed_until=snoozed_until[alert_id], at=now),
                next_check_at=alert_runtime.next_check_at,
                last_notified_at=alert_runtime.last_notified_at,
            )
            if alert_runtime is not None
            else None,
            last_check=MovedAlertLastCheck(checked_at=ensure_utc(last_check.checked_at), value=last_check.value)
            if last_check is not None
            else None,
        )
    return statuses


def moved_alert_check_page(
    *,
    team_id: int,
    alert_id: UUID,
    since: datetime | None,
    until: datetime | None,
    limit: int,
    offset: int,
) -> MovedAlertCheckPage | None:
    """A page of a moved alert's checks in `[since, until]`, newest first, with how many the window holds.

    None when the alert's own checks are the ones to show: the platform does not own it, or its
    history could not be read.
    """
    if not AlertConfiguration.objects.filter(team_id=team_id, id=alert_id, owner=PlatformAlertOwner.PLATFORM).exists():
        return None
    try:
        page = check_page_by_legacy_id(
            team_id=team_id,
            legacy_configuration_id=alert_id,
            since=since or _EARLIEST,
            # The platform's window leaves out its end, and the API's keeps a check made at that moment.
            until=until + timedelta(microseconds=1) if until is not None else _LATEST,
            limit=limit,
            offset=offset,
        )
    except Exception as error:
        capture_exception(error, additional_properties={"alert_configuration_id": str(alert_id)})
        return None
    if page is None:
        return None
    return MovedAlertCheckPage(total=page.total, checks=tuple(_as_check(alert_id, check) for check in page.checks))


def _as_check(alert_id: UUID, check: PlatformCheckEntry) -> MovedAlertCheck:
    return MovedAlertCheck(
        id=uuid5(NAMESPACE_URL, f"{alert_id}|{check.evaluation_key}"),
        checked_at=ensure_utc(check.occurred_at),
        value=check.value,
        # A snoozed check evaluated nothing, so it shows as snoozed rather than as a clear outcome.
        state=AlertState.SNOOZED
        if check.state == PlatformAlertState.SNOOZED
        else insight_state_of_platform(check.state, snoozed_until=None, at=check.occurred_at),
        error_message=check.error_message or None,
    )
