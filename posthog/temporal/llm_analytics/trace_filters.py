from __future__ import annotations

import asyncio
from datetime import timedelta

import structlog
import temporalio.activity
from temporalio.common import RetryPolicy

from products.llm_analytics.backend.trace_filters import get_team_trace_filters_bulk

logger = structlog.get_logger(__name__)

TRACE_FILTERS_ACTIVITY_TIMEOUT = timedelta(seconds=30)
TRACE_FILTERS_ACTIVITY_RETRY_POLICY = RetryPolicy(maximum_attempts=2)


@temporalio.activity.defn
async def get_team_trace_filters(team_ids: list[int]) -> dict[str, list[dict]]:
    if not team_ids:
        return {}

    try:
        return await asyncio.to_thread(get_team_trace_filters_bulk, team_ids)
    except Exception:
        logger.exception("Failed to fetch LLMA trace filters", team_ids=team_ids)
        raise
