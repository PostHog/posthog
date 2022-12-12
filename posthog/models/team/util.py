from datetime import timedelta
from typing import Any, List

from posthog.cache_utils import cache_for
from posthog.models.async_migration import is_async_migration_complete


def delete_bulky_postgres_data(team_ids: List[int]):
    "Efficiently delete large tables for teams from postgres. Using normal CASCADE delete here can time out"

    from posthog.models.cohort import CohortPeople
    from posthog.models.insight_caching_state import InsightCachingState
    from posthog.models.person import Person, PersonDistinctId

    _raw_delete(PersonDistinctId.objects.filter(team_id__in=team_ids))
    _raw_delete(CohortPeople.objects.filter(cohort__team_id__in=team_ids))
    _raw_delete(Person.objects.filter(team_id__in=team_ids))
    _raw_delete(InsightCachingState.objects.filter(team_id__in=team_ids))


def _raw_delete(queryset: Any):
    "Issues a single DELETE statement for the queryset"
    queryset._raw_delete(queryset.db)


can_enable_actor_on_events = False

# :TRICKY: Avoid overly eagerly checking whether the migration is complete.
# We instead cache negative responses for a minute and a positive one forever.
def actor_on_events_ready() -> bool:
    global can_enable_actor_on_events

    if can_enable_actor_on_events:
        return True
    can_enable_actor_on_events = _actor_on_events_ready()
    return can_enable_actor_on_events


@cache_for(timedelta(minutes=1))
def _actor_on_events_ready() -> bool:
    return is_async_migration_complete("0007_persons_and_groups_on_events_backfill")
