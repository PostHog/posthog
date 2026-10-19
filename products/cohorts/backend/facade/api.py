"""
Facade API for cohorts.

This is the module that other apps should import from. It accepts plain inputs and
returns contract DTOs or primitives, never ORM instances or QuerySets.
"""

from __future__ import annotations

from products.cohorts.backend.models.cohort import Cohort


def cohort_exists_for_team(*, team_id: int, cohort_id: int) -> bool:
    """Whether the team owns that cohort.

    A soft-deleted cohort still counts, so a caller that holds a reference to one keeps it.
    """
    return Cohort.objects.filter(team_id=team_id, id=cohort_id).exists()


def list_cohort_names(*, team_id: int) -> dict[int, str]:
    """Names of the team's cohorts that are not deleted, keyed by cohort ID."""
    return dict(Cohort.objects.filter(team_id=team_id, deleted=False).values_list("id", "name"))
