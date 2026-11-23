from typing import TYPE_CHECKING

from .activities import get_org_batch_page, push_digest_metrics_activity, run_digest_batch, send_test_digest
from .workflows import DataCatalogWeeklyDigestTestWorkflow, DataCatalogWeeklyDigestWorkflow

if TYPE_CHECKING:
    from posthog.temporal.common.registration import ActivityDefinition

WORKFLOWS = [DataCatalogWeeklyDigestWorkflow, DataCatalogWeeklyDigestTestWorkflow]
ACTIVITIES: list[ActivityDefinition] = [
    get_org_batch_page,
    run_digest_batch,
    push_digest_metrics_activity,
    send_test_digest,
]
