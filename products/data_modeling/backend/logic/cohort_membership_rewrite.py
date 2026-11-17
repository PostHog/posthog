import uuid
from typing import Any

from django.db import transaction
from django.utils import timezone

import structlog

from posthog.exceptions_capture import capture_exception
from posthog.models.cohortmembership.query_rewrite import (
    SavedQueryRewrite,
    SqlRewrite,
    rewrite_hogql_node,
    rewrite_saved_rows,
)

from products.data_modeling.backend.logic.saved_query_dag_sync import lineage_database, sync_saved_query_to_dag
from products.data_modeling.backend.logic.schedule_reconcile import maybe_reconcile_dag
from products.data_modeling.backend.models import DataWarehouseSavedQuery
from products.data_modeling.backend.models.dag import DAG

logger = structlog.get_logger(__name__)


def _rewrite_query(value: Any) -> tuple[Any, list[SqlRewrite]]:
    # A view stores its HogQL at the top level, often without a `kind`.
    if not isinstance(value, dict):
        return value, []
    rewritten, rewrite = rewrite_hogql_node(value)
    return rewritten, [rewrite] if rewrite is not None else []


def rewrite_cohort_membership_queries(team_id: int, apply: bool) -> list[SavedQueryRewrite]:
    results = rewrite_saved_rows(
        DataWarehouseSavedQuery._base_manager.filter(team_id=team_id),
        "query",
        "view",
        _rewrite_query,
        apply,
        # The SQL editor rejects a save from a stale revision, so an open tab cannot save over the rewrite.
        extra_updates=lambda: {"query_revision": uuid.uuid4(), "query_updated_at": timezone.now()},
    )
    written = [row.pk for row in results if row.written]
    views = DataWarehouseSavedQuery._base_manager.filter(pk__in=written).select_related("team")
    _sync_lineage([view for view in views if view.engine.has_lineage.available])
    return results


def _sync_lineage(views: list[DataWarehouseSavedQuery]) -> None:
    # The update skips the save path, so the DAG still lists `cohort_membership` as a parent until this sync.
    if not views:
        return
    team = views[0].team
    database = lineage_database(team)
    for view in views:
        try:
            with transaction.atomic():
                sync_saved_query_to_dag(view, reconcile=False, database=database)
        except Exception as e:
            # Best effort, as in the SQL editor: the view keeps its old edges until its next save.
            capture_exception(e)
            logger.exception("cohort_membership_rewrite_lineage_sync_failed", saved_query_id=str(view.id))
    # Once for the batch, because each reconcile reads the whole DAG and updates its schedules.
    maybe_reconcile_dag(DAG.get_or_create_default(team))
