import uuid
from typing import Any

from django.utils import timezone

from posthog.models.cohortmembership.query_rewrite import (
    SavedQueryRewrite,
    SqlRewrite,
    rewrite_hogql,
    rewrite_saved_rows,
    runs_on_posthog,
)

from products.data_modeling.backend.models import DataWarehouseSavedQuery


def _rewrite_query(value: Any) -> tuple[Any, list[SqlRewrite]]:
    # A view stores its HogQL at the top level, often without a `kind`.
    if not isinstance(value, dict) or not isinstance(value.get("query"), str) or not runs_on_posthog(value):
        return value, []
    rewrite = rewrite_hogql(value["query"])
    if rewrite is None:
        return value, []
    if rewrite.after is None:
        return value, [rewrite]
    return {**value, "query": rewrite.after}, [rewrite]


def rewrite_cohort_membership_queries(team_id: int, apply: bool) -> list[SavedQueryRewrite]:
    return rewrite_saved_rows(
        DataWarehouseSavedQuery._base_manager.filter(team_id=team_id),
        "query",
        "view",
        _rewrite_query,
        apply,
        # The SQL editor rejects a save from a stale revision, so an open tab cannot save over the rewrite.
        extra_updates=lambda: {"query_revision": uuid.uuid4(), "query_updated_at": timezone.now()},
    )
