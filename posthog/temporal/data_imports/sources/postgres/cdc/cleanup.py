"""Best-effort teardown of Postgres CDC resources when a source is deleted."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from products.data_warehouse.backend.models import ExternalDataSource

logger = logging.getLogger(__name__)


def cleanup_cdc_resources_on_source_deletion(source: ExternalDataSource) -> None:
    """Drop the Temporal schedule (always) + PostHog-managed slot/publication.

    Schedule lives on our side, slot lives on the customer's DB.
    """
    from posthog.temporal.data_imports.sources.postgres.cdc.config import PostgresCDCConfig

    # Schedule key = source id. Delete unconditionally; NotFound is a no-op.
    try:
        from products.data_warehouse.backend.data_load.service import delete_cdc_extraction_schedule

        delete_cdc_extraction_schedule(str(source.id))
    except Exception:
        logger.exception("Failed to delete CDC extraction schedule", extra={"source_id": str(source.id)})

    cdc_config = PostgresCDCConfig.from_source(source)
    if not cdc_config.enabled or cdc_config.management_mode != "posthog":
        return
    if not cdc_config.slot_name or not cdc_config.publication_name:
        return

    try:
        from posthog.temporal.data_imports.sources.postgres.cdc.slot_manager import (
            cdc_pg_connection,
            drop_slot_and_publication,
        )

        with cdc_pg_connection(source, connect_timeout=10) as conn:
            drop_slot_and_publication(conn, cdc_config.slot_name, cdc_config.publication_name)
    except Exception:
        logger.exception(
            "Failed to drop CDC slot/publication on source DB (best-effort)",
            extra={"source_id": str(source.id), "slot_name": cdc_config.slot_name},
        )
