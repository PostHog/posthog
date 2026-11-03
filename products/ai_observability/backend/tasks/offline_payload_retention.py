import time
from uuid import uuid4

import structlog
from celery import shared_task

from posthog.ph_client import ph_scoped_capture
from posthog.scoping_audit import skip_team_scope_audit
from posthog.utils import get_instance_region

from products.ai_observability.backend.offline_payload_retention import OfflinePayloadRetention

logger = structlog.get_logger(__name__)


@shared_task(ignore_result=True, soft_time_limit=240, time_limit=300)
@skip_team_scope_audit
def expire_offline_evaluation_payloads() -> None:
    sweep = OfflinePayloadRetention()
    started = time.monotonic()
    status = "failed"
    try:
        sweep.run()
        status = "completed"
    finally:
        properties = {
            "run_id": str(uuid4()),
            "status": status,
            "batches": sweep.batches,
            "item_payloads_expired": sweep.item_payloads_expired,
            "result_payloads_expired": sweep.result_payloads_expired,
            "payloads_expired": sweep.item_payloads_expired + sweep.result_payloads_expired,
            "budget_exhausted": sweep.budget_exhausted,
            "duration_seconds": time.monotonic() - started,
            "$process_person_profile": False,
        }
        logger.info("offline_evaluation_payload_retention_run", **properties)
        try:
            with ph_scoped_capture(region=get_instance_region() or "US") as capture:
                capture(
                    distinct_id="offline-evaluation-payload-retention",
                    event="offline evaluation payload retention run",
                    properties=properties,
                )
        except Exception:
            logger.exception("offline_evaluation_payload_retention_capture_failed")
