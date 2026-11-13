"""Creating an appearance alert together with its destinations, so a half-made alert never runs."""

from collections.abc import Sequence
from typing import Any

from django.db import transaction

from posthog.models.scoping import team_scope

from products.alerts_platform.backend.facade.contracts import (
    APPEARANCE_GROUPING,
    NewAlertDestination,
    PlatformAlertConfigurationEdit,
    PlatformAlertConfigurationView,
    SourceKind,
)
from products.alerts_platform.backend.facade.enums import PlatformAlertKind
from products.alerts_platform.backend.logic import alert_destinations, platform_writes, source_configs


def create_appearance_alert(
    *,
    team_id: int,
    source: SourceKind,
    name: str,
    filters: Sequence[dict[str, Any]],
    destinations: Sequence[NewAlertDestination],
    created_by_id: int | None,
) -> PlatformAlertConfigurationView:
    edit = PlatformAlertConfigurationEdit(
        name=name,
        enabled=True,
        source_config={"filters": list(filters)},
        grouping=APPEARANCE_GROUPING,
        schedule_restriction=None,
        evaluation_periods=1,
        datapoints_to_alarm=1,
        cooldown_minutes=0,
    )
    with team_scope(team_id), transaction.atomic():
        view = platform_writes.create_configuration(
            team_id=team_id,
            source_kind=source,
            edit=edit,
            created_by_id=created_by_id,
            alert_kind=PlatformAlertKind.APPEARANCE,
        )
        alert_destinations.create_alert_destinations(
            team_id=team_id, configuration_id=view.id, destinations=destinations
        )
    return view


def create_warning(team_id: int, source: SourceKind) -> str | None:
    spec = source_configs.spec(source, PlatformAlertKind.APPEARANCE)
    if spec is None or spec.create_warning is None:
        return None
    return spec.create_warning(team_id)
