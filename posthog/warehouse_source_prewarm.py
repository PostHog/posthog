import time

from django.conf import settings

import structlog

logger = structlog.get_logger(__name__)


def prewarm_warehouse_source_registry() -> None:
    """Load the full warehouse source catalog (every vendor SDK) at web-worker startup so
    the worker's first warehouse query doesn't pay the multi-second import at request time.

    Gated by PREWARM_WAREHOUSE_SOURCE_REGISTRY and best-effort by design: on failure the
    worker starts cold and the registry's lazy loading retries on first use (its loaded
    flag flips only on success). A broken catalog must not fail startup of a web tier
    that mostly serves non-warehouse traffic, especially with worker respawning on.
    """
    if not settings.PREWARM_WAREHOUSE_SOURCE_REGISTRY:
        return

    logger.info("warehouse_source_registry_prewarm_started")
    start = time.monotonic()
    try:
        from products.warehouse_sources.backend.facade.source_management import (  # noqa: PLC0415 — keeps the source catalog's vendor SDKs off startup for processes that don't opt in
            SourceRegistry,
        )

        sources = SourceRegistry.get_all_sources()
    except Exception:
        logger.exception("warehouse_source_registry_prewarm_failed")
        return
    logger.info(
        "warehouse_source_registry_prewarm_completed",
        elapsed_ms=round((time.monotonic() - start) * 1000),
        source_count=len(sources),
    )
