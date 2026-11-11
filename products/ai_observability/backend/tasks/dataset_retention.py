import time
from uuid import uuid4

import structlog
from celery import shared_task

from posthog.ph_client import ph_scoped_capture
from posthog.scoping_audit import skip_team_scope_audit
from posthog.utils import get_instance_region

from products.ai_observability.backend.dataset_retention import DatasetRetention

logger = structlog.get_logger(__name__)


@shared_task(ignore_result=True, soft_time_limit=240, time_limit=300)
@skip_team_scope_audit
def expire_datasets() -> None:
    sweep = DatasetRetention()
    started = time.monotonic()
    status = "failed"
    try:
        sweep.run()
        status = "disabled" if sweep.disabled else "completed_with_errors" if sweep.datasets_failed else "completed"
    finally:
        properties = {
            "run_id": str(uuid4()),
            "status": status,
            "datasets_expired": sweep.datasets_expired,
            "revisions_expired": sweep.revisions_expired,
            "versions_deleted": sweep.versions_deleted,
            "datasets_deleted": sweep.datasets_deleted,
            "datasets_failed": sweep.datasets_failed,
            "budget_exhausted": sweep.budget_exhausted,
            "duration_seconds": time.monotonic() - started,
            "$process_person_profile": False,
        }
        logger.info("dataset_retention_run", **properties)
        try:
            with ph_scoped_capture(region=get_instance_region() or "US") as capture:
                capture(distinct_id="dataset-retention", event="dataset retention run", properties=properties)
        except Exception:
            logger.exception("dataset_retention_capture_failed")
