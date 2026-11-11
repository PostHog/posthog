"""What an alert list shows beside each configuration: its creator, its last check, its state over the
last day and where it notifies. Read for a whole page at once, so a page costs a fixed number of queries.
"""

from collections.abc import Sequence
from datetime import UTC, datetime, timedelta
from typing import Final
from uuid import UUID

from django.utils import timezone

import structlog

from posthog.dataclasses import frozen
from posthog.exceptions_capture import capture_exception
from posthog.models import User

from products.alerts_platform.backend.facade import api as platform_api
from products.alerts_platform.backend.facade.contracts import (
    PlatformAlertConfigurationView,
    PlatformAlertHistory,
    PlatformControlHistory,
    PlatformLastCheck,
    StateInterval,
)
from products.alerts_platform.backend.facade.enums import PlatformAlertState

logger = structlog.get_logger(__name__)

STATE_TIMELINE_LOOKBACK: Final = timedelta(hours=24)


@frozen
class ConfigurationExtras:
    created_by: User | None
    last_checked_at: datetime | None
    last_error_message: str | None
    state_timeline: tuple[StateInterval, ...]
    destination_types: tuple[str, ...]


def list_extras(
    *, team_id: int, configurations: Sequence[PlatformAlertConfigurationView]
) -> dict[UUID, ConfigurationExtras]:
    if not configurations:
        return {}
    ids = [configuration.id for configuration in configurations]
    window_end = timezone.now().astimezone(UTC)
    window = (window_end - STATE_TIMELINE_LOOKBACK, window_end)

    creator_ids = {configuration.created_by_id for configuration in configurations if configuration.created_by_id}
    creators = {user.id: user for user in User.objects.filter(id__in=creator_ids)} if creator_ids else {}
    destination_types = platform_api.destination_types_by_configuration(team_id=team_id, configuration_ids=ids)

    # Check history lives in ClickHouse. When it cannot be read, the list still loads, without it.
    last_checks: dict[UUID, PlatformLastCheck] = {}
    histories: dict[UUID, PlatformAlertHistory] = {}
    controls: dict[UUID, PlatformControlHistory] = {}
    try:
        last_checks, histories, controls = platform_api.alert_list_history(
            team_id=team_id, configuration_ids=ids, since=window[0], until=window[1]
        )
    except Exception as error:
        logger.warning("platform_alert_list_history_unavailable", team_id=team_id)
        capture_exception(error)

    return {
        configuration.id: ConfigurationExtras(
            created_by=creators.get(configuration.created_by_id) if configuration.created_by_id else None,
            last_checked_at=last_checks[configuration.id].checked_at if configuration.id in last_checks else None,
            last_error_message=histories[configuration.id].last_error_message
            if configuration.id in histories
            else None,
            state_timeline=platform_api.state_timeline(
                history=histories.get(configuration.id),
                control=controls.get(configuration.id),
                current_group_states={
                    alert.grouping_key: PlatformAlertState(alert.state) for alert in configuration.alerts
                },
                current_enabled=configuration.enabled,
                snooze_until=configuration.snooze_until,
                window=window,
            ),
            destination_types=destination_types.get(configuration.id, ()),
        )
        for configuration in configurations
    }
