from .activities import get_org_batch_page, push_digest_metrics_activity, run_digest_batch, send_test_digest
from .workflows import DataCatalogWeeklyDigestTestWorkflow, DataCatalogWeeklyDigestWorkflow

WORKFLOWS = [DataCatalogWeeklyDigestWorkflow, DataCatalogWeeklyDigestTestWorkflow]
ACTIVITIES = [
    get_org_batch_page,
    run_digest_batch,
    push_digest_metrics_activity,
    send_test_digest,
]
