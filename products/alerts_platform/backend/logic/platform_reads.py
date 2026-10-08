"""Reads of the shared alert tables, as a consumer outside this product sees them.

Separate from `platform_lifecycle`, which serves the source adapters. These serve a reader
outside the product, so they return views rather than rows and never change one.
"""

from collections.abc import Sequence
from uuid import UUID

from django.db.models import Prefetch, QuerySet

from products.alerts_platform.backend.facade.contracts import (
    PlatformAlertConfigurationPage,
    PlatformAlertConfigurationView,
    PlatformAlertSnapshot,
)
from products.alerts_platform.backend.models import PlatformAlert, PlatformAlertConfiguration


def instance_view(alert: PlatformAlert) -> PlatformAlertSnapshot:
    """One instance row as a contract. Shared with the test doors, so both describe one shape."""
    return PlatformAlertSnapshot(
        id=alert.id,
        grouping_key=alert.grouping_key,
        state=alert.state,
        firing_started_at=alert.firing_started_at,
        last_notified_at=alert.last_notified_at,
        snooze_until=alert.snooze_until,
    )


def _configuration_view(configuration: PlatformAlertConfiguration) -> PlatformAlertConfigurationView:
    return PlatformAlertConfigurationView(
        id=configuration.id,
        name=configuration.name,
        enabled=configuration.enabled,
        source_kind=configuration.source_kind,
        source_config=configuration.source_config,
        check_interval_minutes=configuration.check_interval_minutes,
        recurrence_unit=configuration.recurrence_unit,
        anchor_time=configuration.anchor_time,
        evaluation_periods=configuration.evaluation_periods,
        datapoints_to_alarm=configuration.datapoints_to_alarm,
        cooldown_minutes=configuration.cooldown_minutes,
        schedule_restriction=configuration.schedule_restriction,
        next_check_at=configuration.next_check_at,
        consecutive_failures=configuration.consecutive_failures,
        legacy_configuration_id=configuration.legacy_configuration_id,
        created_at=configuration.created_at,
        updated_at=configuration.updated_at,
        alerts=tuple(instance_view(alert) for alert in configuration.alerts.all()),
    )


def _readable(team_id: int, source_kinds: Sequence[str]) -> QuerySet[PlatformAlertConfiguration]:
    """Configurations of the given kinds belonging to `team_id`, instances prefetched.

    The caller resolves which kinds it may read, because that depends on the caller's grants
    rather than on anything this product knows.
    """
    instances = PlatformAlert.objects.for_team(team_id, canonical=True).order_by("grouping_key")
    return (
        PlatformAlertConfiguration.objects.for_team(team_id, canonical=True)
        .filter(source_kind__in=list(source_kinds))
        .prefetch_related(Prefetch("alerts", queryset=instances))
        .order_by("-created_at", "-id")
    )


def list_configurations(
    *, team_id: int, source_kinds: Sequence[str], limit: int, offset: int
) -> PlatformAlertConfigurationPage:
    """One page of configurations, newest first, with the total behind it.

    The page is taken in the database rather than in the caller, so a team with many alerts
    costs one page rather than all of them. Slicing keeps the prefetch, which resolves over the
    page's rows alone.
    """
    readable = _readable(team_id, source_kinds)
    return PlatformAlertConfigurationPage(
        configurations=tuple(_configuration_view(row) for row in readable[offset : offset + limit]),
        total=readable.count(),
    )


def get_configuration(
    *, team_id: int, source_kinds: Sequence[str], configuration_id: UUID
) -> PlatformAlertConfigurationView | None:
    """One configuration, or None when it does not exist or the caller may not read its kind."""
    row = _readable(team_id, source_kinds).filter(id=configuration_id).first()
    return None if row is None else _configuration_view(row)
