from products.conversations.backend.temporal.coordinator import (
    SupportReplyCoordinatorWorkflow,
    collect_eligible_tickets_activity,
)
from products.conversations.backend.temporal.pipeline import (
    SupportReplyWorkflow,
    build_context_activity,
    draft_activity,
    persist_reply_activity,
    refine_queries_activity,
    retrieve_activity,
    validate_activity,
)

WORKFLOWS = [
    SupportReplyWorkflow,
    SupportReplyCoordinatorWorkflow,
]

ACTIVITIES = [
    build_context_activity,
    refine_queries_activity,
    retrieve_activity,
    draft_activity,
    validate_activity,
    persist_reply_activity,
    collect_eligible_tickets_activity,
]
