"""Alerts that belong to an organization, not to one of its projects.

Each row has a home team, which runs its checks, but a caller names the organization. The caller
checks that its user may read the organization's alerts. This module only keeps one organization
from reaching another's rows, and holds the settings the source does not expose at fixed values.
"""

from collections.abc import Callable
from dataclasses import replace
from datetime import datetime, timedelta
from typing import Final
from uuid import UUID

from django.utils import timezone as django_timezone

from posthog.models.team import Team

from products.alerts_platform.backend.facade.contracts import (
    ORGANIZATION_SOURCE_KINDS,
    Grouping,
    InvalidPlatformAlertEdit,
    OrganizationAlertSettings,
    PlatformAlertConfigurationEdit,
    PlatformAlertConfigurationPage,
    PlatformAlertConfigurationView,
    PlatformAlertNotEditable,
    SourceKind,
)
from products.alerts_platform.backend.logic import platform_reads, platform_writes, source_configs
from products.alerts_platform.backend.models import PlatformAlertConfiguration

# The platform API's longest snooze, so a mute set through a source's API cannot outlast one set there.
MAX_MUTE: Final = timedelta(days=30)


def create_configuration(
    *,
    organization_id: UUID,
    team_id: int,
    source_kind: SourceKind,
    settings: OrganizationAlertSettings,
    created_by_id: int | None,
) -> PlatformAlertConfigurationView:
    _require_organization_kind(source_kind)
    spec = source_configs.spec(source_kind)
    # Without a native lifecycle, a create would go through the source's own hook and make a source row.
    if spec is None or spec.native is None:
        raise PlatformAlertNotEditable(f"{source_kind} alerts cannot be created through this API.")
    if not Team.objects.filter(id=team_id, organization_id=organization_id).exists():
        raise InvalidPlatformAlertEdit("team_id", "The project is not in this organization.")
    return platform_writes.create_configuration(
        team_id=team_id,
        source_kind=source_kind,
        edit=PlatformAlertConfigurationEdit(
            name=settings.name,
            enabled=settings.enabled,
            source_config=settings.source_config,
            grouping=Grouping(),
            schedule_restriction=None,
            evaluation_periods=1,
            datapoints_to_alarm=1,
            cooldown_minutes=0,
        ),
        created_by_id=created_by_id,
        natively=True,
    )


def list_configurations(
    *, organization_id: UUID, source_kind: SourceKind, limit: int, offset: int
) -> PlatformAlertConfigurationPage:
    _require_organization_kind(source_kind)
    return platform_reads.list_organization_configurations(
        organization_id=organization_id, source_kind=source_kind.value, limit=limit, offset=offset
    )


def get_configuration(
    *, organization_id: UUID, source_kind: SourceKind, configuration_id: UUID
) -> PlatformAlertConfigurationView | None:
    team_id = _home_team_id(organization_id, source_kind, configuration_id)
    if team_id is None:
        return None
    return platform_reads.get_configuration(
        team_id=team_id, source_kinds=[source_kind.value], configuration_id=configuration_id
    )


def update_configuration(
    *,
    organization_id: UUID,
    source_kind: SourceKind,
    configuration_id: UUID,
    change: Callable[[OrganizationAlertSettings], OrganizationAlertSettings],
) -> PlatformAlertConfigurationView | None:
    def apply(current: PlatformAlertConfigurationEdit) -> PlatformAlertConfigurationEdit:
        changed = change(
            OrganizationAlertSettings(name=current.name, enabled=current.enabled, source_config=current.source_config)
        )
        return replace(current, name=changed.name, enabled=changed.enabled, source_config=changed.source_config)

    team_id = _home_team_id(organization_id, source_kind, configuration_id)
    if team_id is None:
        return None
    # The source's own API makes every write here, so its checks have already run.
    return platform_writes.update_configuration(
        team_id=team_id,
        source_kinds=[source_kind.value],
        configuration_id=configuration_id,
        change=apply,
        source_checked=True,
    )


def mute_configuration(
    *, organization_id: UUID, source_kind: SourceKind, configuration_id: UUID, until: datetime | None
) -> PlatformAlertConfigurationView | None:
    if until is not None:
        now = django_timezone.now()
        if until <= now:
            raise InvalidPlatformAlertEdit("until", "Pick a time in the future, or None to unmute.")
        if until > now + MAX_MUTE:
            raise InvalidPlatformAlertEdit("until", f"An alert can be muted for up to {MAX_MUTE.days} days.")
    team_id = _home_team_id(organization_id, source_kind, configuration_id)
    if team_id is None:
        return None
    return platform_writes.update_configuration(
        team_id=team_id,
        source_kinds=[source_kind.value],
        configuration_id=configuration_id,
        change=lambda current: current,
        snooze_until=until,
        snooze_changed=True,
    )


def delete_configuration(*, organization_id: UUID, source_kind: SourceKind, configuration_id: UUID) -> bool:
    team_id = _home_team_id(organization_id, source_kind, configuration_id)
    if team_id is None:
        return False
    return platform_writes.delete_configuration(
        team_id=team_id, source_kinds=[source_kind.value], configuration_id=configuration_id
    )


def _require_organization_kind(source_kind: SourceKind) -> None:
    if source_kind not in ORGANIZATION_SOURCE_KINDS:
        raise PlatformAlertNotEditable(f"{source_kind} alerts belong to a project, not an organization.")


def _home_team_id(organization_id: UUID, source_kind: SourceKind, configuration_id: UUID) -> int | None:
    _require_organization_kind(source_kind)
    return (
        PlatformAlertConfiguration.objects.unscoped()
        .filter(id=configuration_id, source_kind=source_kind.value, team__organization_id=organization_id)
        .values_list("team_id", flat=True)
        .first()
    )
