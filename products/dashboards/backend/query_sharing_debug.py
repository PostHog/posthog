from contextvars import ContextVar
from typing import TypedDict

from django.db.models import TextChoices


class DashboardSharingOutcome(TextChoices):
    SHARED = "shared", "Shared"
    SEPARATE = "separate", "Separate"
    FALLBACK = "fallback", "Shared attempt failed"


class SharingExecutionDebug(TypedDict):
    outcome: str
    tile_ids: list[int]
    rule: str
    reason: str


class SharingWorkDebug(TypedDict):
    executions: list[SharingExecutionDebug]
    truncated: bool
    query_count: int
    rows_read: int
    duration_ms: float


class DashboardQuerySharingDebug:
    def __init__(self, tile_id: int) -> None:
        self.tile_id = tile_id
        self.executions: list[SharingExecutionDebug] = []
        self.truncated = False

    def record(self, *, outcome: str, tile_ids: list[int], rule: str = "", reason: str = "") -> None:
        if len(self.executions) >= 64:
            self.truncated = True
            return
        self.executions.append({"outcome": outcome, "tile_ids": tile_ids, "rule": rule, "reason": reason})


sharing_debug: ContextVar[DashboardQuerySharingDebug | None] = ContextVar("dashboard_sharing_debug", default=None)
