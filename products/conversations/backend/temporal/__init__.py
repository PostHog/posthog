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

WORKFLOWS = [
    SupportReplyWorkflow,
    SupportReplyCoordinatorWorkflow,
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
]
