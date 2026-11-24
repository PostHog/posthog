"""How many realtime cohorts a project may have on, and how far back their criteria may look, by plan.

Billing sends both as plan features. An organization whose plan doesn't carry one gets the limit set in
REALTIME_COHORT_DEFAULT_MAX_COHORTS or REALTIME_COHORT_DEFAULT_MAX_HISTORY_DAYS, and no limit when that is unset.
"""

from django.conf import settings

from posthog.constants import AvailableFeature
from posthog.models.organization import Organization

from products.cohorts.backend.models.cohort import Cohort, CohortType


def max_realtime_cohorts(organization: Organization) -> int | None:
    """How many cohorts may have realtime on in one project. None means no limit."""
    return _plan_limit(organization, AvailableFeature.REALTIME_COHORTS, settings.REALTIME_COHORT_DEFAULT_MAX_COHORTS)


def max_realtime_history_days(organization: Organization) -> int:
    """How many days back the criteria of a realtime cohort may look.

    Never more than the pipeline's own cap, which is also the answer when there is no limit.
    """
    plan_days = _plan_limit(
        organization, AvailableFeature.REALTIME_COHORTS_HISTORY, settings.REALTIME_COHORT_DEFAULT_MAX_HISTORY_DAYS
    )
    pipeline_days = settings.REALTIME_COHORT_MAX_HISTORY_DAYS
    return pipeline_days if plan_days is None else min(plan_days, pipeline_days)


def realtime_cohorts_used(team_id: int) -> int:
    """How many of the project's cohorts hold a slot. ``team_id`` is the project's root team."""
    return Cohort.objects.filter(
        team_id=team_id,
        cohort_type=CohortType.REALTIME,
        realtime_enabled_at__isnull=False,
        is_static=False,
        deleted=False,
    ).count()


def _plan_limit(organization: Organization, feature: AvailableFeature, default: int | None) -> int | None:
    # A feature that billing sends with a null limit sets no limit, so only a missing feature falls back.
    entry = organization.get_available_feature(feature)
    return default if entry is None else entry.get("limit")
