from django.db.models import Q

from celery import shared_task

from posthog.models.scoping import with_team_scope

from products.cohorts.backend.models.cohort import Cohort
from products.cohorts.backend.models.util import count_cohort_members


@shared_task(ignore_result=True, autoretry_for=(Exception,), retry_backoff=True, max_retries=5)
@with_team_scope()
def reconcile_static_cohort_count_after_addition(*, team_id: int, cohort_id: int) -> None:
    actual_count = count_cohort_members(team_id=team_id, cohort_id=cohort_id, consistency="strong")
    Cohort.objects.filter(
        Q(count__isnull=True) | Q(count__lt=actual_count),
        team_id=team_id,
        id=cohort_id,
        is_static=True,
        deleted=False,
    ).update(count=actual_count)
