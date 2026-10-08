"""
Facade API for cohorts.

This is the module that other apps should import from. It accepts plain inputs and
returns contract DTOs or primitives, never ORM instances or QuerySets.
"""

from __future__ import annotations

from posthog.models.activity_logging.activity_log import Change, Detail, log_activity
from posthog.models.activity_logging.model_activity import get_was_impersonated
from posthog.models.person.util import validate_person_uuids_exist
from posthog.models.user import User

from products.access_control.backend.facade.user_access_control import UserAccessControl
from products.cohorts.backend.models.cohort import DEFAULT_COHORT_INSERT_BATCH_SIZE, Cohort

MAX_PERSONS_PER_STATIC_COHORT_ADD = DEFAULT_COHORT_INSERT_BATCH_SIZE


class CohortNotFound(Exception):
    pass


class CohortNotStatic(Exception):
    pass


class CohortAccessDenied(Exception):
    pass


class NoValidPersons(Exception):
    pass


def cohort_exists_for_team(*, team_id: int, cohort_id: int) -> bool:
    """Whether the team owns that cohort.

    A soft-deleted cohort still counts, so a caller that holds a reference to one keeps it.
    """
    return Cohort.objects.filter(team_id=team_id, id=cohort_id).exists()


def add_persons_to_static_cohort(*, team_id: int, user_id: int, cohort_id: int, person_ids: list[str]) -> int:
    """Add people (by person uuid) to a static cohort as ``user_id`` and return how many uuids were valid.

    The same write and activity log entry as the cohort API's ``add_persons_to_static_cohort``
    action. Raises ``CohortNotFound`` for a cohort outside the team or soft deleted,
    ``CohortAccessDenied`` when the user has no editor access to the cohort (the check the
    cohort API applies), ``CohortNotStatic`` for a dynamic cohort, and ``NoValidPersons`` when
    none of the uuids name a person in the team.
    """
    cohort = Cohort.objects.filter(team_id=team_id, id=cohort_id, deleted=False).select_related("team").first()
    if cohort is None:
        raise CohortNotFound
    user = User.objects.get(id=user_id)
    if not UserAccessControl(user=user, team=cohort.team).check_access_level_for_object(cohort, "editor"):
        raise CohortAccessDenied
    if not cohort.is_static:
        raise CohortNotStatic
    uuids = validate_person_uuids_exist(team_id, person_ids[:MAX_PERSONS_PER_STATIC_COHORT_ADD])
    if not uuids:
        raise NoValidPersons
    cohort.insert_users_list_by_uuid(uuids, team_id=team_id)
    log_activity(
        organization_id=cohort.team.organization_id,
        team_id=team_id,
        user=user,
        was_impersonated=get_was_impersonated(),
        item_id=str(cohort.id),
        scope="Cohort",
        activity="persons_added_manually",
        detail=Detail(changes=[Change(type="Cohort", action="changed")]),
    )
    return len(uuids)
