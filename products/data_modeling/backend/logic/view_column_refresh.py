from collections.abc import Collection
from datetime import datetime
from enum import Enum, auto
from typing import TYPE_CHECKING
from uuid import UUID

from django.utils import timezone

import structlog
from opentelemetry import trace

from posthog.hogql.database.database import Database

from posthog.clickhouse.client.limit import ConcurrencyLimitExceeded
from posthog.uuidt import UUIDT

from products.access_control.backend.facade.api import get_restricted_properties_with_group_type_index_for_team
from products.access_control.backend.facade.user_access_control import UserAccessControl
from products.data_modeling.backend.logic.saved_query_reads import (
    allowed_saved_query_ids,
    downstream_saved_query_ids,
    saved_query_ids_upstream_first,
)
from products.data_modeling.backend.models.datawarehouse_saved_query import DataWarehouseSavedQuery

if TYPE_CHECKING:
    from posthog.models.team import Team
    from posthog.models.user import User

logger = structlog.get_logger(__name__)
tracer = trace.get_tracer(__name__)


def refresh_view_columns(team: "Team", saved_query_ids: Collection[UUID | str], user: "User | None") -> set[UUID]:
    """Re-infer the stored columns of these views, upstream first, and return the ids whose columns changed.

    With no user, inference runs as the system and bypasses warehouse access control.
    """
    if _infers_masked_columns(team, user):
        return set()
    views = {
        view.id: view
        for view in DataWarehouseSavedQuery.objects.select_related("team")
        .filter(team_id=team.pk, id__in=_saved_query_uuids(saved_query_ids), managed_viewset__isnull=True)
        .exclude(deleted=True)
    }
    changed: set[UUID] = set()
    database: Database | None = None
    for view_id in saved_query_ids_upstream_first(team.pk, set(views)):
        if database is None:
            database = _inference_database(views[view_id], user)
        if database is None:
            continue
        outcome = _refresh_columns(views[view_id], user, database)
        if outcome is _ColumnRefresh.SAVED:
            changed.add(view_id)
        if outcome is not _ColumnRefresh.KEPT:
            database = None
    return changed


def views_updated_since(team: "Team", saved_query_ids: Collection[UUID | str], since: datetime) -> bool:
    """Whether any of these views was written after ``since``, for example by another request's refresh."""
    return DataWarehouseSavedQuery.objects.filter(
        team_id=team.pk, id__in=_saved_query_uuids(saved_query_ids), updated_at__gt=since
    ).exists()


def refresh_downstream_view_columns(team: "Team", saved_query_id: UUID | str, user: "User | None") -> set[UUID]:
    """Re-infer the stored columns of every view that reads from this one, directly or through other views."""
    downstream_ids = downstream_saved_query_ids(team.pk, saved_query_id)
    trace.get_current_span().set_attribute("downstream_view_count", len(downstream_ids))
    return refresh_view_columns(team, _readable_by(team, user, downstream_ids), user)


def _readable_by(team: "Team", user: "User | None", view_ids: Collection[UUID]) -> Collection[UUID]:
    if user is None:
        return view_ids
    return allowed_saved_query_ids(team.pk, UserAccessControl(user=user, team=team), ids=view_ids)


def _saved_query_uuids(saved_query_ids: Collection[UUID | str]) -> list[UUID]:
    return [UUID(str(value)) for value in saved_query_ids if UUIDT.is_valid_uuid(str(value))]


def _infers_masked_columns(team: "Team", user: "User | None") -> bool:
    return bool(get_restricted_properties_with_group_type_index_for_team(user=user, team_id=team.pk))


def _inference_database(view: DataWarehouseSavedQuery, user: "User | None") -> Database | None:
    try:
        return Database.create_for(team=view.team, user=user, bypass_warehouse_access_control=user is None)
    except Exception:
        logger.warning("view_column_refresh_failed", team_id=view.team_id, saved_query_id=str(view.id), exc_info=True)
        return None


class _ColumnRefresh(Enum):
    KEPT = auto()
    SAVED = auto()
    SUPERSEDED = auto()


def _refresh_columns(view: DataWarehouseSavedQuery, user: "User | None", database: Database) -> _ColumnRefresh:
    with tracer.start_as_current_span(
        "view_column_refresh.view", attributes={"saved_query_id": str(view.id)}
    ) as view_span:
        outcome = _infer_and_store_columns(view, user, database)
        view_span.set_attribute("columns_changed", outcome is _ColumnRefresh.SAVED)
        return outcome


def _infer_and_store_columns(view: DataWarehouseSavedQuery, user: "User | None", database: Database) -> _ColumnRefresh:
    # Inference uses the team's default modifiers, so a materialized upstream view is read from its backing table.
    # A query with useMaterializedViews=False reads that view's SQL instead. When the SQL changed and the view has
    # not materialized again, such a query can still fail on stale columns after this refresh. The refresh that
    # runs when materialization publishes the new backing table fixes it.
    try:
        columns = view.get_columns(user=user, bypass_warehouse_access_control=user is None, database=database)
    except ConcurrencyLimitExceeded:
        raise
    except Exception:
        logger.warning("view_column_refresh_failed", team_id=view.team_id, saved_query_id=str(view.id), exc_info=True)
        return _ColumnRefresh.KEPT

    if view.stores_columns(columns):
        return _ColumnRefresh.KEPT

    view.set_columns(columns)
    return _ColumnRefresh.SAVED if _save_columns_unless_query_changed(view) else _ColumnRefresh.SUPERSEDED


def _save_columns_unless_query_changed(view: DataWarehouseSavedQuery) -> bool:
    saved_rows = DataWarehouseSavedQuery.objects.filter(
        team_id=view.team_id, pk=view.pk, query_revision=view.query_revision
    ).update(columns=view.columns, column_order=view.column_order, updated_at=timezone.now())
    return saved_rows == 1
