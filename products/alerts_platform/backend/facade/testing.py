"""Test doors for a source's own tests.

A source's tests set a configuration up and read back what a check decided. Both are rows this
product owns, so they cross as snapshots and ids rather than as model instances. A source's tests
also check its comparison correspondence here, because the platform cannot list its sources.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import fields
from datetime import datetime
from typing import Any
from uuid import UUID

from products.alerts_platform.backend.facade.contracts import (
    DeliveryPath,
    PlatformAlertSnapshot,
    PlatformConfigurationSnapshot,
    SourceCorrespondence,
    SourceKind,
)
from products.alerts_platform.backend.logic.platform_alert_events import PlatformAlertEventRow, insert_events
from products.alerts_platform.backend.logic.platform_reads import instance_view
from products.alerts_platform.backend.models import (
    PlatformAlert,
    PlatformAlertConfiguration,
    PlatformAlertDeliveryPath,
    PlatformAlertThread,
)


def _configuration_snapshot(row: PlatformAlertConfiguration) -> PlatformConfigurationSnapshot:
    return PlatformConfigurationSnapshot(
        id=row.id,
        next_check_at=row.next_check_at,
        consecutive_failures=row.consecutive_failures,
        check_status=row.check_status,
        owner=row.owner,
    )


def create_configuration(**fields: Any) -> PlatformConfigurationSnapshot:
    """One configuration, as a source's test wants it. Team scoping is the caller's to hold."""
    configuration = PlatformAlertConfiguration.objects.create(**fields)
    return _configuration_snapshot(configuration)


def configuration(configuration_id: UUID) -> PlatformConfigurationSnapshot:
    """The configuration as it stands now, so a test can see a schedule the platform advanced.

    Raises rather than returning None: a test that re-reads a configuration it created is
    asserting about that row, so a missing one is a broken test rather than an outcome.
    """
    # nosemgrep: idor-lookup-without-team — fail-closed model; the caller holds the team scope
    return _configuration_snapshot(PlatformAlertConfiguration.objects.get(id=configuration_id))


def copy_of(legacy_configuration_id: UUID) -> PlatformConfigurationSnapshot:
    """The platform copy of a source's configuration, which a source's test made through its own code."""
    # nosemgrep: idor-lookup-without-team — fail-closed model; the caller holds the team scope
    return _configuration_snapshot(
        PlatformAlertConfiguration.objects.get(legacy_configuration_id=legacy_configuration_id)
    )


def set_due_at(configuration_id: UUID, due_at: datetime) -> None:
    """Move a configuration's due time, so a test can run two checks against one schedule."""
    # nosemgrep: idor-lookup-without-team — fail-closed model; the caller holds the team scope
    PlatformAlertConfiguration.objects.filter(id=configuration_id).update(next_check_at=due_at)


def count_still_due(configuration_ids: Iterable[UUID], *, at: datetime) -> int:
    """How many of these configurations a tick would still pick up at `at`."""
    # nosemgrep: idor-lookup-without-team — fail-closed model; the caller holds the team scope
    return PlatformAlertConfiguration.objects.filter(id__in=list(configuration_ids), next_check_at__lte=at).count()


def start_firing(
    configuration_id: UUID,
    *,
    team_id: int,
    at: datetime,
    delivered_via: DeliveryPath | None = None,
    sent_natively: bool = False,
    grouping_key: str = "",
) -> None:
    """Put a configuration's instance inside a firing, as live delivery can leave one.

    With `delivered_via`, the firing's first delivery took that path, so its resolve takes it too.
    With `sent_natively`, a native transport sent the firing, as live delivery does for an alert
    its source owns.
    """
    PlatformAlert.objects.update_or_create(
        team_id=team_id,
        configuration_id=configuration_id,
        grouping_key=grouping_key,
        defaults={"state": "firing", "firing_started_at": at},
    )
    if delivered_via is not None:
        PlatformAlertDeliveryPath.objects.for_team(team_id).create(
            team_id=team_id,
            configuration_id=str(configuration_id),
            grouping_key=grouping_key,
            episode_started_at=at,
            path=delivered_via.value,
        )
    if sent_natively:
        PlatformAlertThread.objects.for_team(team_id).create(
            team_id=team_id,
            configuration_id=configuration_id,
            grouping_key=grouping_key,
            provider="slack",
            channel_target="C0",
            episode_started_at=at,
        )


def set_check_status(configuration_id: UUID, check_status: str) -> None:
    """Mark a configuration's checks as failing or not, as checks outside the test can leave it."""
    # nosemgrep: idor-lookup-without-team — fail-closed model; the caller holds the team scope
    PlatformAlertConfiguration.objects.filter(id=configuration_id).update(check_status=check_status)


def set_enabled(configuration_id: UUID, enabled: bool) -> None:
    """Switch a configuration on or off, as a broken check the platform owns leaves it.

    A test door with no production caller. The caller holds the team scope.
    """
    # nosemgrep: idor-lookup-without-team, platform-alert-state-direct-mutation — test door, see the docstring
    PlatformAlertConfiguration.objects.filter(id=configuration_id).update(enabled=enabled)


def record_check(
    configuration_id: UUID,
    *,
    team_id: int,
    at: datetime,
    previous_state: str,
    state: str,
    error_message: str | None = None,
    value: float | None = None,
    condition: dict[str, Any] | None = None,
    query_duration_ms: int | None = None,
) -> None:
    """Write one ungrouped check to the platform's ClickHouse history, as a check that ran at `at`."""
    insert_events(
        team_id,
        [
            PlatformAlertEventRow(
                team_id=team_id,
                source_kind=SourceKind.LOGS.value,
                configuration_id=configuration_id,
                alert_id=configuration_id,
                grouping_key="",
                evaluation_key=f"slot:{at.isoformat()}",
                kind="check",
                alert_name="",
                previous_state=previous_state,
                state=state,
                episode_started_at=None,
                value=value,
                labels={},
                condition_snapshot=condition or {},
                source_config_snapshot={},
                query_duration_ms=query_duration_ms,
                error_message=error_message,
                consecutive_failures=0,
                muted_notification="",
                occurred_at=at,
            )
        ],
    )


def alert_for(configuration_id: UUID, *, grouping_key: str = "") -> PlatformAlertSnapshot | None:
    """The instance row a check wrote, or None when no check has written one."""
    row = (
        PlatformAlert.objects.select_related("configuration")
        .filter(configuration_id=configuration_id, grouping_key=grouping_key)
        .first()
    )
    return None if row is None else instance_view(row, row.configuration)


def undeclared_policy_divergences(correspondence: SourceCorrespondence) -> frozenset[str]:
    """The `AlertPolicy` flags on which a source's two stacks differ and it declares no divergence.

    A source's own tests assert this is empty.
    """
    production, platform = correspondence.production_policy, correspondence.platform_policy
    configured = {f.name for f in fields(production) if getattr(production, f.name) != getattr(platform, f.name)}
    # Coverage rather than equality: a source may also declare a deliberate difference no flag
    # describes, and must not be forced to invent one to hang the declaration on.
    return frozenset(configured - {divergence.policy_flag for divergence in correspondence.intentional_divergences})
