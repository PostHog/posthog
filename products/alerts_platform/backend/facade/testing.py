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
    PlatformAlertSnapshot,
    PlatformConfigurationSnapshot,
    SourceCorrespondence,
)
from products.alerts_platform.backend.logic.platform_reads import instance_view
from products.alerts_platform.backend.models import PlatformAlert, PlatformAlertConfiguration


def _configuration_snapshot(row: PlatformAlertConfiguration) -> PlatformConfigurationSnapshot:
    return PlatformConfigurationSnapshot(
        id=row.id, next_check_at=row.next_check_at, consecutive_failures=row.consecutive_failures
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


def set_due_at(configuration_id: UUID, due_at: datetime) -> None:
    """Move a configuration's due time, so a test can run two checks against one schedule."""
    # nosemgrep: idor-lookup-without-team — fail-closed model; the caller holds the team scope
    PlatformAlertConfiguration.objects.filter(id=configuration_id).update(next_check_at=due_at)


def count_still_due(configuration_ids: Iterable[UUID], *, at: datetime) -> int:
    """How many of these configurations a tick would still pick up at `at`."""
    # nosemgrep: idor-lookup-without-team — fail-closed model; the caller holds the team scope
    return PlatformAlertConfiguration.objects.filter(id__in=list(configuration_ids), next_check_at__lte=at).count()


def alert_for(configuration_id: UUID, *, grouping_key: str = "") -> PlatformAlertSnapshot | None:
    """The instance row a check wrote, or None when no check has written one."""
    row = PlatformAlert.objects.filter(configuration_id=configuration_id, grouping_key=grouping_key).first()
    return None if row is None else instance_view(row)


def undeclared_policy_divergences(correspondence: SourceCorrespondence) -> frozenset[str]:
    """The `AlertPolicy` flags on which a source's two stacks differ and it declares no divergence.

    A source's own tests assert this is empty.
    """
    production, platform = correspondence.production_policy, correspondence.platform_policy
    configured = {f.name for f in fields(production) if getattr(production, f.name) != getattr(platform, f.name)}
    # Coverage rather than equality: a source may also declare a deliberate difference no flag
    # describes, and must not be forced to invent one to hang the declaration on.
    return frozenset(configured - {divergence.policy_flag for divergence in correspondence.intentional_divergences})
