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

- If message is provided: Start new conversation processing
- If no message: Stream from existing conversation
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
            ])
            .optional()
            .describe(
                '* `product_analytics` - product_analytics\n* `sql` - sql\n* `session_replay` - session_replay\n* `error_tracking` - error_tracking\n* `plan` - plan\n* `execution` - execution\n* `survey` - survey\n* `research` - research\n* `flags` - flags\n* `llm_analytics` - llm_analytics\n* `sandbox` - sandbox'
            ),
        is_sandbox: zod.boolean().default(conversationsCreateBodyIsSandboxDefault),
        resume_payload: zod.unknown().nullish(),
    })
    .describe('Serializer for appending a message to an existing conversation without triggering AI processing.')

/**
 * Appends a message to an existing conversation without triggering AI processing.
This is used for client-side generated messages that need to be persisted
(e.g., support ticket confirmation messages).
 */
export const conversationsAppendMessageCreateBodyContentMax = 10000

export const ConversationsAppendMessageCreateBody = /* @__PURE__ */ zod
    .object({
        content: zod.string().max(conversationsAppendMessageCreateBodyContentMax),
    })
    .describe('Serializer for appending a message to an existing conversation without triggering AI processing.')

export const ConversationsCancelPartialUpdateBody = /* @__PURE__ */ zod.object({})

export const ConversationsQueueCreateBody = /* @__PURE__ */ zod.object({})

export const ConversationsQueuePartialUpdateBody = /* @__PURE__ */ zod.object({})

export const ConversationsQueueClearCreateBody = /* @__PURE__ */ zod.object({})

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

export const ConversationsTicketsCreateBody = /* @__PURE__ */ zod
    .object({
        status: zod
            .enum(['new', 'open', 'pending', 'on_hold', 'resolved'])
            .describe(
                '* `new` - New\n* `open` - Open\n* `pending` - Pending\n* `on_hold` - On hold\n* `resolved` - Resolved'
            )
            .optional()
            .describe(
                'Ticket status: new, open, pending, on_hold, or resolved\n\n* `new` - New\n* `open` - Open\n* `pending` - Pending\n* `on_hold` - On hold\n* `resolved` - Resolved'
            ),
        priority: zod
            .union([
                zod.enum(['low', 'medium', 'high']).describe('* `low` - Low\n* `medium` - Medium\n* `high` - High'),
                zod.enum(['']),
                zod.literal(null),
            ])
            .nullish()
            .describe(
                'Ticket priority: low, medium, or high. Null if unset.\n\n* `low` - Low\n* `medium` - Medium\n* `high` - High'
            ),
        anonymous_traits: zod.unknown().optional().describe('Customer-provided traits such as name and email'),
        ai_resolved: zod.boolean().optional(),
        escalation_reason: zod.string().nullish(),
        sla_due_at: zod.iso.datetime({}).nullish().describe('SLA deadline set via workflows. Null means no SLA.'),
        snoozed_until: zod.iso.datetime({}).nullish(),
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
                '* `new` - New\n* `open` - Open\n* `pending` - Pending\n* `on_hold` - On hold\n* `resolved` - Resolved'
            )
            .optional()
            .describe(
                'Ticket status: new, open, pending, on_hold, or resolved\n\n* `new` - New\n* `open` - Open\n* `pending` - Pending\n* `on_hold` - On hold\n* `resolved` - Resolved'
            ),
        priority: zod
            .union([
                zod.enum(['low', 'medium', 'high']).describe('* `low` - Low\n* `medium` - Medium\n* `high` - High'),
                zod.enum(['']),
                zod.literal(null),
            ])
            .nullish()
            .describe(
                'Ticket priority: low, medium, or high. Null if unset.\n\n* `low` - Low\n* `medium` - Medium\n* `high` - High'
            ),
        anonymous_traits: zod.unknown().optional().describe('Customer-provided traits such as name and email'),
        ai_resolved: zod.boolean().optional(),
        escalation_reason: zod.string().nullish(),
        sla_due_at: zod.iso.datetime({}).nullish().describe('SLA deadline set via workflows. Null means no SLA.'),
        snoozed_until: zod.iso.datetime({}).nullish(),
        tags: zod.array(zod.unknown()).optional(),
    })
    .describe('Serializer mixin that handles tags for objects.')

export const ConversationsTicketsPartialUpdateBody = /* @__PURE__ */ zod
    .object({
        status: zod
            .enum(['new', 'open', 'pending', 'on_hold', 'resolved'])
            .describe(
                '* `new` - New\n* `open` - Open\n* `pending` - Pending\n* `on_hold` - On hold\n* `resolved` - Resolved'
            )
            .optional()
            .describe(
                'Ticket status: new, open, pending, on_hold, or resolved\n\n* `new` - New\n* `open` - Open\n* `pending` - Pending\n* `on_hold` - On hold\n* `resolved` - Resolved'
            ),
        priority: zod
            .union([
                zod.enum(['low', 'medium', 'high']).describe('* `low` - Low\n* `medium` - Medium\n* `high` - High'),
                zod.enum(['']),
                zod.literal(null),
            ])
            .nullish()
            .describe(
                'Ticket priority: low, medium, or high. Null if unset.\n\n* `low` - Low\n* `medium` - Medium\n* `high` - High'
            ),
        anonymous_traits: zod.unknown().optional().describe('Customer-provided traits such as name and email'),
        ai_resolved: zod.boolean().optional(),
        escalation_reason: zod.string().nullish(),
        sla_due_at: zod.iso.datetime({}).nullish().describe('SLA deadline set via workflows. Null means no SLA.'),
        snoozed_until: zod.iso.datetime({}).nullish(),
        tags: zod.array(zod.unknown()).optional(),
    })
    .describe('Serializer mixin that handles tags for objects.')

/**
 * Bulk update tags on multiple objects.

Accepts:
- {"ids": [...], "action": "add"|"remove"|"set", "tags": ["tag1", "tag2"]}

Actions:
- "add": Add tags to existing tags on each object
- "remove": Remove specific tags from each object
- "set": Replace all tags on each object with the provided list
 */
export const conversationsTicketsBulkUpdateTagsCreateBodyIdsMax = 500

export const ConversationsTicketsBulkUpdateTagsCreateBody = /* @__PURE__ */ zod.object({
    ids: zod
        .array(zod.number())
        .max(conversationsTicketsBulkUpdateTagsCreateBodyIdsMax)
        .describe('List of object IDs to update tags on.'),
    action: zod
        .enum(['add', 'remove', 'set'])
        .describe('* `add` - add\n* `remove` - remove\n* `set` - set')
        .describe(
            "'add' merges with existing tags, 'remove' deletes specific tags, 'set' replaces all tags.\n\n* `add` - add\n* `remove` - remove\n* `set` - set"
        ),
    tags: zod.array(zod.string()).describe('Tag names to add, remove, or set.'),
})
