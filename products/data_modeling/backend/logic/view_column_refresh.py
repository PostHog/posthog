from collections.abc import Collection
from datetime import datetime
from graphlib import TopologicalSorter
from typing import TYPE_CHECKING
from uuid import UUID

from django.utils import timezone

import structlog

from products.access_control.backend.facade.api import get_restricted_properties_with_group_type_index_for_team
from products.data_modeling.backend.logic.saved_query_reads import dependent_saved_query_ids
from products.data_modeling.backend.models.datawarehouse_saved_query import DataWarehouseSavedQuery

if TYPE_CHECKING:
    from posthog.models.team import Team
    from posthog.models.user import User

logger = structlog.get_logger(__name__)


def refresh_view_columns(team: "Team", saved_query_ids: Collection[UUID | str], user: "User | None") -> set[UUID]:
    """Re-infer the stored columns of these views, upstream first, and return the ids whose columns changed."""
    if _infers_masked_columns(team, user):
        return set()
    views = {
        view.id: view
        for view in DataWarehouseSavedQuery.objects.select_related("team")
        .filter(team_id=team.pk, id__in=list(saved_query_ids), managed_viewset__isnull=True)
        .exclude(deleted=True)
    }
    return {view_id for view_id in _upstream_first(team.pk, set(views)) if _refresh_columns(views[view_id], user)}


def views_updated_since(team: "Team", saved_query_ids: Collection[UUID | str], since: datetime) -> bool:
    """Whether any of these views was written after ``since``, for example by another request's refresh."""
    return DataWarehouseSavedQuery.objects.filter(
        team_id=team.pk, id__in=list(saved_query_ids), updated_at__gt=since
    ).exists()


def _infers_masked_columns(team: "Team", user: "User | None") -> bool:
    return bool(get_restricted_properties_with_group_type_index_for_team(user=user, team_id=team.pk))


def _upstream_first(team_id: int, view_ids: set[UUID]) -> list[UUID]:
    sorter: TopologicalSorter[UUID] = TopologicalSorter({view_id: set() for view_id in view_ids})
    for source_id, target_ids in dependent_saved_query_ids(team_id, view_ids).items():
        for target_id in target_ids & view_ids:
            sorter.add(target_id, source_id)
    return list(sorter.static_order())


def _refresh_columns(view: DataWarehouseSavedQuery, user: "User | None") -> bool:
    try:
        columns = view.get_columns(user=user)
    except Exception:
        logger.warning("view_column_refresh_failed", team_id=view.team_id, saved_query_id=str(view.id), exc_info=True)
        return False

    if view.stores_columns(columns):
        return False

    view.set_columns(columns)
    return _save_columns_unless_query_changed(view)


def _save_columns_unless_query_changed(view: DataWarehouseSavedQuery) -> bool:
    saved_rows = DataWarehouseSavedQuery.objects.filter(
        team_id=view.team_id, pk=view.pk, query_revision=view.query_revision
    ).update(columns=view.columns, column_order=view.column_order, updated_at=timezone.now())
    return saved_rows == 1
