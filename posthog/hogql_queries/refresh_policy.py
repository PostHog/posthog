"""Single source of truth for how an insight result is (re)computed per request.

Every HTTP surface that renders insight tiles (the insight detail/list endpoints, the
dashboard detail/stream/run_insights actions, and shared/embedded rendering) funnels into
`InsightSerializer.insight_result`, which computes an `ExecutionMode`. Historically each
surface's *default* (what happens when the client sends no explicit `?refresh=`) was an
accident of which query params its client happened to send, invisible at the route. This
module makes that default explicit and per-surface, in one table, without changing the
rule that an explicit client `?refresh=` always wins.
"""

from enum import StrEnum
from typing import TYPE_CHECKING

from posthog.hogql_queries.query_runner import (
    ExecutionMode,
    SharedExecutionSettings,
    execution_mode_from_refresh,
    shared_insights_execution_mode,
)
from posthog.utils import refresh_requested_by_client

if TYPE_CHECKING:
    from rest_framework.request import Request


class ComputeSurface(StrEnum):
    """The route/caller computing an insight result. Selects the default execution mode
    when the client sends no explicit `?refresh=`; an explicit value always overrides it."""

    INSIGHT_DETAIL = "insight_detail"
    INSIGHT_LIST = "insight_list"
    # An insight rendered as a dashboard tile (insights/{pk}?from_dashboard=…), distinct from the
    # standalone insight editor (INSIGHT_DETAIL) so the two can carry different refresh defaults.
    DASHBOARD_TILE = "dashboard_tile"
    DASHBOARD_DETAIL = "dashboard_detail"
    DASHBOARD_STREAM = "dashboard_stream"
    DASHBOARD_RUN_INSIGHTS = "dashboard_run_insights"
    DASHBOARD_MUTATE = "dashboard_mutate"
    SHARED = "shared"
    LEGACY_UNKNOWN = "legacy_unknown"


# The one place per-surface refresh defaults live. Every surface is CACHE_ONLY_NEVER_CALCULATE
# today, which reproduces the historical behavior (an absent `?refresh=` meant cache-only on
# every route). Listed explicitly per surface (rather than dict.fromkeys) so changing one
# surface's default is a single greppable, independently measurable line to flip — rather than
# editing request handling in each viewset.
SURFACE_DEFAULT_EXECUTION_MODE: dict[ComputeSurface, ExecutionMode] = {
    ComputeSurface.INSIGHT_DETAIL: ExecutionMode.CACHE_ONLY_NEVER_CALCULATE,
    ComputeSurface.INSIGHT_LIST: ExecutionMode.CACHE_ONLY_NEVER_CALCULATE,
    ComputeSurface.DASHBOARD_TILE: ExecutionMode.CACHE_ONLY_NEVER_CALCULATE,
    ComputeSurface.DASHBOARD_DETAIL: ExecutionMode.CACHE_ONLY_NEVER_CALCULATE,
    ComputeSurface.DASHBOARD_STREAM: ExecutionMode.CACHE_ONLY_NEVER_CALCULATE,
    ComputeSurface.DASHBOARD_RUN_INSIGHTS: ExecutionMode.CACHE_ONLY_NEVER_CALCULATE,
    ComputeSurface.DASHBOARD_MUTATE: ExecutionMode.CACHE_ONLY_NEVER_CALCULATE,
    ComputeSurface.SHARED: ExecutionMode.CACHE_ONLY_NEVER_CALCULATE,
    ComputeSurface.LEGACY_UNKNOWN: ExecutionMode.CACHE_ONLY_NEVER_CALCULATE,
}


def _refresh_param_present(request: "Request") -> bool:
    """Whether the client sent a `refresh` param at all (query string or body), regardless of its
    value — so an explicit `refresh=false` is distinguished from an absent param."""
    if request.query_params.get("refresh") is not None:
        return True
    data = getattr(request, "data", None)
    return isinstance(data, dict) and data.get("refresh") is not None


def resolve_execution_mode(
    request: "Request", *, surface: ComputeSurface, is_shared: bool = False
) -> SharedExecutionSettings:
    """Resolve the execution mode (and shared staleness window) for one insight computation.

    Precedence: an explicit `?refresh=` from the client wins; otherwise the surface default.
    Shared/embedded resources are clamped last — anonymous demand must never force a blocking
    recompute — and that clamp also carries the `cache_age_seconds` staleness window. Returns
    a `SharedExecutionSettings(execution_mode, cache_age_seconds)`; `cache_age_seconds` is None
    off the shared path.
    """
    # An explicit ?refresh= (any value, including false/0/no) is honored via
    # execution_mode_from_refresh, matching historical behavior — so a client that opts out of
    # refreshing still gets CACHE_ONLY even after a surface default is flipped off cache-only.
    # The surface default applies only when no refresh param is present at all.
    if _refresh_param_present(request):
        execution_mode = execution_mode_from_refresh(refresh_requested_by_client(request))
    else:
        execution_mode = SURFACE_DEFAULT_EXECUTION_MODE[surface]

    if is_shared:
        return shared_insights_execution_mode(execution_mode)
    return SharedExecutionSettings(execution_mode, None)
