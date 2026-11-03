"""
Facade API for cohorts.

This is the module that other apps should import from. It accepts plain inputs and
returns contract DTOs or primitives, never ORM instances or QuerySets.
"""

from __future__ import annotations

from posthog.dataclasses import frozen
from posthog.tasks.calculate_cohort import schedule_static_cohort_count_refresh

from products.cohorts.backend.models.cohort import Cohort, ImportResolution


def cohort_exists_for_team(*, team_id: int, cohort_id: int) -> bool:
    """Whether the team owns that cohort.

    A soft-deleted cohort still counts, so a caller that holds a reference to one keeps it.
    """
    return Cohort.objects.filter(team_id=team_id, id=cohort_id).exists()


@frozen
class CohortRef:
    id: int
    team_id: int
    created_by_id: int | None
    is_static: bool
    deleted: bool


def get_cohort_ref(*, team_id: int, cohort_id: int) -> CohortRef | None:
    cohort = (
        Cohort.objects.filter(team_id=team_id, id=cohort_id)
        .only("id", "team_id", "created_by_id", "is_static", "deleted")
        .first()
    )
    if cohort is None:
        return None
    return CohortRef(
        id=cohort.id,
        team_id=cohort.team_id,
        created_by_id=cohort.created_by_id,
        is_static=cohort.is_static,
        deleted=cohort.deleted,
    )


def add_person_to_static_cohort(*, team_id: int, cohort_id: int, person_uuid: str) -> bool:
    """Add one person to a static cohort. Returns False when the team has no person with that UUID.

    A person who is already a member is not inserted again, but the check and the insert are separate
    statements, so the caller must serialize concurrent calls for the same cohort and person.
    """
    cohort = Cohort.objects.get(team_id=team_id, id=cohort_id)
    resolution = ImportResolution()
    # save_state=False skips the full recount after each insert. The scheduled refresh updates the count.
    cohort.insert_users_list_by_uuid([person_uuid], team_id=team_id, save_state=False, import_resolution=resolution)
    if not resolution.matched_inputs:
        return False
    schedule_static_cohort_count_refresh(team_id=team_id, cohort_id=cohort_id)
    return True
