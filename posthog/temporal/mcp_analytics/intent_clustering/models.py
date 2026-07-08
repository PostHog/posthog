"""Data models for the MCP analytics intent clustering workflow.

Kept intentionally small — the pure-function pipeline already lives in
``products/mcp_analytics/backend/intent_clustering.py``; this module just
declares the workflow/activity envelopes that wrap those functions.
"""

from dataclasses import dataclass
from typing import Any

from posthog.temporal.mcp_analytics.intent_clustering.constants import DEFAULT_LOOKBACK_DAYS, DEFAULT_TOP_N_INTENTS


@dataclass
class IntentClusteringWorkflowInputs:
    """Inputs to ``DailyIntentClusteringWorkflow``.

    All numeric knobs default to the same values the Celery task uses today.
    ``user_id`` is preserved so adhoc recomputes can attribute the run in
    ``MCPIntentClusterSnapshot.last_computed_by``.
    """

    team_id: int
    lookback_days: int = DEFAULT_LOOKBACK_DAYS
    top_n: int = DEFAULT_TOP_N_INTENTS
    user_id: int | None = None

    @property
    def properties_to_log(self) -> dict[str, Any]:
        return {"team_id": self.team_id}


@dataclass
class IntentClusteringResult:
    """Result returned by ``DailyIntentClusteringWorkflow``."""

    team_id: int
    n_intents: int
    n_clusters: int
    computed_at: str  # ISO format
