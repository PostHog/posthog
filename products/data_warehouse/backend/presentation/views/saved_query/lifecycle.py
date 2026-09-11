"""Saved-query lifecycle operations."""

from django.db.models import Q

import structlog
from rest_framework import serializers

from posthog.exceptions_capture import capture_exception

from products.data_modeling.backend.facade.models import DataWarehouseSavedQuery
from products.data_tools.backend.facade.models import DataWarehouseJoin

logger = structlog.get_logger(__name__)


def delete_saved_query(saved_query: DataWarehouseSavedQuery) -> None:
    from products.data_modeling.backend.facade.api import HasDependentsError, delete_node_from_dag

    if saved_query.managed_viewset is not None:
        raise serializers.ValidationError(
            "Cannot delete a query from a managed viewset directly. Disable the managed viewset instead."
        )

    try:
        delete_node_from_dag(saved_query)
    except HasDependentsError:
        raise
    except Exception as e:
        capture_exception(e)
        logger.exception("Failed to delete node for saved query", saved_query_name=saved_query.name)

    for join in DataWarehouseJoin.objects.filter(
        Q(team_id=saved_query.team_id)
        & (Q(source_table_name=saved_query.name) | Q(joining_table_name=saved_query.name))
    ).exclude(deleted=True):
        join.soft_delete()

    saved_query.revert_materialization()
    saved_query.soft_delete()
