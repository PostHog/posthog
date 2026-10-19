"""
Facade API for cohorts.

This is the module that other apps should import from. It accepts plain inputs and
returns contract DTOs or primitives, never ORM instances or QuerySets.
"""

from __future__ import annotations

from enum import StrEnum

from django.db.models import F, Value
from django.db.models.functions import Coalesce

from products.cohorts.backend.models.cohort import Cohort
from products.cohorts.backend.models.util import is_person_in_cohort


class StaticCohortMembershipOutcome(StrEnum):
    VALID = "valid"
    ADDED = "added"
    ALREADY_PRESENT = "already_present"
    NOT_FOUND = "not_found"
    DELETED = "deleted"
    NOT_STATIC = "not_static"


def cohort_exists_for_team(*, team_id: int, cohort_id: int) -> bool:
    """Whether the team owns that cohort.

    A soft-deleted cohort still counts, so a caller that holds a reference to one keeps it.
    """
    return Cohort.objects.filter(team_id=team_id, id=cohort_id).exists()


def get_static_cohort_membership_status(*, team_id: int, cohort_id: int) -> StaticCohortMembershipOutcome:
    cohort = Cohort.objects.filter(team_id=team_id, id=cohort_id).first()
    return _get_static_cohort_membership_status(cohort)


def add_resolved_person_to_static_cohort(
    *, team_id: int, cohort_id: int, person_id: int, person_uuid: str
) -> StaticCohortMembershipOutcome:
    """Add a person that was resolved by a team-scoped personhog read."""
    cohort = Cohort.objects.filter(team_id=team_id, id=cohort_id).first()
    cohort_status = _get_static_cohort_membership_status(cohort)
    if cohort is None or cohort_status != StaticCohortMembershipOutcome.VALID:
        return cohort_status
    if is_person_in_cohort(team_id, person_id, cohort_id):
        return StaticCohortMembershipOutcome.ALREADY_PRESENT

    cohort.insert_users_list_by_id_uuid_pairs_skip_validation(
        [(person_id, person_uuid)], team_id=team_id, raise_on_error=True, save_state=False
    )
    Cohort.objects.filter(team_id=team_id, id=cohort_id).update(count=Coalesce(F("count"), Value(0)) + 1)
    return StaticCohortMembershipOutcome.ADDED


def _get_static_cohort_membership_status(cohort: Cohort | None) -> StaticCohortMembershipOutcome:
    if cohort is None:
        return StaticCohortMembershipOutcome.NOT_FOUND
    if cohort.deleted:
        return StaticCohortMembershipOutcome.DELETED
    if not cohort.is_static:
        return StaticCohortMembershipOutcome.NOT_STATIC
    return StaticCohortMembershipOutcome.VALID
