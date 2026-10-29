from uuid import UUID

from django.db.models import Q

import structlog
from rest_framework import serializers

from posthog.exceptions_capture import capture_exception
from posthog.models import User
from posthog.models.activity_logging.activity_log import Detail, Trigger, log_activity

from products.data_modeling.backend.logic.node_materialization import SavedQueryNotFoundError
from products.data_modeling.backend.logic.saved_query_dag_sync import HasDependentsError, check_saved_query_deletable
from products.data_modeling.backend.models.datawarehouse_saved_query import DataWarehouseSavedQuery
from products.data_tools.backend.facade.models import DataWarehouseJoin

logger = structlog.get_logger(__name__)

SAVED_QUERY_ACTIVITY_SCOPE = "DataWarehouseSavedQuery"
DELETED_ACTIVITY = "deleted"


def delete_saved_query(saved_query: DataWarehouseSavedQuery) -> None:
    if saved_query.managed_viewset is not None:
        raise serializers.ValidationError(
            "Cannot delete a query from a managed viewset directly. Disable the managed viewset instead."
        )

    try:
        check_saved_query_deletable(saved_query.team_id, saved_query.id)
    except HasDependentsError:
        raise
    except Exception as e:
        capture_exception(e)
        logger.exception("Failed to check dependents of saved query", saved_query_name=saved_query.name)

    for join in DataWarehouseJoin.objects.filter(
        Q(team_id=saved_query.team_id)
        & (Q(source_table_name=saved_query.name) | Q(joining_table_name=saved_query.name))
    ).exclude(deleted=True):
        join.soft_delete()

    saved_query.revert_materialization()
    saved_query.soft_delete()


def delete_saved_query_by_id(
    team_id: int, saved_query_id: UUID, *, user: User, was_impersonated: bool, trigger: Trigger | None = None
) -> None:
    """Delete a live saved query and log it as deleted by `user`."""
    saved_query = (
        DataWarehouseSavedQuery.objects.filter(team_id=team_id, id=saved_query_id).exclude(deleted=True).first()
    )
    if saved_query is None:
        raise SavedQueryNotFoundError(f"Saved query {saved_query_id} not found for team {team_id}")
    name = saved_query.name
    delete_saved_query(saved_query)
    log_activity(
        organization_id=saved_query.team.organization_id,
        team_id=team_id,
        user=user,
        was_impersonated=was_impersonated,
        item_id=saved_query.id,
        scope=SAVED_QUERY_ACTIVITY_SCOPE,
        activity=DELETED_ACTIVITY,
        detail=Detail(name=name, trigger=trigger),
    )
