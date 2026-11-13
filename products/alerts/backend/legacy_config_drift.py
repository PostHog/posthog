"""The insight rows the legacy config drift report compares with their platform copies."""

from collections.abc import Sequence
from uuid import UUID

from products.alerts.backend.models.alert import AlertConfiguration
from products.alerts_platform.backend.facade.contracts import LegacyCopyExpectation
from products.alerts_platform.backend.facade.enums import PlatformAlertOwner


def insight_copy_expectations(team_id: int | None, after: UUID | None, limit: int) -> Sequence[LegacyCopyExpectation]:
    # Off the startup path, because the evaluation stack imports numpy.
    from products.alerts.backend.platform_source_cycle import platform_upsert_of  # noqa: PLC0415

    rows = AlertConfiguration.objects.filter(owner=PlatformAlertOwner.PLATFORM).select_related("threshold")
    if team_id is not None:
        rows = rows.filter(team_id=team_id)
    if after is not None:
        rows = rows.filter(id__gt=after)
    return [
        LegacyCopyExpectation(legacy_configuration_id=alert.id, team_id=alert.team_id, upsert=platform_upsert_of(alert))
        for alert in rows.order_by("id")[:limit]
    ]
