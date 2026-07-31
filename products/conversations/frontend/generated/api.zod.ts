/**
 * Auto-generated Zod validation schemas from the Django backend OpenAPI schema.
 * To modify these schemas, update the Django serializers or views, then run:
 *   hogli build:openapi
 * Questions or issues? #team-devex on Slack
 *
 * PostHog API - generated
 * OpenAPI spec version: 1.0.0
 */
import {
    AiFeedbackRequestApi,
    BulkUpdateStatusRequestApi,
    BulkUpdateTagsRequestApi,
    ComposeTicketApi,
    ConversationApi,
    MessageApi,
    MessageMinimalApi,
    PatchedConversationApi,
    PatchedTicketApi,
    PatchedTicketViewApi,
    SandboxOpenApi,
    TicketApi,
    TicketReplyRequestApi,
    TicketViewApi,
    ZendeskImportStartApi,
} from './api.zod.schemas'

/**
 * Unified endpoint that handles both conversation creation and streaming.
 *
 * - If message is provided: Start new conversation processing
 * - If no message: Stream from existing conversation
 */
export const ConversationsCreateBody = MessageApi

/**
 * Appends a message to an existing conversation without triggering AI processing.
 * This is used for client-side generated messages that need to be persisted
 * (e.g., support ticket confirmation messages).
 */
export const ConversationsAppendMessageCreateBody = MessageMinimalApi

/**
 * Cancel the conversation's in-progress LangGraph run.
 */
export const ConversationsCancelPartialUpdateBody = PatchedConversationApi

/**
 * Create-or-resume a sandbox conversation — the single sandbox session opener. With `content`, processes the turn (first message, in-progress follow-up, or terminal resume); without `content`, warms a sandbox that idles awaiting the first message. Returns the `(task, run)` handle the frontend opens SSE against. The conversation row is created on first use from the URL id.
 */
export const ConversationsOpenCreateBody = SandboxOpenApi

export const ConversationsQueueCreateBody = ConversationApi

export const ConversationsQueuePartialUpdateBody = PatchedConversationApi

export const ConversationsQueueClearCreateBody = ConversationApi

/**
 * Handle ticket updates including assignee changes.
 */
export const ConversationsTicketsUpdateBody = TicketApi

export const ConversationsTicketsPartialUpdateBody = PatchedTicketApi

/**
 * Record reviewer feedback on an AI reply, captured to the internal analytics project.
 */
export const ConversationsTicketsAiFeedbackCreateBody = AiFeedbackRequestApi

/**
 * Post a reply or internal note to a ticket.
 *
 * With is_private=false, the reply is delivered to the customer via the
 * ticket's channel (email, Slack, Teams, GitHub). With is_private=true,
 * the message is stored as an internal note only visible to team members.
 */
export const ConversationsTicketsReplyCreateBody = TicketReplyRequestApi

/**
 * Update the status of multiple tickets in a single request.
 *
 * Only tickets belonging to the current team are affected; other-team UUIDs
 * are silently ignored. Tickets the caller lacks editor-level access to (denied
 * or view-only via object-level access control) are silently skipped too, the
 * same way single-ticket updates enforce object-level access via get_object().
 * Tickets already in the requested status are skipped.
 */
export const ConversationsTicketsBulkUpdateStatusCreateBody = BulkUpdateStatusRequestApi

/**
 * Bulk update tags on multiple objects.
 *
 * PAT access: this action has no ``required_scopes=`` on the decorator —
 * inheriting viewsets must add ``"bulk_update_tags"`` to their
 * ``scope_object_write_actions`` list to accept personal API keys.
 * Without that opt-in, ``APIScopePermission`` rejects PAT requests with
 * "This action does not support personal API key access". Done per-viewset
 * so granting ``<scope>:write`` for one resource doesn't leak access to
 * sibling resources that share this mixin.
 *
 * Accepts:
 * - {"ids": [...], "action": "add"|"remove"|"set", "tags": ["tag1", "tag2"]}
 *
 * Actions:
 * - "add": Add tags to existing tags on each object
 * - "remove": Remove specific tags from each object
 * - "set": Replace all tags on each object with the provided list
 */
export const ConversationsTicketsBulkUpdateTagsCreateBody = BulkUpdateTagsRequestApi

/**
 * Create a new outbound ticket and send the first message to the customer.
 */
export const ConversationsTicketsComposeCreateBody = ComposeTicketApi

export const ConversationsViewsCreateBody = TicketViewApi

export const ConversationsViewsPartialUpdateBody = PatchedTicketViewApi

export const ConversationsZendeskImportsCreateBody = ZendeskImportStartApi
