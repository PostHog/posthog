"""How many realtime cohorts a project may have on, and how far back their criteria may look, by plan.

Billing sends both as plan features. Every plan has them, so an organization without one gets the Free
limits: self-hosted and local dev have no billing features, and the pipeline does not run there.
"""

from django.conf import settings

from posthog.constants import AvailableFeature
from posthog.models.organization import Organization

from products.cohorts.backend.models.cohort import Cohort, CohortType

FREE_MAX_REALTIME_COHORTS = 10
FREE_MAX_REALTIME_HISTORY_DAYS = 30


def max_realtime_cohorts(organization: Organization) -> int | None:
    """How many cohorts may have realtime on in one project. None means the plan sets no limit."""
    feature = organization.get_available_feature(AvailableFeature.REALTIME_COHORTS)
    return FREE_MAX_REALTIME_COHORTS if feature is None else feature.get("limit")


def max_realtime_history_days(organization: Organization) -> int:
    """How many days back the criteria of a realtime cohort may look.

    Never more than the pipeline's own cap, which is also the answer when the plan sets no limit.
    """
    feature = organization.get_available_feature(AvailableFeature.REALTIME_COHORTS_HISTORY)
    plan_days = FREE_MAX_REALTIME_HISTORY_DAYS if feature is None else feature.get("limit")
    pipeline_days = settings.REALTIME_COHORT_MAX_HISTORY_DAYS
    return pipeline_days if plan_days is None else min(plan_days, pipeline_days)


def realtime_cohorts_used(team_id: int) -> int:
    """How many of the project's cohorts the pipeline loads. ``team_id`` is the project's root team."""
    return Cohort.objects.filter(
        team_id=team_id,
        cohort_type=CohortType.REALTIME,
        realtime_enabled_at__isnull=False,
        is_static=False,
        deleted=False,
    ).count()
