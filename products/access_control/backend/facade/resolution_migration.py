"""Sweep of organizations still on the legacy access resolution, and the switch for the
ones the change cannot affect.

An organization is unaffected when every rule subject resolves the same under both
resolutions on every team (see `resolution_preview`), or when it has no access rules at all.
Organizations that resolve differently, and organizations with rules but no active member
to evaluate as, are reported and left on the legacy resolution.
"""

from collections.abc import Iterable
from uuid import UUID

from django.db.models import QuerySet

from posthog.dataclasses import frozen
from posthog.models.organization import Organization
from posthog.models.team.team import Team

from products.access_control.backend.facade.resolution_preview import iter_resolution_changes
from products.access_control.backend.models.access_control import AccessControl

_UPDATE_BATCH_SIZE = 500


@frozen
class OrganizationReadiness:
    id: UUID
    name: str
    teams: int
    changes: int
    gains: int
    loses: int


@frozen
class OrganizationRef:
    id: UUID
    name: str


@frozen
class ResolutionSweep:
    """Every organization not yet on the most-specific resolution, sorted into buckets."""

    divergent: list[OrganizationReadiness]
    unchanged: list[OrganizationReadiness]
    unevaluated: list[OrganizationRef]
    without_rules: list[UUID]

    @property
    def unaffected_ids(self) -> list[UUID]:
        return [readiness.id for readiness in self.unchanged] + list(self.without_rules)


def _pending_organizations() -> QuerySet[Organization]:
    return Organization.objects.exclude(uses_most_specific_access_resolution=True)


def sweep_pending_organizations() -> ResolutionSweep:
    totals: dict[UUID, dict[str, int]] = {}
    names: dict[UUID, str] = {}

    for team, changes in iter_resolution_changes(only_pending=True):
        org_id = team.organization_id
        names[org_id] = team.organization.name
        counts = totals.setdefault(org_id, {"teams": 0, "changes": 0, "gains": 0, "loses": 0})
        counts["teams"] += 1
        counts["changes"] += len(changes)
        counts["gains"] += sum(1 for change in changes if change.direction == "gains")
        counts["loses"] += sum(1 for change in changes if change.direction == "loses")

    evaluated = [OrganizationReadiness(id=org_id, name=names[org_id], **counts) for org_id, counts in totals.items()]
    divergent = sorted((r for r in evaluated if r.changes > 0), key=lambda r: -r.changes)
    unchanged = sorted((r for r in evaluated if r.changes == 0), key=lambda r: str(r.id))

    organizations_with_rules = Team.objects.filter(id__in=AccessControl.objects.values("team_id")).values(
        "organization_id"
    )
    unevaluated = [
        OrganizationRef(id=org_id, name=name)
        for org_id, name in _pending_organizations()
        .filter(id__in=organizations_with_rules)
        .exclude(id__in=totals.keys())
        .order_by("id")
        .values_list("id", "name")
    ]
    without_rules = list(
        _pending_organizations().exclude(id__in=organizations_with_rules).order_by("id").values_list("id", flat=True)
    )
    return ResolutionSweep(
        divergent=divergent, unchanged=unchanged, unevaluated=unevaluated, without_rules=without_rules
    )


def enable_most_specific_resolution(organization_ids: Iterable[UUID]) -> int:
    """Switch the given organizations to the most-specific resolution. Returns the number of
    rows updated. Batched so one sweep never holds a long lock on the organization table."""
    ids = list(organization_ids)
    updated = 0
    for start in range(0, len(ids), _UPDATE_BATCH_SIZE):
        batch = ids[start : start + _UPDATE_BATCH_SIZE]
        updated += Organization.objects.filter(id__in=batch).update(uses_most_specific_access_resolution=True)
    return updated
