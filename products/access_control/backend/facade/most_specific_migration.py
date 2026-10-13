"""Finds the organizations still on the legacy access resolution that the most-specific
resolution does not affect, and switches them over.

An organization is not affected when it has no access rules, or when every rule resolves
the same under both resolutions on every team (see `resolution_preview`). Organizations
that resolve differently, and organizations the preview cannot evaluate, are reported and
stay on the legacy resolution.
"""

from collections import Counter, defaultdict
from collections.abc import Iterable
from datetime import datetime
from itertools import batched
from uuid import UUID

from django.db.models import Exists, OuterRef, QuerySet
from django.utils import timezone

from posthog.dataclasses import frozen
from posthog.models.organization import Organization

from products.access_control.backend.facade.resolution_preview import ResolutionChange, iter_resolution_changes
from products.access_control.backend.models.access_control import AccessControl

_UPDATE_BATCH_SIZE = 500


@frozen
class OrganizationChanges:
    """How many rules on an organization resolve differently, across its evaluated teams."""

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
class MigrationCandidates:
    """Every organization still on the legacy resolution, sorted by what the switch would do."""

    # When the classification started. Rules written after this may invalidate it.
    found_at: datetime
    divergent: list[OrganizationChanges]
    unchanged: list[OrganizationChanges]
    unevaluated: list[OrganizationRef]
    without_rules: list[UUID]

    @property
    def unaffected_ids(self) -> list[UUID]:
        return [org.id for org in self.unchanged] + self.without_rules


def _pending_organizations() -> QuerySet[Organization]:
    # The column is nullable and NULL means legacy, so exclude True rather than filter False
    return Organization.objects.exclude(uses_most_specific_access_resolution=True)


def find_organizations_to_migrate() -> MigrationCandidates:
    found_at = timezone.now()
    names: dict[UUID, str] = {}
    teams_by_org: Counter[UUID] = Counter()
    changes_by_org: defaultdict[UUID, list[ResolutionChange]] = defaultdict(list)
    for team, changes in iter_resolution_changes(only_pending=True):
        names[team.organization_id] = team.organization.name
        teams_by_org[team.organization_id] += 1
        changes_by_org[team.organization_id].extend(changes)

    evaluated = [
        OrganizationChanges(
            id=org_id,
            name=names[org_id],
            teams=teams_by_org[org_id],
            changes=len(changes),
            gains=sum(change.direction == "gains" for change in changes),
            loses=sum(change.direction == "loses" for change in changes),
        )
        for org_id, changes in changes_by_org.items()
    ]
    divergent = sorted((org for org in evaluated if org.changes > 0), key=lambda org: org.changes, reverse=True)
    unchanged = sorted((org for org in evaluated if org.changes == 0), key=lambda org: str(org.id))

    organizations_with_rules = AccessControl.objects.values("team__organization_id")
    unevaluated = [
        OrganizationRef(id=org_id, name=name)
        for org_id, name in _pending_organizations()
        .filter(id__in=organizations_with_rules)
        .exclude(id__in=changes_by_org.keys())
        .order_by("id")
        .values_list("id", "name")
    ]
    without_rules = list(
        _pending_organizations().exclude(id__in=organizations_with_rules).order_by("id").values_list("id", flat=True)
    )
    return MigrationCandidates(
        found_at=found_at,
        divergent=divergent,
        unchanged=unchanged,
        unevaluated=unevaluated,
        without_rules=without_rules,
    )


def enable_most_specific_resolution(organization_ids: Iterable[UUID], *, rules_unchanged_since: datetime) -> int:
    """Switch the given organizations to the most-specific resolution. Returns the number of
    rows updated. Batched so one run never holds a long lock on the organization table.

    An organization whose access rules were written at or after `rules_unchanged_since` is
    left alone: the classification that approved it no longer describes its rules.
    """
    rules_written_since = AccessControl.objects.filter(
        team__organization_id=OuterRef("id"), updated_at__gte=rules_unchanged_since
    )
    updated = 0
    for batch in batched(organization_ids, _UPDATE_BATCH_SIZE, strict=False):
        updated += (
            Organization.objects.filter(id__in=batch)
            .exclude(Exists(rules_written_since))
            .update(uses_most_specific_access_resolution=True)
        )
    return updated
