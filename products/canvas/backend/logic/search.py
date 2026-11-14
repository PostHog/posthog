"""Global search over a project's canvases: standalone freeform canvases the user may open."""

from typing import Any

from django.db.models import F

from posthog.helpers.full_text_search import build_rank

from products.canvas.backend.facade.contracts import CanvasViewer
from products.canvas.backend.facade.enums import CanvasAccess
from products.canvas.backend.logic.access import authorized_canvases
from products.canvas.backend.models import Canvas

SEARCH_FIELDS: dict[str, Any] = {"name": "A"}
SEARCH_RANK_THRESHOLD = 0.05


def search(
    *, viewer: CanvasViewer, query: str | None, limit: int, include_count: bool
) -> tuple[list[dict[str, Any]], int]:
    queryset = authorized_canvases(viewer, CanvasAccess.READ).filter(**Canvas.FILED_ANALYSIS_FILTER)
    if query:
        queryset = queryset.annotate(rank=build_rank(SEARCH_FIELDS, query, config="simple"))
        queryset = queryset.filter(rank__gt=SEARCH_RANK_THRESHOLD).order_by("-rank")
    else:
        queryset = queryset.order_by(F("name").asc(nulls_first=True))
    total_count = queryset.count() if include_count else 0
    fields = ["id", "name", "rank"] if query else ["id", "name"]
    return list(queryset[:limit].values(*fields)), total_count
