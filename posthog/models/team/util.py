from datetime import timedelta
from typing import Any

from posthog.batch_exports.service import batch_export_delete_schedule
from posthog.cache_utils import cache_for
from posthog.models.async_migration import is_async_migration_complete
from posthog.temporal.common.client import sync_connect

actions_that_require_current_team = [
    "rotate_secret_token",
    "delete_secret_token_backup",
    "reset_token",
]


def delete_bulky_postgres_data(team_ids: list[int]):
    "Efficiently delete large tables for teams from postgres. Using normal CASCADE delete here can time out"

    from posthog.models.cohort import CohortPeople
    from posthog.models.error_tracking import ErrorTrackingIssueFingerprintV2
    from posthog.models.feature_flag.feature_flag import FeatureFlagHashKeyOverride
    from posthog.models.insight_caching_state import InsightCachingState
    from posthog.models.person import Person, PersonDistinctId

    from products.early_access_features.backend.models import EarlyAccessFeature

    _raw_delete(EarlyAccessFeature.objects.filter(team_id__in=team_ids))
    _raw_delete(PersonDistinctId.objects.filter(team_id__in=team_ids))
    _raw_delete(ErrorTrackingIssueFingerprintV2.objects.filter(team_id__in=team_ids))
    _raw_delete(CohortPeople.objects.filter(cohort__team_id__in=team_ids))
    _raw_delete(FeatureFlagHashKeyOverride.objects.filter(team_id__in=team_ids))
    _raw_delete(Person.objects.filter(team_id__in=team_ids))
    _raw_delete(InsightCachingState.objects.filter(team_id__in=team_ids))


def _raw_delete(queryset: Any):
    "Issues a single DELETE statement for the queryset"
    queryset._raw_delete(queryset.db)


def delete_batch_exports(team_ids: list[int]):
    """Delete BatchExports for deleted teams.

    Using normal CASCADE doesn't trigger a delete from Temporal.
    """
    from posthog.batch_exports.models import BatchExport

    temporal = sync_connect()

    for batch_export in BatchExport.objects.filter(team_id__in=team_ids):
        schedule_id = batch_export.id

        batch_export.delete()
        batch_export.destination.delete()

        batch_export_delete_schedule(temporal, str(schedule_id))


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
