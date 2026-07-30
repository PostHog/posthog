"""Maps Temporal task queues to canonical FinOps v2 product names.

Used by the finops interceptor to tag each usage meter with the product that
owns the compute. Dedicated task queues map directly; the general-purpose queue
falls back to "shared" (per-workflow-type mapping is a follow-up).

Canonical product names come from product_crosswalk.json in the finops-numbering
repo. When in doubt, check the crosswalk's identity.values list and crosswalk entries.
"""

from __future__ import annotations

from functools import lru_cache

from django.conf import settings

_FALLBACK_PRODUCT = "shared"


@lru_cache(maxsize=1)
def _build_task_queue_product_map() -> dict[str, str]:
    return {
        settings.BATCH_EXPORTS_TASK_QUEUE: "batch_exports",
        settings.SYNC_BATCH_EXPORTS_TASK_QUEUE: "batch_exports",
        settings.DATA_WAREHOUSE_TASK_QUEUE: "data_warehouse",
        settings.DATA_WAREHOUSE_CDP_PRODUCER_TASK_QUEUE: "data_warehouse",
        settings.DATA_WAREHOUSE_METADATA_TASK_QUEUE: "data_warehouse",
        settings.DATA_MODELING_TASK_QUEUE: "data_warehouse",
        settings.DUCKLAKE_TASK_QUEUE: "data_warehouse",
        settings.SESSION_REPLAY_TASK_QUEUE: "session_replay",
        settings.REPLAY_VISION_TASK_QUEUE: "replay_vision",
        settings.EXPERIMENTS_RECALCULATION_TASK_QUEUE: "experiments",
        settings.TASKS_TASK_QUEUE: "posthog_code",
        settings.MAX_AI_TASK_QUEUE: "posthog_ai",
        settings.ERROR_TRACKING_TASK_QUEUE: "error_tracking",
        settings.ERROR_TRACKING_LIFECYCLE_TASK_QUEUE: "error_tracking",
        settings.LOGS_ALERTING_TASK_QUEUE: "logs",
        settings.MESSAGING_TASK_QUEUE: "workflows_emails",
        settings.WEEKLY_DIGEST_TASK_QUEUE: "growth",
        settings.LLMA_TASK_QUEUE: "ai_observability",
        settings.LLMA_EVALS_TASK_QUEUE: "ai_observability",
        settings.ANALYTICS_PLATFORM_TASK_QUEUE: "platform_and_support",
        settings.BILLING_TASK_QUEUE: "billing-internal",
        settings.STAMPHOG_TASK_QUEUE: "devex-internal",
        settings.EVENT_SCREENSHOTS_TASK_QUEUE: "platform_and_support",
        settings.HEALTH_CHECK_TASK_QUEUE: "shared",
    }


def resolve_product(task_queue: str) -> str:
    """Return the canonical product name for a Temporal task queue."""
    return _build_task_queue_product_map().get(task_queue, _FALLBACK_PRODUCT)
