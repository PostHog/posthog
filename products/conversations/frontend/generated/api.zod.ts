/**
 * Auto-generated Zod validation schemas from the Django backend OpenAPI schema.
 * To modify these schemas, update the Django serializers or views, then run:
 *   hogli build:openapi
 * Questions or issues? #team-devex on Slack
 *
 * PostHog API - generated
 * OpenAPI spec version: 1.0.0
 */
import * as zod from 'zod'

/**
 * Unified endpoint that handles both conversation creation and streaming.
 *
 * - If message is provided: Start new conversation processing
 * - If no message: Stream from existing conversation
 */
export const conversationsCreateBodyContentMax = 40000

export const conversationsCreateBodyIsSandboxDefault = false

export const ConversationsCreateBody = /* @__PURE__ */ zod
    .object({
        content: zod.string().max(conversationsCreateBodyContentMax).nullable(),
        conversation: zod.uuid(),
        contextual_tools: zod.record(zod.string(), zod.unknown()).optional(),
        ui_context: zod.unknown().optional(),
        billing_context: zod.unknown().optional(),
        trace_id: zod.uuid(),
        session_id: zod.string().optional(),
        agent_mode: zod
            .enum([
                'product_analytics',
                'sql',
                'session_replay',
                'error_tracking',
                'plan',
                'execution',
                'survey',
                'research',
                'flags',
                'llm_analytics',
                'sandbox',
                'user_interview',
                'customer_analytics',
            ])
            .optional()
            .describe(
                '\* `product_analytics` - product_analytics\n\* `sql` - sql\n\* `session_replay` - session_replay\n\* `error_tracking` - error_tracking\n\* `plan` - plan\n\* `execution` - execution\n\* `survey` - survey\n\* `research` - research\n\* `flags` - flags\n\* `llm_analytics` - llm_analytics\n\* `sandbox` - sandbox\n\* `user_interview` - user_interview\n\* `customer_analytics` - customer_analytics'
            ),
        is_sandbox: zod.boolean().default(conversationsCreateBodyIsSandboxDefault),
        resume_payload: zod.unknown().optional(),
    })
    .describe('Serializer for appending a message to an existing conversation without triggering AI processing.')

/**
 * Appends a message to an existing conversation without triggering AI processing.
 * This is used for client-side generated messages that need to be persisted
 * (e.g., support ticket confirmation messages).
 */
export const conversationsAppendMessageCreateBodyContentMax = 10000

export const ConversationsAppendMessageCreateBody = /* @__PURE__ */ zod
    .object({
        content: zod.string().max(conversationsAppendMessageCreateBodyContentMax),
    })
    .describe('Serializer for appending a message to an existing conversation without triggering AI processing.')

/**
 * Cancel the conversation's in-progress LangGraph run.
 */
export const ConversationsCancelPartialUpdateBody = /* @__PURE__ */ zod.looseObject({})

/**
 * Create-or-resume a sandbox conversation — the single sandbox session opener. With `content`, processes the turn (first message, in-progress follow-up, or terminal resume); without `content`, warms a sandbox that idles awaiting the first message. Returns the `(task, run)` handle the frontend opens SSE against. The conversation row is created on first use from the URL id.
 */
export const conversationsOpenCreateBodyContentMax = 40000

export const ConversationsOpenCreateBody = /* @__PURE__ */ zod
    .object({
        content: zod
            .string()
            .max(conversationsOpenCreateBodyContentMax)
            .nullish()
            .describe(
                "The user's message text. Omit or null to warm a sandbox (boot + idle) ahead of the first message."
            ),
        trace_id: zod
            .uuid()
            .optional()
            .describe("Client-generated trace id correlated with the resulting Run's SSE stream."),
        attached_context: zod
            .array(
                zod
                    .object({
                        type: zod
                            .enum([
                                'action',
                                'dashboard',
                                'error_tracking_issue',
                                'evaluation',
                                'event',
                                'insight',
                                'notebook',
                                'text',
                            ])
                            .describe(
                                '\* `action` - action\n\* `dashboard` - dashboard\n\* `error_tracking_issue` - error_tracking_issue\n\* `evaluation` - evaluation\n\* `event` - event\n\* `insight` - insight\n\* `notebook` - notebook\n\* `text` - text'
                            )
                            .describe(
                                'Attachment kind. Entity types carry `id` (+ optional `name`); `text` carries `value`.\n\n\* `action` - action\n\* `dashboard` - dashboard\n\* `error_tracking_issue` - error_tracking_issue\n\* `evaluation` - evaluation\n\* `event` - event\n\* `insight` - insight\n\* `notebook` - notebook\n\* `text` - text'
                            ),
                        id: zod
                            .unknown()
                            .optional()
                            .describe(
                                'Entity identifier — integer for `dashboard`\/`action`, string short_id\/UUID otherwise. Absent for `text`.'
                            ),
                        name: zod
                            .string()
                            .optional()
                            .describe('Optional human-readable label rendered in the context block.'),
                        value: zod.string().optional().describe('Free-text content. Only for `text` attachments.'),
                    })
                    .describe('One typed attachment carried by a sandbox message.')
            )
            .optional()
            .describe('Typed PostHog entities (and free text) attached to this message.'),
        initial_permission_mode: zod
            .enum(['default', 'acceptEdits', 'plan', 'bypassPermissions', 'auto'])
            .describe(
                '\* `default` - default\n\* `acceptEdits` - acceptEdits\n\* `plan` - plan\n\* `bypassPermissions` - bypassPermissions\n\* `auto` - auto'
            )
            .optional()
            .describe(
                'Initial permission mode for the sandbox agent session. Defaults to `auto`, which allows safe tool use while preserving explicit confirmations.\n\n\* `default` - default\n\* `acceptEdits` - acceptEdits\n\* `plan` - plan\n\* `bypassPermissions` - bypassPermissions\n\* `auto` - auto'
            ),
        task_id: zod
            .uuid()
            .optional()
            .describe(
                "Bind a brand-new sandbox conversation to an existing Task so the first message resumes that Task's run. Honored only when this request creates the conversation row; ignored for an already-existing conversation."
            ),
        model: zod
            .string()
            .nullish()
            .describe(
                "LLM model identifier for the sandbox agent's Claude runtime. Omit or null to use the runtime default. Only applied when this request creates a new Run (first message or resume after a terminal Run) — ignored for a follow-up onto an in-progress Run."
            ),
        reasoning_effort: zod
            .union([
                zod
                    .enum(['low', 'medium', 'high', 'xhigh', 'max'])
                    .describe(
                        '\* `low` - low\n\* `medium` - medium\n\* `high` - high\n\* `xhigh` - xhigh\n\* `max` - max'
                    ),
                zod.null(),
            ])
            .optional()
            .describe(
                "Reasoning effort to request for `model`, when that model exposes an effort control. Requires `model` to be set; validated together against the model's supported efforts.\n\n\* `low` - low\n\* `medium` - medium\n\* `high` - high\n\* `xhigh` - xhigh\n\* `max` - max"
            ),
    })
    .describe(
        'Request body for `POST \/conversations\/{id}\/open\/`. A string `content` processes a turn; a\nnull\/absent `content` warms a sandbox that idles awaiting the first message.'
    )

export const ConversationsQueueCreateBody = /* @__PURE__ */ zod.looseObject({})

export const ConversationsQueuePartialUpdateBody = /* @__PURE__ */ zod.looseObject({})

export const ConversationsQueueClearCreateBody = /* @__PURE__ */ zod.looseObject({})

export const ConversationsTicketsCreateBody = /* @__PURE__ */ zod
    .object({
        status: zod
            .enum(['new', 'open', 'pending', 'on_hold', 'resolved'])
            .describe(
                '\* `new` - New\n\* `open` - Open\n\* `pending` - Pending\n\* `on_hold` - On hold\n\* `resolved` - Resolved'
            )
            .optional()
            .describe(
                'Ticket status: new, open, pending, on_hold, or resolved\n\n\* `new` - New\n\* `open` - Open\n\* `pending` - Pending\n\* `on_hold` - On hold\n\* `resolved` - Resolved'
            ),
        priority: zod
            .union([
                zod.enum(['low', 'medium', 'high']).describe('\* `low` - Low\n\* `medium` - Medium\n\* `high` - High'),
                zod.enum(['']),
                zod.null(),
            ])
            .optional()
            .describe(
                'Ticket priority: low, medium, or high. Null if unset.\n\n\* `low` - Low\n\* `medium` - Medium\n\* `high` - High'
            ),
        anonymous_traits: zod.unknown().optional().describe('Customer-provided traits such as name and email'),
        ai_resolved: zod.boolean().optional(),
        escalation_reason: zod.string().nullish(),
        sla_due_at: zod.iso
            .datetime({ offset: true })
            .nullish()
            .describe('SLA deadline set via workflows. Null means no SLA.'),
        snoozed_until: zod.iso.datetime({ offset: true }).nullish(),
        tags: zod.array(zod.unknown()).optional(),
    })
    .describe('Serializer mixin that handles tags for objects.')

/**
 * Handle ticket updates including assignee changes.
 */
export const ConversationsTicketsUpdateBody = /* @__PURE__ */ zod
    .object({
        status: zod
            .enum(['new', 'open', 'pending', 'on_hold', 'resolved'])
            .describe(
                '\* `new` - New\n\* `open` - Open\n\* `pending` - Pending\n\* `on_hold` - On hold\n\* `resolved` - Resolved'
            )
            .optional()
            .describe(
                'Ticket status: new, open, pending, on_hold, or resolved\n\n\* `new` - New\n\* `open` - Open\n\* `pending` - Pending\n\* `on_hold` - On hold\n\* `resolved` - Resolved'
            ),
        priority: zod
            .union([
                zod.enum(['low', 'medium', 'high']).describe('\* `low` - Low\n\* `medium` - Medium\n\* `high` - High'),
                zod.enum(['']),
                zod.null(),
            ])
            .optional()
            .describe(
                'Ticket priority: low, medium, or high. Null if unset.\n\n\* `low` - Low\n\* `medium` - Medium\n\* `high` - High'
            ),
        anonymous_traits: zod.unknown().optional().describe('Customer-provided traits such as name and email'),
        ai_resolved: zod.boolean().optional(),
        escalation_reason: zod.string().nullish(),
        sla_due_at: zod.iso
            .datetime({ offset: true })
            .nullish()
            .describe('SLA deadline set via workflows. Null means no SLA.'),
        snoozed_until: zod.iso.datetime({ offset: true }).nullish(),
        tags: zod.array(zod.unknown()).optional(),
    })
    .describe('Serializer mixin that handles tags for objects.')

export const ConversationsTicketsPartialUpdateBody = /* @__PURE__ */ zod
    .object({
        status: zod
            .enum(['new', 'open', 'pending', 'on_hold', 'resolved'])
            .describe(
                '\* `new` - New\n\* `open` - Open\n\* `pending` - Pending\n\* `on_hold` - On hold\n\* `resolved` - Resolved'
            )
            .optional()
            .describe(
                'Ticket status: new, open, pending, on_hold, or resolved\n\n\* `new` - New\n\* `open` - Open\n\* `pending` - Pending\n\* `on_hold` - On hold\n\* `resolved` - Resolved'
            ),
        priority: zod
            .union([
                zod.enum(['low', 'medium', 'high']).describe('\* `low` - Low\n\* `medium` - Medium\n\* `high` - High'),
                zod.enum(['']),
                zod.null(),
            ])
            .optional()
            .describe(
                'Ticket priority: low, medium, or high. Null if unset.\n\n\* `low` - Low\n\* `medium` - Medium\n\* `high` - High'
            ),
        anonymous_traits: zod.unknown().optional().describe('Customer-provided traits such as name and email'),
        ai_resolved: zod.boolean().optional(),
        escalation_reason: zod.string().nullish(),
        sla_due_at: zod.iso
            .datetime({ offset: true })
            .nullish()
            .describe('SLA deadline set via workflows. Null means no SLA.'),
        snoozed_until: zod.iso.datetime({ offset: true }).nullish(),
        tags: zod.array(zod.unknown()).optional(),
    })
    .describe('Serializer mixin that handles tags for objects.')

/**
 * Post a reply or internal note to a ticket.
 *
 * With is_private=false, the reply is delivered to the customer via the
 * ticket's channel (email, Slack, Teams, GitHub). With is_private=true,
 * the message is stored as an internal note only visible to team members.
 */
export const conversationsTicketsReplyCreateBodyMessageMax = 5000

export const conversationsTicketsReplyCreateBodyIsPrivateDefault = false

export const ConversationsTicketsReplyCreateBody = /* @__PURE__ */ zod
    .object({
        message: zod.string().max(conversationsTicketsReplyCreateBodyMessageMax).describe('Reply content in markdown.'),
        is_private: zod
            .boolean()
            .default(conversationsTicketsReplyCreateBodyIsPrivateDefault)
            .describe(
                "If true, store as an internal note (not sent to the customer). If false, the reply is delivered to the customer over the ticket's channel."
            ),
        rich_content: zod.unknown().optional().describe('Optional TipTap rich content JSON for formatted messages.'),
    })
    .describe('Payload for posting a reply or internal note to a ticket.')

/**
 * Update the status of multiple tickets in a single request.
 *
 * Only tickets belonging to the current team are affected; other-team UUIDs
 * are silently ignored.  Tickets already in the requested status are skipped.
 */
export const conversationsTicketsBulkUpdateStatusCreateBodyIdsMax = 500

export const ConversationsTicketsBulkUpdateStatusCreateBody = /* @__PURE__ */ zod.object({
    ids: zod
        .array(zod.uuid())
        .max(conversationsTicketsBulkUpdateStatusCreateBodyIdsMax)
        .describe('List of ticket UUIDs to update.'),
    status: zod
        .enum(['new', 'open', 'pending', 'on_hold', 'resolved'])
        .describe(
            '\* `new` - New\n\* `open` - Open\n\* `pending` - Pending\n\* `on_hold` - On hold\n\* `resolved` - Resolved'
        )
        .describe(
            'New status to apply to all selected tickets: new, open, pending, on_hold, or resolved.\n\n\* `new` - New\n\* `open` - Open\n\* `pending` - Pending\n\* `on_hold` - On hold\n\* `resolved` - Resolved'
        ),
})

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
export const conversationsTicketsBulkUpdateTagsCreateBodyIdsMax = 500

export const ConversationsTicketsBulkUpdateTagsCreateBody = /* @__PURE__ */ zod.object({
    ids: zod
        .array(zod.number())
        .max(conversationsTicketsBulkUpdateTagsCreateBodyIdsMax)
        .describe('List of object IDs to update tags on.'),
    action: zod
        .enum(['add', 'remove', 'set'])
        .describe('\* `add` - add\n\* `remove` - remove\n\* `set` - set')
        .describe(
            "'add' merges with existing tags, 'remove' deletes specific tags, 'set' replaces all tags.\n\n\* `add` - add\n\* `remove` - remove\n\* `set` - set"
        ),
    tags: zod.array(zod.string()).describe('Tag names to add, remove, or set.'),
})

/**
 * Create a new outbound ticket and send the first message to the customer.
 */
export const conversationsTicketsComposeCreateBodyRecipientDistinctIdMax = 400

export const conversationsTicketsComposeCreateBodyEmailSubjectMax = 500

export const conversationsTicketsComposeCreateBodyMessageMax = 5000

export const ConversationsTicketsComposeCreateBody = /* @__PURE__ */ zod.object({
    recipient_email: zod.email().describe('Recipient email address.'),
    recipient_distinct_id: zod
        .string()
        .max(conversationsTicketsComposeCreateBodyRecipientDistinctIdMax)
        .optional()
        .describe('PostHog distinct_id to link the ticket to a person. Falls back to recipient_email.'),
    email_subject: zod
        .string()
        .max(conversationsTicketsComposeCreateBodyEmailSubjectMax)
        .optional()
        .describe('Email subject line.'),
    email_config_id: zod.uuid().describe('ID of the EmailChannel to send from.'),
    message: zod.string().max(conversationsTicketsComposeCreateBodyMessageMax).describe('Message content in markdown.'),
    rich_content: zod.unknown().optional().describe('TipTap rich content JSON for formatted messages.'),
})

export const conversationsViewsCreateBodyNameMax = 400

export const ConversationsViewsCreateBody = /* @__PURE__ */ zod.object({
    name: zod.string().max(conversationsViewsCreateBodyNameMax),
    filters: zod
        .record(zod.string(), zod.unknown())
        .optional()
        .describe(
            'Saved ticket filter criteria. May contain status, priority, channel, sla, assignee, tags, dateFrom, dateTo, and sorting keys.'
        ),
})
