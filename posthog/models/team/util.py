import time
from datetime import timedelta
from typing import Any

import structlog

from posthog.cache_utils import cache_for
from posthog.exceptions_capture import capture_exception
from posthog.models.async_migration import is_async_migration_complete
from posthog.temporal.common.client import sync_connect

from products.batch_exports.backend.service import BatchExportServiceScheduleNotFound, batch_export_delete_schedule

logger = structlog.get_logger(__name__)

actions_that_require_current_team = [
    "rotate_secret_token",
    "delete_secret_token_backup",
    "reset_token",
    "generate_conversations_public_token",
    "default_release_conditions",
]


def delete_bulky_postgres_data(team_ids: list[int]):
    "Efficiently delete large tables for teams from postgres. Using normal CASCADE delete here can time out"

    from posthog.models.cohort import Cohort, CohortPeople
    from posthog.models.feature_flag.feature_flag import FeatureFlagHashKeyOverride
    from posthog.models.group.group import Group
    from posthog.models.group_type_mapping import GroupTypeMapping
    from posthog.models.insight_caching_state import InsightCachingState
    from posthog.models.person import PersonlessDistinctId

    from products.data_modeling.backend.models import Edge, Node
    from products.early_access_features.backend.models import EarlyAccessFeature
    from products.error_tracking.backend.models import ErrorTrackingIssueFingerprintV2

    # Delete data modeling nodes and edges first to not block Team deletion.
    # Team cascades to DataWarehouseSavedQuery, but it has PROTECT on delete.
    _raw_delete(Edge.objects.filter(team_id__in=team_ids))
    _raw_delete(Node.objects.filter(team_id__in=team_ids))

    _raw_delete(EarlyAccessFeature.objects.filter(team_id__in=team_ids))
    _raw_delete_batch(PersonlessDistinctId.objects.filter(team_id__in=team_ids))  # nosemgrep: no-direct-persons-db-orm
    _raw_delete(ErrorTrackingIssueFingerprintV2.objects.filter(team_id__in=team_ids))

    # Get cohort_ids from the default database first to avoid cross-database join
    # CohortPeople is in persons_db, Cohort is in default db
    cohort_ids = list(Cohort.objects.filter(team_id__in=team_ids).values_list("id", flat=True))
    _raw_delete(CohortPeople.objects.filter(cohort_id__in=cohort_ids))  # nosemgrep: no-direct-persons-db-orm

    _raw_delete(FeatureFlagHashKeyOverride.objects.filter(team_id__in=team_ids))  # nosemgrep: no-direct-persons-db-orm
    _raw_delete(Group.objects.filter(team_id__in=team_ids))  # nosemgrep: no-direct-persons-db-orm
    _raw_delete(GroupTypeMapping.objects.filter(team_id__in=team_ids))  # nosemgrep: no-direct-persons-db-orm

    # Delete Person + PersonDistinctId via personhog RPC (handles both tables).
    # Falls back to ORM batch deletion when personhog is not available.
    _delete_persons_for_teams(team_ids)

    _raw_delete(InsightCachingState.objects.filter(team_id__in=team_ids))


def _delete_persons_for_teams(team_ids: list[int]) -> None:
    """Delete Person + PersonDistinctId rows for teams via personhog RPC.

    Falls back to ORM batch deletion when personhog is not available.
    The RPC handles PersonDistinctId deletion automatically.
    Uses _personhog_routed per team for consistent gate/metrics/fallback.
    """
    from functools import partial

    from posthog.models.person.util import _personhog_routed

    for team_id in team_ids:
        _personhog_routed(
            "delete_persons_for_team",
            partial(_delete_persons_for_team_via_personhog, team_id),
            partial(_delete_persons_for_team_via_orm, team_id),
            team_id=team_id,
        )


def _delete_persons_for_team_via_personhog(team_id: int) -> None:
    from posthog.personhog_client.client import get_personhog_client
    from posthog.personhog_client.proto import DeletePersonsBatchForTeamRequest

    client = get_personhog_client()
    if client is None:
        raise RuntimeError("personhog client not configured")

    while True:
        resp = client.delete_persons_batch_for_team(DeletePersonsBatchForTeamRequest(team_id=team_id, batch_size=10000))
        if resp.deleted_count == 0:
            break


def _delete_persons_for_team_via_orm(team_id: int) -> None:
    from posthog.models.person import Person, PersonDistinctId

    _raw_delete_batch(PersonDistinctId.objects.filter(team_id=team_id))  # nosemgrep: no-direct-persons-db-orm
    _raw_delete_batch(Person.objects.filter(team_id=team_id))  # nosemgrep: no-direct-persons-db-orm


def _raw_delete(queryset: Any):
    "Issues a single DELETE statement for the queryset"
    from django.db import router

    # Use db_for_write to ensure we get a writable connection (not read-only replica)
    db_alias = router.db_for_write(queryset.model)
    queryset._raw_delete(db_alias)


def _raw_delete_batch(queryset: Any, batch_size: int = 10000):
    """
    Deletes records in batches to avoid statement timeout on large tables.

    Note: For partitioned tables (like posthog_person_new), preserving filters
    like team_id ensures efficient single-partition deletes instead of scanning
    all partitions.

    Uses tuple IN clause (id, team_id) IN ((...), (...)) to ensure accurate
    deletion of specific record combinations rather than a Cartesian product.
    """
    from django.db import connections, router

    while True:
        # Get tuples of (id, team_id) to ensure accurate deletion
        batch_tuples = list(queryset.values_list("team_id", "id")[:batch_size])

        if not batch_tuples:
            break

        # Use raw SQL with tuple IN clause for accurate deletion
        # Format: DELETE FROM table WHERE (id, team_id) IN ((1, 1), (2, 1), ...)
        # Use db_for_write to ensure we get a writable connection (not read-only replica)
        db_alias = router.db_for_write(queryset.model)
        db_connection = connections[db_alias]
        with db_connection.cursor() as cursor:
            table_name = queryset.model._meta.db_table
            # Build tuple placeholders: (%s, %s), (%s, %s), ...
            tuple_placeholders = ",".join(["(%s, %s)"] * len(batch_tuples))
            # Flatten tuples for parameters: [id1, team_id1, id2, team_id2, ...]
            params = [item for tuple_pair in batch_tuples for item in tuple_pair]

            query = f'DELETE FROM "{table_name}" WHERE ("team_id", "id") IN ({tuple_placeholders})'
            cursor.execute(query, params)

        # If we got fewer records than batch_size, we're done
        if len(batch_tuples) < batch_size:
            break

        time.sleep(0.1)


def delete_batch_exports(team_ids: list[int]):
    """Delete BatchExports for deleted teams.

    Using normal CASCADE doesn't trigger a delete from Temporal.
    """
    from posthog.batch_exports.models import BatchExport

    temporal = sync_connect()

    for batch_export in BatchExport.objects.filter(team_id__in=team_ids, deleted=False):
        schedule_id = batch_export.id

        batch_export.delete()
        batch_export.destination.delete()

        try:
            batch_export_delete_schedule(temporal, str(schedule_id))
        except BatchExportServiceScheduleNotFound as e:
            logger.warning(
                "Schedule not found during team deletion",
                schedule_id=e.schedule_id,
            )


def delete_data_modeling_schedules(team_ids: list[int]) -> None:
    """Delete Temporal schedules for data modeling saved queries in deleted teams.

    Django CASCADE deletes the DataWarehouseSavedQuery records but doesn't
    call revert_materialization(), leaving orphaned Temporal schedules.
    """
    import temporalio.service

    from posthog.temporal.common.schedule import delete_schedule

    from products.data_warehouse.backend.models.datawarehouse_saved_query import DataWarehouseSavedQuery

    saved_queries = list(
        DataWarehouseSavedQuery.objects.filter(
            team_id__in=team_ids,
            sync_frequency_interval__isnull=False,
        ).exclude(deleted=True)  # as it's nullable
    )

    if not saved_queries:
        return

    temporal = sync_connect()

    for saved_query in saved_queries:
        try:
            delete_schedule(temporal, schedule_id=str(saved_query.id))
        except temporalio.service.RPCError as e:
            if e.status == temporalio.service.RPCStatusCode.NOT_FOUND:
                logger.warning(
                    "Data modeling schedule not found during team deletion",
                    schedule_id=str(saved_query.id),
                    team_id=saved_query.team_id,
                )
                continue
            capture_exception(e)


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
