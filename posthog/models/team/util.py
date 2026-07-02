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

# Batch size for the personhog batch-delete RPCs on the largest team-scoped tables
# (personless distinct IDs, persons, hash-key-overrides). Kept well below 10000 so each
# DELETE commits comfortably inside the personhog gRPC deadline on multi-billion-row
# tables; otherwise a batch that overruns the deadline is rolled back wholesale and the
# activity retries with zero forward progress.
TEAM_DELETE_BATCH_SIZE = 2000

actions_that_require_current_team = [
    "rotate_secret_token",
    "delete_secret_token_backup",
    "reset_token",
    "generate_conversations_public_token",
    "default_release_conditions",
    "experiments_config",
    "default_evaluation_contexts",
    "evaluation_context_suggestions",
]


def delete_bulky_postgres_data(team_ids: list[int]):
    "Efficiently delete large tables for teams from postgres. Using normal CASCADE delete here can time out"
    # Each phase is its own batched helper so the Temporal deletion workflow can run them
    # as separate, individually-retryable activities while Celery keeps calling them in sequence.
    _delete_misc_small_tables_for_teams(team_ids)
    _delete_personless_distinct_ids_for_teams(team_ids)
    _delete_cohort_members_for_all_teams(team_ids)
    _delete_groups_for_teams(team_ids)
    _delete_group_type_mappings_for_teams(team_ids)

    # Delete Person + PersonDistinctId via personhog RPC (handles both tables).
    _delete_persons_for_teams(team_ids)


def _delete_misc_small_tables_for_teams(team_ids: list[int]) -> None:
    """Batch-delete the per-team tables that have no dedicated bulk path.

    These previously used a single unbatched DELETE each, which could hit a statement
    timeout or hold a long lock on very large teams. _raw_delete_batch keeps every
    statement bounded.
    """
    from posthog.models.file_system.file_system_view_log import FileSystemViewLog

    from products.data_modeling.backend.facade.models import Edge, Node
    from products.early_access_features.backend.models import EarlyAccessFeature
    from products.error_tracking.backend.models import ErrorTrackingIssueFingerprintV2
    from products.product_analytics.backend.models.insight_caching_state import InsightCachingState

    # Data modeling Edge/Node must be deleted before the Team row: Team cascades to
    # DataWarehouseSavedQuery, which has PROTECT on delete.
    _raw_delete_batch(Edge.objects.filter(team_id__in=team_ids))
    _raw_delete_batch(Node.objects.filter(team_id__in=team_ids))
    _raw_delete_batch(FileSystemViewLog.objects.filter(team_id__in=team_ids))
    _raw_delete_batch(EarlyAccessFeature.objects.filter(team_id__in=team_ids))
    _raw_delete_batch(ErrorTrackingIssueFingerprintV2.objects.filter(team_id__in=team_ids))
    # FeatureFlagHashKeyOverride references Person, so it must go before persons are deleted.
    _delete_hash_key_overrides_for_teams(team_ids)
    _raw_delete_batch(InsightCachingState.objects.filter(team_id__in=team_ids))


def _delete_hash_key_overrides_for_teams(team_ids: list[int]) -> None:
    """Delete FeatureFlagHashKeyOverride rows for the given teams via personhog.

    These rows reference Person but have no DB-level cascade (cross-database FK with
    db_constraint=False), so they must be deleted explicitly before the persons are.
    """
    if not team_ids:
        return

    from posthog.personhog_client.client import personhog_call, require_personhog_client
    from posthog.personhog_client.proto import DeleteHashKeyOverridesByTeamsRequest

    client = require_personhog_client()

    def _fn() -> None:
        while True:
            resp = client.delete_hash_key_overrides_by_teams(
                DeleteHashKeyOverridesByTeamsRequest(team_ids=team_ids, batch_size=TEAM_DELETE_BATCH_SIZE)
            )
            if resp.deleted_count == 0:
                break

    personhog_call(
        "delete_hash_key_overrides_for_teams",
        _fn,
        caller_tag="team-delete/hash-key-overrides",
    )


def _delete_personless_distinct_ids_for_teams(team_ids: list[int]) -> None:
    """Delete posthog_personlessdistinctid rows for teams via personhog RPC."""
    from functools import partial

    from posthog.personhog_client.client import personhog_call

    for team_id in team_ids:
        personhog_call(
            "delete_personless_distinct_ids_for_team",
            partial(_delete_personless_distinct_ids_for_team_via_personhog, team_id),
        )


def _delete_personless_distinct_ids_for_team_via_personhog(team_id: int) -> None:
    from posthog.personhog_client.client import require_personhog_client
    from posthog.personhog_client.proto import DeletePersonlessDistinctIdsBatchForTeamRequest

    client = require_personhog_client()

    while True:
        resp = client.delete_personless_distinct_ids_batch_for_team(
            DeletePersonlessDistinctIdsBatchForTeamRequest(team_id=team_id, batch_size=TEAM_DELETE_BATCH_SIZE)
        )
        if resp.deleted_count == 0:
            break


def _delete_cohort_members_for_all_teams(team_ids: list[int]) -> None:
    # Resolve cohort ids from the default DB first to avoid a cross-database join:
    # CohortPeople lives in persons_db, Cohort in the default db.
    from products.cohorts.backend.models.cohort import Cohort

    cohort_ids = list(Cohort.objects.filter(team_id__in=team_ids).values_list("id", flat=True))
    if cohort_ids:
        _delete_cohort_members_for_teams(team_ids, cohort_ids)


def _delete_persons_for_teams(team_ids: list[int]) -> None:
    """Delete Person + PersonDistinctId rows for teams via personhog RPC.

    The RPC handles PersonDistinctId deletion automatically.
    """
    from functools import partial

    from posthog.personhog_client.client import personhog_call

    for team_id in team_ids:
        personhog_call(
            "delete_persons_for_team",
            partial(_delete_persons_for_team_via_personhog, team_id),
        )


def _delete_persons_for_team_via_personhog(team_id: int) -> None:
    from posthog.personhog_client.client import require_personhog_client
    from posthog.personhog_client.proto import DeletePersonsBatchForTeamRequest

    client = require_personhog_client()

    while True:
        resp = client.delete_persons_batch_for_team(
            DeletePersonsBatchForTeamRequest(team_id=team_id, batch_size=TEAM_DELETE_BATCH_SIZE)
        )
        if resp.deleted_count == 0:
            break


def _delete_groups_for_teams(team_ids: list[int]) -> None:
    from posthog.personhog_client.client import personhog_call, require_personhog_client
    from posthog.personhog_client.proto import DeleteGroupsBatchForTeamRequest

    client = require_personhog_client()

    for team_id in team_ids:

        def _fn(tid: int = team_id) -> None:
            while True:
                resp = client.delete_groups_batch_for_team(
                    DeleteGroupsBatchForTeamRequest(team_id=tid, batch_size=10000)
                )
                if resp.deleted_count == 0:
                    break

        personhog_call("delete_groups_for_team", _fn)


def _delete_group_type_mappings_for_teams(team_ids: list[int]) -> None:
    from posthog.personhog_client.client import personhog_call, require_personhog_client
    from posthog.personhog_client.proto import DeleteGroupTypeMappingsBatchForTeamRequest

    client = require_personhog_client()

    for team_id in team_ids:

        def _fn(tid: int = team_id) -> None:
            while True:
                resp = client.delete_group_type_mappings_batch_for_team(
                    DeleteGroupTypeMappingsBatchForTeamRequest(team_id=tid, batch_size=10000)
                )
                if resp.deleted_count == 0:
                    break

        personhog_call("delete_group_type_mappings_for_team", _fn)


def _delete_cohort_members_for_teams(team_ids: list[int], cohort_ids: list[int]) -> None:
    """Delete CohortPeople rows for teams via personhog RPC.

    Routes per-team for consistent metrics.
    """
    from products.cohorts.backend.models.cohort import Cohort
    from products.cohorts.backend.models.util import delete_cohort_members_bulk

    for team_id in team_ids:
        team_cohort_ids = list(Cohort.objects.filter(team_id=team_id, id__in=cohort_ids).values_list("id", flat=True))
        if team_cohort_ids:
            delete_cohort_members_bulk(team_id, team_cohort_ids)


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
    from products.batch_exports.backend.models.batch_export import BatchExport

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

    from products.data_modeling.backend.facade.models import DataWarehouseSavedQuery

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


def delete_team_records(team_ids: list[int]) -> None:
    """Delete the Team rows once their bulky child data has been removed.

    FOR UPDATE on the teams blocks concurrent FK-inserts to any child table during the
    cascade delete.
    """
    from django.db import transaction

    from posthog.models.team import Team

    with transaction.atomic():
        list(Team.objects.select_for_update().filter(id__in=team_ids))
        Team.objects.filter(id__in=team_ids).delete()


def delete_project_record(project_id: int) -> None:
    from posthog.models.project import Project

    Project.objects.filter(id=project_id).delete()


def delete_organization_record(organization_id: str) -> None:
    from posthog.models.organization import Organization

    Organization.objects.filter(id=organization_id).delete()


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
