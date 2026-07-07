from products.conversations.backend.temporal.ai_reply.activities.persist_knowledge_gap import (
    support_persist_knowledge_gap_activity,
)
from products.conversations.backend.temporal.coordinator import (
    SupportReplyCoordinatorWorkflow,
    support_collect_eligible_tickets_activity,
)
from products.conversations.backend.temporal.pipeline import (
    SupportReplyWorkflow,
    support_build_context_activity,
    support_classify_activity,
    support_draft_activity,
    support_persist_reply_activity,
    support_record_triage_activity,
    support_refine_queries_activity,
    support_retrieve_activity,
    support_review_reply_activity,
    support_safety_filter_activity,
    support_validate_activity,
)
from products.conversations.backend.temporal.zendesk_import.activities import (
    zendesk_import_batch_activity,
    zendesk_import_enumerate_tickets_activity,
    zendesk_import_update_job_progress_activity,
    zendesk_import_update_job_status_activity,
)
from products.conversations.backend.temporal.zendesk_import.workflows import (
    ZendeskImportBatchWorkflow,
    ZendeskImportCoordinatorWorkflow,
)

WORKFLOWS = [
    SupportReplyWorkflow,
    SupportReplyCoordinatorWorkflow,
    ZendeskImportCoordinatorWorkflow,
    ZendeskImportBatchWorkflow,
]

ACTIVITIES = [
    support_build_context_activity,
    support_safety_filter_activity,
    support_classify_activity,
    support_refine_queries_activity,
    support_retrieve_activity,
    support_draft_activity,
    support_validate_activity,
    support_review_reply_activity,
    support_persist_reply_activity,
    support_persist_knowledge_gap_activity,
    support_record_triage_activity,
    support_collect_eligible_tickets_activity,
    zendesk_import_enumerate_tickets_activity,
    zendesk_import_batch_activity,
    zendesk_import_update_job_status_activity,
    zendesk_import_update_job_progress_activity,
]
