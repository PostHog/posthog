from collections.abc import Callable, Mapping
from datetime import timedelta
from uuid import UUID

import structlog

from posthog.exceptions_capture import capture_exception
from posthog.models import User
from posthog.models.activity_logging.activity_log import Change, Detail, log_activity
from posthog.rbac.query_access import assert_user_can_read_query

from products.access_control.backend.facade.user_access_control import UserAccessControl
from products.data_modeling.backend.facade.contracts import (
    MaterializationFailedError,
    MaterializationForbiddenError,
    MaterializationRefusedError,
    UnstorableColumnTypeError,
)
from products.data_modeling.backend.logic.freshness import UnsatisfiableFrequencyError, UnsupportedFrequencyTargetError
from products.data_modeling.backend.logic.materialized_column_types import check_saved_query_column_types
from products.data_modeling.backend.logic.node_frequency import SavedQueryFrequencyBounds, saved_query_target_bounds
from products.data_modeling.backend.logic.node_materialization import SavedQueryNotFoundError
from products.data_modeling.backend.logic.saved_query_dag_sync import update_node_type
from products.data_modeling.backend.logic.schedule_reconcile import check_saved_query_frequency_target
from products.data_modeling.backend.models.datawarehouse_saved_query import DataWarehouseSavedQuery
from products.data_modeling.backend.models.node import NodeType

logger = structlog.get_logger(__name__)

VisibleBlockerNames = Callable[[SavedQueryFrequencyBounds], Mapping[str, str]]

MANAGED_VIEWSET_REFUSAL = "Cannot materialize a query from a managed viewset."
EDIT_ACCESS_REFUSAL = "You need edit access to this view to materialize it."
LINEAGE_CHANGED_REFUSAL = "This view's lineage changed while we were setting it up. Reopen it and pick a cadence again."
MATERIALIZATION_FAILED_MESSAGE = "Materialization failed. Please try again or contact support."
MATERIALIZATION_ENABLED_ACTIVITY = "materialization_enabled"
SAVED_QUERY_ACTIVITY_SCOPE = "DataWarehouseSavedQuery"


def enable_saved_query_materialization(
    team_id: int,
    saved_query_id: UUID | str,
    *,
    user: User,
    sync_frequency_interval: timedelta | None,
    visible_blocker_names: VisibleBlockerNames,
    was_impersonated: bool,
) -> None:
    """Materialize a saved query at the given cadence and start its first run."""
    saved_query = (
        DataWarehouseSavedQuery.objects.filter(team_id=team_id, id=saved_query_id).exclude(deleted=True).first()
    )
    if saved_query is None:
        raise SavedQueryNotFoundError(f"Saved query {saved_query_id} not found for team {team_id}")
    _enable_materialization(
        saved_query,
        user=user,
        sync_frequency_interval=sync_frequency_interval,
        visible_blocker_names=visible_blocker_names,
        was_impersonated=was_impersonated,
    )


def _enable_materialization(
    saved_query: DataWarehouseSavedQuery,
    *,
    user: User,
    sync_frequency_interval: timedelta | None,
    visible_blocker_names: VisibleBlockerNames,
    was_impersonated: bool,
) -> None:
    if saved_query.managed_viewset_id is not None:
        raise MaterializationRefusedError(MANAGED_VIEWSET_REFUSAL)

    _require_edit_access(saved_query, user)
    assert_user_can_read_query(saved_query.query, saved_query.team_id, user)
    check_saved_query_column_types(saved_query.team_id, saved_query.pk)

    if sync_frequency_interval is not None:
        # Ask before writing, so the ordinary refusal never has to be undone below. Names only
        # what this caller may read, matching the bounds payload — otherwise one rejected
        # materialize reads back a node they were never shown.
        _refuse_a_cadence_the_lineage_forbids(saved_query, sync_frequency_interval, visible_blocker_names)

    previous_interval = saved_query.sync_frequency_interval
    previously_materialized = saved_query.is_materialized
    _save_materialization(saved_query, is_materialized=True, sync_frequency_interval=sync_frequency_interval)

    # Enable materialization - this handles model path setup and schedule creation
    # If this fails, it will set is_materialized = False
    try:
        saved_query.schedule_materialization(trigger_immediate_run=True, triggered_by_id=user.pk)
    except UnstorableColumnTypeError:
        _save_materialization(
            saved_query, is_materialized=previously_materialized, sync_frequency_interval=previous_interval
        )
        raise
    except (UnsatisfiableFrequencyError, UnsupportedFrequencyTargetError) as error:
        # The check above already refused every cadence the lineage forbids, so reaching here
        # means the lineage moved mid-request. Say so plainly rather than forwarding a message
        # built from unredacted names. `schedule_materialization` re-raises these without
        # applying its disable-on-failure contract, and this action is not inside an atomic
        # block, so undo the enable by hand: otherwise the 400 leaves is_materialized=True
        # behind and the UI reads the rejection as a success.
        _save_materialization(
            saved_query, is_materialized=previously_materialized, sync_frequency_interval=previous_interval
        )
        raise MaterializationRefusedError(LINEAGE_CHANGED_REFUSAL) from error

    # Refresh from DB to check if schedule_materialization set is_materialized = False on failure
    saved_query.refresh_from_db()
    if saved_query.is_materialized is False:
        raise MaterializationFailedError(MATERIALIZATION_FAILED_MESSAGE)

    _mark_nodes_materialized(saved_query)
    _log_materialization_enabled(
        saved_query,
        user=user,
        was_impersonated=was_impersonated,
        previous_interval=previous_interval,
        sync_frequency_interval=sync_frequency_interval,
    )


def _require_edit_access(saved_query: DataWarehouseSavedQuery, user: User) -> None:
    access = UserAccessControl(user=user, team=saved_query.team)
    if not access.check_access_level_for_object(saved_query, "editor"):
        raise MaterializationForbiddenError(EDIT_ACCESS_REFUSAL)


def _refuse_a_cadence_the_lineage_forbids(
    saved_query: DataWarehouseSavedQuery,
    sync_frequency_interval: timedelta,
    visible_blocker_names: VisibleBlockerNames,
) -> None:
    bounds = saved_query_target_bounds(saved_query.team_id, saved_query.pk)
    try:
        check_saved_query_frequency_target(
            saved_query,
            sync_frequency_interval,
            visible_names=visible_blocker_names(bounds) if bounds else {},
        )
    except (UnsatisfiableFrequencyError, UnsupportedFrequencyTargetError) as error:
        raise MaterializationRefusedError(str(error)) from error


def _save_materialization(
    saved_query: DataWarehouseSavedQuery, *, is_materialized: bool | None, sync_frequency_interval: timedelta | None
) -> None:
    saved_query.sync_frequency_interval = sync_frequency_interval
    saved_query.is_materialized = is_materialized
    saved_query.save(update_fields=["sync_frequency_interval", "is_materialized"])


def _mark_nodes_materialized(saved_query: DataWarehouseSavedQuery) -> None:
    # set data modeling node type to matview
    try:
        update_node_type(saved_query, NodeType.MAT_VIEW)
    except Exception as e:
        capture_exception(e)
        logger.exception("Failed to update node type to matview", saved_query_name=saved_query.name)


def _log_materialization_enabled(
    saved_query: DataWarehouseSavedQuery,
    *,
    user: User,
    was_impersonated: bool,
    previous_interval: timedelta | None,
    sync_frequency_interval: timedelta | None,
) -> None:
    log_activity(
        organization_id=saved_query.team.organization_id,
        team_id=saved_query.team_id,
        user=user,
        was_impersonated=was_impersonated,
        item_id=saved_query.id,
        scope=SAVED_QUERY_ACTIVITY_SCOPE,
        activity=MATERIALIZATION_ENABLED_ACTIVITY,
        detail=Detail(
            name=saved_query.name,
            changes=[
                Change(
                    field="sync_frequency_interval",
                    action="changed",
                    type=SAVED_QUERY_ACTIVITY_SCOPE,
                    before=str(previous_interval) if previous_interval else None,
                    after=str(sync_frequency_interval),
                ),
            ],
        ),
    )
