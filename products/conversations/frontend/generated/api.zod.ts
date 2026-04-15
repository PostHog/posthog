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

export const conversationsListResponseResultsItemUserOneDistinctIdMax = 200

export const conversationsListResponseResultsItemUserOneFirstNameMax = 150

export const conversationsListResponseResultsItemUserOneLastNameMax = 150

export const conversationsListResponseResultsItemUserOneEmailMax = 254

export const ConversationsListResponse = /* @__PURE__ */ zod.object({
    count: zod.number(),
    next: zod.url().nullish(),
    previous: zod.url().nullish(),
    results: zod.array(
        zod.object({
            id: zod.uuid(),
            status: zod
                .enum(['idle', 'in_progress', 'canceling'])
                .describe('* `idle` - Idle\n* `in_progress` - In progress\n* `canceling` - Canceling'),
            title: zod.string().nullable().describe('Title of the conversation.'),
            user: zod.object({
                id: zod.number(),
                uuid: zod.uuid(),
                distinct_id: zod.string().max(conversationsListResponseResultsItemUserOneDistinctIdMax).nullish(),
                first_name: zod.string().max(conversationsListResponseResultsItemUserOneFirstNameMax).optional(),
                last_name: zod.string().max(conversationsListResponseResultsItemUserOneLastNameMax).optional(),
                email: zod.email().max(conversationsListResponseResultsItemUserOneEmailMax),
                is_email_verified: zod.boolean().nullish(),
                hedgehog_config: zod.record(zod.string(), zod.unknown()).nullable(),
                role_at_organization: zod
                    .union([
                        zod
                            .enum([
                                'engineering',
                                'data',
                                'product',
                                'founder',
                                'leadership',
                                'marketing',
                                'sales',
                                'other',
                            ])
                            .describe(
                                '* `engineering` - Engineering\n* `data` - Data\n* `product` - Product Management\n* `founder` - Founder\n* `leadership` - Leadership\n* `marketing` - Marketing\n* `sales` - Sales / Success\n* `other` - Other'
                            ),
                        zod.enum(['']),
                        zod.literal(null),
                    ])
                    .nullish(),
            }),
            created_at: zod.iso.datetime({}).nullable(),
            updated_at: zod.iso.datetime({}).nullable(),
            type: zod
                .enum(['assistant', 'tool_call', 'deep_research', 'slack'])
                .describe(
                    '* `assistant` - Assistant\n* `tool_call` - Tool call\n* `deep_research` - Deep research\n* `slack` - Slack'
                ),
            is_internal: zod
                .boolean()
                .nullable()
                .describe(
                    'Whether this conversation was created during an impersonated session (e.g., by support agents). Internal conversations are hidden from customers.'
                ),
            slack_thread_key: zod
                .string()
                .nullable()
                .describe("Unique key for Slack thread: '{workspace_id}:{channel}:{thread_ts}'"),
            slack_workspace_domain: zod
                .string()
                .nullable()
                .describe("Slack workspace subdomain (e.g. 'posthog' for posthog.slack.com)"),
        })
    ),
})

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

export const conversationsRetrieveResponseUserOneDistinctIdMax = 200

export const conversationsRetrieveResponseUserOneFirstNameMax = 150

export const conversationsRetrieveResponseUserOneLastNameMax = 150

export const conversationsRetrieveResponseUserOneEmailMax = 254

export const ConversationsRetrieveResponse = /* @__PURE__ */ zod.object({
    id: zod.uuid(),
    status: zod
        .enum(['idle', 'in_progress', 'canceling'])
        .describe('* `idle` - Idle\n* `in_progress` - In progress\n* `canceling` - Canceling'),
    title: zod.string().nullable().describe('Title of the conversation.'),
    user: zod.object({
        id: zod.number(),
        uuid: zod.uuid(),
        distinct_id: zod.string().max(conversationsRetrieveResponseUserOneDistinctIdMax).nullish(),
        first_name: zod.string().max(conversationsRetrieveResponseUserOneFirstNameMax).optional(),
        last_name: zod.string().max(conversationsRetrieveResponseUserOneLastNameMax).optional(),
        email: zod.email().max(conversationsRetrieveResponseUserOneEmailMax),
        is_email_verified: zod.boolean().nullish(),
        hedgehog_config: zod.record(zod.string(), zod.unknown()).nullable(),
        role_at_organization: zod
            .union([
                zod
                    .enum(['engineering', 'data', 'product', 'founder', 'leadership', 'marketing', 'sales', 'other'])
                    .describe(
                        '* `engineering` - Engineering\n* `data` - Data\n* `product` - Product Management\n* `founder` - Founder\n* `leadership` - Leadership\n* `marketing` - Marketing\n* `sales` - Sales / Success\n* `other` - Other'
                    ),
                zod.enum(['']),
                zod.literal(null),
            ])
            .nullish(),
    }),
    created_at: zod.iso.datetime({}).nullable(),
    updated_at: zod.iso.datetime({}).nullable(),
    type: zod
        .enum(['assistant', 'tool_call', 'deep_research', 'slack'])
        .describe(
            '* `assistant` - Assistant\n* `tool_call` - Tool call\n* `deep_research` - Deep research\n* `slack` - Slack'
        ),
    is_internal: zod
        .boolean()
        .nullable()
        .describe(
            'Whether this conversation was created during an impersonated session (e.g., by support agents). Internal conversations are hidden from customers.'
        ),
    slack_thread_key: zod
        .string()
        .nullable()
        .describe("Unique key for Slack thread: '{workspace_id}:{channel}:{thread_ts}'"),
    slack_workspace_domain: zod
        .string()
        .nullable()
        .describe("Slack workspace subdomain (e.g. 'posthog' for posthog.slack.com)"),
    messages: zod.array(zod.record(zod.string(), zod.unknown())),
    has_unsupported_content: zod.boolean(),
    agent_mode: zod.string().nullable(),
    is_sandbox: zod.boolean(),
    pending_approvals: zod
        .array(zod.record(zod.string(), zod.unknown()))
        .describe(
            'Return pending approval cards as structured data.\n\nCombines metadata from conversation.approval_decisions with payload from checkpoint\ninterrupts (single source of truth for payload data).'
        ),
})

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

export const conversationsAppendMessageCreateResponseContentMax = 10000

export const ConversationsAppendMessageCreateResponse = /* @__PURE__ */ zod
    .object({
        content: zod.string().max(conversationsAppendMessageCreateResponseContentMax),
    })
    .describe('Serializer for appending a message to an existing conversation without triggering AI processing.')

export const ConversationsCancelPartialUpdateBody = /* @__PURE__ */ zod.object({})

export const conversationsCancelPartialUpdateResponseUserOneDistinctIdMax = 200

export const conversationsCancelPartialUpdateResponseUserOneFirstNameMax = 150

export const conversationsCancelPartialUpdateResponseUserOneLastNameMax = 150

export const conversationsCancelPartialUpdateResponseUserOneEmailMax = 254

export const ConversationsCancelPartialUpdateResponse = /* @__PURE__ */ zod.object({
    id: zod.uuid(),
    status: zod
        .enum(['idle', 'in_progress', 'canceling'])
        .describe('* `idle` - Idle\n* `in_progress` - In progress\n* `canceling` - Canceling'),
    title: zod.string().nullable().describe('Title of the conversation.'),
    user: zod.object({
        id: zod.number(),
        uuid: zod.uuid(),
        distinct_id: zod.string().max(conversationsCancelPartialUpdateResponseUserOneDistinctIdMax).nullish(),
        first_name: zod.string().max(conversationsCancelPartialUpdateResponseUserOneFirstNameMax).optional(),
        last_name: zod.string().max(conversationsCancelPartialUpdateResponseUserOneLastNameMax).optional(),
        email: zod.email().max(conversationsCancelPartialUpdateResponseUserOneEmailMax),
        is_email_verified: zod.boolean().nullish(),
        hedgehog_config: zod.record(zod.string(), zod.unknown()).nullable(),
        role_at_organization: zod
            .union([
                zod
                    .enum(['engineering', 'data', 'product', 'founder', 'leadership', 'marketing', 'sales', 'other'])
                    .describe(
                        '* `engineering` - Engineering\n* `data` - Data\n* `product` - Product Management\n* `founder` - Founder\n* `leadership` - Leadership\n* `marketing` - Marketing\n* `sales` - Sales / Success\n* `other` - Other'
                    ),
                zod.enum(['']),
                zod.literal(null),
            ])
            .nullish(),
    }),
    created_at: zod.iso.datetime({}).nullable(),
    updated_at: zod.iso.datetime({}).nullable(),
    type: zod
        .enum(['assistant', 'tool_call', 'deep_research', 'slack'])
        .describe(
            '* `assistant` - Assistant\n* `tool_call` - Tool call\n* `deep_research` - Deep research\n* `slack` - Slack'
        ),
    is_internal: zod
        .boolean()
        .nullable()
        .describe(
            'Whether this conversation was created during an impersonated session (e.g., by support agents). Internal conversations are hidden from customers.'
        ),
    slack_thread_key: zod
        .string()
        .nullable()
        .describe("Unique key for Slack thread: '{workspace_id}:{channel}:{thread_ts}'"),
    slack_workspace_domain: zod
        .string()
        .nullable()
        .describe("Slack workspace subdomain (e.g. 'posthog' for posthog.slack.com)"),
    messages: zod.array(zod.record(zod.string(), zod.unknown())),
    has_unsupported_content: zod.boolean(),
    agent_mode: zod.string().nullable(),
    is_sandbox: zod.boolean(),
    pending_approvals: zod
        .array(zod.record(zod.string(), zod.unknown()))
        .describe(
            'Return pending approval cards as structured data.\n\nCombines metadata from conversation.approval_decisions with payload from checkpoint\ninterrupts (single source of truth for payload data).'
        ),
})

export const conversationsQueueRetrieveResponseUserOneDistinctIdMax = 200

export const conversationsQueueRetrieveResponseUserOneFirstNameMax = 150

export const conversationsQueueRetrieveResponseUserOneLastNameMax = 150

export const conversationsQueueRetrieveResponseUserOneEmailMax = 254

export const ConversationsQueueRetrieveResponse = /* @__PURE__ */ zod.object({
    id: zod.uuid(),
    status: zod
        .enum(['idle', 'in_progress', 'canceling'])
        .describe('* `idle` - Idle\n* `in_progress` - In progress\n* `canceling` - Canceling'),
    title: zod.string().nullable().describe('Title of the conversation.'),
    user: zod.object({
        id: zod.number(),
        uuid: zod.uuid(),
        distinct_id: zod.string().max(conversationsQueueRetrieveResponseUserOneDistinctIdMax).nullish(),
        first_name: zod.string().max(conversationsQueueRetrieveResponseUserOneFirstNameMax).optional(),
        last_name: zod.string().max(conversationsQueueRetrieveResponseUserOneLastNameMax).optional(),
        email: zod.email().max(conversationsQueueRetrieveResponseUserOneEmailMax),
        is_email_verified: zod.boolean().nullish(),
        hedgehog_config: zod.record(zod.string(), zod.unknown()).nullable(),
        role_at_organization: zod
            .union([
                zod
                    .enum(['engineering', 'data', 'product', 'founder', 'leadership', 'marketing', 'sales', 'other'])
                    .describe(
                        '* `engineering` - Engineering\n* `data` - Data\n* `product` - Product Management\n* `founder` - Founder\n* `leadership` - Leadership\n* `marketing` - Marketing\n* `sales` - Sales / Success\n* `other` - Other'
                    ),
                zod.enum(['']),
                zod.literal(null),
            ])
            .nullish(),
    }),
    created_at: zod.iso.datetime({}).nullable(),
    updated_at: zod.iso.datetime({}).nullable(),
    type: zod
        .enum(['assistant', 'tool_call', 'deep_research', 'slack'])
        .describe(
            '* `assistant` - Assistant\n* `tool_call` - Tool call\n* `deep_research` - Deep research\n* `slack` - Slack'
        ),
    is_internal: zod
        .boolean()
        .nullable()
        .describe(
            'Whether this conversation was created during an impersonated session (e.g., by support agents). Internal conversations are hidden from customers.'
        ),
    slack_thread_key: zod
        .string()
        .nullable()
        .describe("Unique key for Slack thread: '{workspace_id}:{channel}:{thread_ts}'"),
    slack_workspace_domain: zod
        .string()
        .nullable()
        .describe("Slack workspace subdomain (e.g. 'posthog' for posthog.slack.com)"),
    messages: zod.array(zod.record(zod.string(), zod.unknown())),
    has_unsupported_content: zod.boolean(),
    agent_mode: zod.string().nullable(),
    is_sandbox: zod.boolean(),
    pending_approvals: zod
        .array(zod.record(zod.string(), zod.unknown()))
        .describe(
            'Return pending approval cards as structured data.\n\nCombines metadata from conversation.approval_decisions with payload from checkpoint\ninterrupts (single source of truth for payload data).'
        ),
})

export const ConversationsQueueCreateBody = /* @__PURE__ */ zod.object({})

export const conversationsQueueCreateResponseUserOneDistinctIdMax = 200

export const conversationsQueueCreateResponseUserOneFirstNameMax = 150

export const conversationsQueueCreateResponseUserOneLastNameMax = 150

export const conversationsQueueCreateResponseUserOneEmailMax = 254

export const ConversationsQueueCreateResponse = /* @__PURE__ */ zod.object({
    id: zod.uuid(),
    status: zod
        .enum(['idle', 'in_progress', 'canceling'])
        .describe('* `idle` - Idle\n* `in_progress` - In progress\n* `canceling` - Canceling'),
    title: zod.string().nullable().describe('Title of the conversation.'),
    user: zod.object({
        id: zod.number(),
        uuid: zod.uuid(),
        distinct_id: zod.string().max(conversationsQueueCreateResponseUserOneDistinctIdMax).nullish(),
        first_name: zod.string().max(conversationsQueueCreateResponseUserOneFirstNameMax).optional(),
        last_name: zod.string().max(conversationsQueueCreateResponseUserOneLastNameMax).optional(),
        email: zod.email().max(conversationsQueueCreateResponseUserOneEmailMax),
        is_email_verified: zod.boolean().nullish(),
        hedgehog_config: zod.record(zod.string(), zod.unknown()).nullable(),
        role_at_organization: zod
            .union([
                zod
                    .enum(['engineering', 'data', 'product', 'founder', 'leadership', 'marketing', 'sales', 'other'])
                    .describe(
                        '* `engineering` - Engineering\n* `data` - Data\n* `product` - Product Management\n* `founder` - Founder\n* `leadership` - Leadership\n* `marketing` - Marketing\n* `sales` - Sales / Success\n* `other` - Other'
                    ),
                zod.enum(['']),
                zod.literal(null),
            ])
            .nullish(),
    }),
    created_at: zod.iso.datetime({}).nullable(),
    updated_at: zod.iso.datetime({}).nullable(),
    type: zod
        .enum(['assistant', 'tool_call', 'deep_research', 'slack'])
        .describe(
            '* `assistant` - Assistant\n* `tool_call` - Tool call\n* `deep_research` - Deep research\n* `slack` - Slack'
        ),
    is_internal: zod
        .boolean()
        .nullable()
        .describe(
            'Whether this conversation was created during an impersonated session (e.g., by support agents). Internal conversations are hidden from customers.'
        ),
    slack_thread_key: zod
        .string()
        .nullable()
        .describe("Unique key for Slack thread: '{workspace_id}:{channel}:{thread_ts}'"),
    slack_workspace_domain: zod
        .string()
        .nullable()
        .describe("Slack workspace subdomain (e.g. 'posthog' for posthog.slack.com)"),
    messages: zod.array(zod.record(zod.string(), zod.unknown())),
    has_unsupported_content: zod.boolean(),
    agent_mode: zod.string().nullable(),
    is_sandbox: zod.boolean(),
    pending_approvals: zod
        .array(zod.record(zod.string(), zod.unknown()))
        .describe(
            'Return pending approval cards as structured data.\n\nCombines metadata from conversation.approval_decisions with payload from checkpoint\ninterrupts (single source of truth for payload data).'
        ),
})

export const ConversationsQueuePartialUpdateBody = /* @__PURE__ */ zod.object({})

export const conversationsQueuePartialUpdateResponseUserOneDistinctIdMax = 200

export const conversationsQueuePartialUpdateResponseUserOneFirstNameMax = 150

export const conversationsQueuePartialUpdateResponseUserOneLastNameMax = 150

export const conversationsQueuePartialUpdateResponseUserOneEmailMax = 254

export const ConversationsQueuePartialUpdateResponse = /* @__PURE__ */ zod.object({
    id: zod.uuid(),
    status: zod
        .enum(['idle', 'in_progress', 'canceling'])
        .describe('* `idle` - Idle\n* `in_progress` - In progress\n* `canceling` - Canceling'),
    title: zod.string().nullable().describe('Title of the conversation.'),
    user: zod.object({
        id: zod.number(),
        uuid: zod.uuid(),
        distinct_id: zod.string().max(conversationsQueuePartialUpdateResponseUserOneDistinctIdMax).nullish(),
        first_name: zod.string().max(conversationsQueuePartialUpdateResponseUserOneFirstNameMax).optional(),
        last_name: zod.string().max(conversationsQueuePartialUpdateResponseUserOneLastNameMax).optional(),
        email: zod.email().max(conversationsQueuePartialUpdateResponseUserOneEmailMax),
        is_email_verified: zod.boolean().nullish(),
        hedgehog_config: zod.record(zod.string(), zod.unknown()).nullable(),
        role_at_organization: zod
            .union([
                zod
                    .enum(['engineering', 'data', 'product', 'founder', 'leadership', 'marketing', 'sales', 'other'])
                    .describe(
                        '* `engineering` - Engineering\n* `data` - Data\n* `product` - Product Management\n* `founder` - Founder\n* `leadership` - Leadership\n* `marketing` - Marketing\n* `sales` - Sales / Success\n* `other` - Other'
                    ),
                zod.enum(['']),
                zod.literal(null),
            ])
            .nullish(),
    }),
    created_at: zod.iso.datetime({}).nullable(),
    updated_at: zod.iso.datetime({}).nullable(),
    type: zod
        .enum(['assistant', 'tool_call', 'deep_research', 'slack'])
        .describe(
            '* `assistant` - Assistant\n* `tool_call` - Tool call\n* `deep_research` - Deep research\n* `slack` - Slack'
        ),
    is_internal: zod
        .boolean()
        .nullable()
        .describe(
            'Whether this conversation was created during an impersonated session (e.g., by support agents). Internal conversations are hidden from customers.'
        ),
    slack_thread_key: zod
        .string()
        .nullable()
        .describe("Unique key for Slack thread: '{workspace_id}:{channel}:{thread_ts}'"),
    slack_workspace_domain: zod
        .string()
        .nullable()
        .describe("Slack workspace subdomain (e.g. 'posthog' for posthog.slack.com)"),
    messages: zod.array(zod.record(zod.string(), zod.unknown())),
    has_unsupported_content: zod.boolean(),
    agent_mode: zod.string().nullable(),
    is_sandbox: zod.boolean(),
    pending_approvals: zod
        .array(zod.record(zod.string(), zod.unknown()))
        .describe(
            'Return pending approval cards as structured data.\n\nCombines metadata from conversation.approval_decisions with payload from checkpoint\ninterrupts (single source of truth for payload data).'
        ),
})

export const ConversationsQueueClearCreateBody = /* @__PURE__ */ zod.object({})

export const conversationsQueueClearCreateResponseUserOneDistinctIdMax = 200

export const conversationsQueueClearCreateResponseUserOneFirstNameMax = 150

export const conversationsQueueClearCreateResponseUserOneLastNameMax = 150

export const conversationsQueueClearCreateResponseUserOneEmailMax = 254

export const ConversationsQueueClearCreateResponse = /* @__PURE__ */ zod.object({
    id: zod.uuid(),
    status: zod
        .enum(['idle', 'in_progress', 'canceling'])
        .describe('* `idle` - Idle\n* `in_progress` - In progress\n* `canceling` - Canceling'),
    title: zod.string().nullable().describe('Title of the conversation.'),
    user: zod.object({
        id: zod.number(),
        uuid: zod.uuid(),
        distinct_id: zod.string().max(conversationsQueueClearCreateResponseUserOneDistinctIdMax).nullish(),
        first_name: zod.string().max(conversationsQueueClearCreateResponseUserOneFirstNameMax).optional(),
        last_name: zod.string().max(conversationsQueueClearCreateResponseUserOneLastNameMax).optional(),
        email: zod.email().max(conversationsQueueClearCreateResponseUserOneEmailMax),
        is_email_verified: zod.boolean().nullish(),
        hedgehog_config: zod.record(zod.string(), zod.unknown()).nullable(),
        role_at_organization: zod
            .union([
                zod
                    .enum(['engineering', 'data', 'product', 'founder', 'leadership', 'marketing', 'sales', 'other'])
                    .describe(
                        '* `engineering` - Engineering\n* `data` - Data\n* `product` - Product Management\n* `founder` - Founder\n* `leadership` - Leadership\n* `marketing` - Marketing\n* `sales` - Sales / Success\n* `other` - Other'
                    ),
                zod.enum(['']),
                zod.literal(null),
            ])
            .nullish(),
    }),
    created_at: zod.iso.datetime({}).nullable(),
    updated_at: zod.iso.datetime({}).nullable(),
    type: zod
        .enum(['assistant', 'tool_call', 'deep_research', 'slack'])
        .describe(
            '* `assistant` - Assistant\n* `tool_call` - Tool call\n* `deep_research` - Deep research\n* `slack` - Slack'
        ),
    is_internal: zod
        .boolean()
        .nullable()
        .describe(
            'Whether this conversation was created during an impersonated session (e.g., by support agents). Internal conversations are hidden from customers.'
        ),
    slack_thread_key: zod
        .string()
        .nullable()
        .describe("Unique key for Slack thread: '{workspace_id}:{channel}:{thread_ts}'"),
    slack_workspace_domain: zod
        .string()
        .nullable()
        .describe("Slack workspace subdomain (e.g. 'posthog' for posthog.slack.com)"),
    messages: zod.array(zod.record(zod.string(), zod.unknown())),
    has_unsupported_content: zod.boolean(),
    agent_mode: zod.string().nullable(),
    is_sandbox: zod.boolean(),
    pending_approvals: zod
        .array(zod.record(zod.string(), zod.unknown()))
        .describe(
            'Return pending approval cards as structured data.\n\nCombines metadata from conversation.approval_decisions with payload from checkpoint\ninterrupts (single source of truth for payload data).'
        ),
})

export const conversationsViewsListResponseResultsItemNameMax = 400

export const conversationsViewsListResponseResultsItemCreatedByOneDistinctIdMax = 200

export const conversationsViewsListResponseResultsItemCreatedByOneFirstNameMax = 150

export const conversationsViewsListResponseResultsItemCreatedByOneLastNameMax = 150

export const conversationsViewsListResponseResultsItemCreatedByOneEmailMax = 254

export const ConversationsViewsListResponse = /* @__PURE__ */ zod.object({
    count: zod.number(),
    next: zod.url().nullish(),
    previous: zod.url().nullish(),
    results: zod.array(
        zod.object({
            id: zod.uuid(),
            short_id: zod.string(),
            name: zod.string().max(conversationsViewsListResponseResultsItemNameMax),
            filters: zod
                .record(zod.string(), zod.unknown())
                .optional()
                .describe(
                    'Saved ticket filter criteria. May contain status, priority, channel, sla, assignee, tags, dateFrom, dateTo, and sorting keys.'
                ),
            created_at: zod.iso.datetime({}),
            created_by: zod.object({
                id: zod.number(),
                uuid: zod.uuid(),
                distinct_id: zod
                    .string()
                    .max(conversationsViewsListResponseResultsItemCreatedByOneDistinctIdMax)
                    .nullish(),
                first_name: zod
                    .string()
                    .max(conversationsViewsListResponseResultsItemCreatedByOneFirstNameMax)
                    .optional(),
                last_name: zod
                    .string()
                    .max(conversationsViewsListResponseResultsItemCreatedByOneLastNameMax)
                    .optional(),
                email: zod.email().max(conversationsViewsListResponseResultsItemCreatedByOneEmailMax),
                is_email_verified: zod.boolean().nullish(),
                hedgehog_config: zod.record(zod.string(), zod.unknown()).nullable(),
                role_at_organization: zod
                    .union([
                        zod
                            .enum([
                                'engineering',
                                'data',
                                'product',
                                'founder',
                                'leadership',
                                'marketing',
                                'sales',
                                'other',
                            ])
                            .describe(
                                '* `engineering` - Engineering\n* `data` - Data\n* `product` - Product Management\n* `founder` - Founder\n* `leadership` - Leadership\n* `marketing` - Marketing\n* `sales` - Sales / Success\n* `other` - Other'
                            ),
                        zod.enum(['']),
                        zod.literal(null),
                    ])
                    .nullish(),
            }),
        })
    ),
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

export const conversationsViewsRetrieveResponseNameMax = 400

export const conversationsViewsRetrieveResponseCreatedByOneDistinctIdMax = 200

export const conversationsViewsRetrieveResponseCreatedByOneFirstNameMax = 150

export const conversationsViewsRetrieveResponseCreatedByOneLastNameMax = 150

export const conversationsViewsRetrieveResponseCreatedByOneEmailMax = 254

export const ConversationsViewsRetrieveResponse = /* @__PURE__ */ zod.object({
    id: zod.uuid(),
    short_id: zod.string(),
    name: zod.string().max(conversationsViewsRetrieveResponseNameMax),
    filters: zod
        .record(zod.string(), zod.unknown())
        .optional()
        .describe(
            'Saved ticket filter criteria. May contain status, priority, channel, sla, assignee, tags, dateFrom, dateTo, and sorting keys.'
        ),
    created_at: zod.iso.datetime({}),
    created_by: zod.object({
        id: zod.number(),
        uuid: zod.uuid(),
        distinct_id: zod.string().max(conversationsViewsRetrieveResponseCreatedByOneDistinctIdMax).nullish(),
        first_name: zod.string().max(conversationsViewsRetrieveResponseCreatedByOneFirstNameMax).optional(),
        last_name: zod.string().max(conversationsViewsRetrieveResponseCreatedByOneLastNameMax).optional(),
        email: zod.email().max(conversationsViewsRetrieveResponseCreatedByOneEmailMax),
        is_email_verified: zod.boolean().nullish(),
        hedgehog_config: zod.record(zod.string(), zod.unknown()).nullable(),
        role_at_organization: zod
            .union([
                zod
                    .enum(['engineering', 'data', 'product', 'founder', 'leadership', 'marketing', 'sales', 'other'])
                    .describe(
                        '* `engineering` - Engineering\n* `data` - Data\n* `product` - Product Management\n* `founder` - Founder\n* `leadership` - Leadership\n* `marketing` - Marketing\n* `sales` - Sales / Success\n* `other` - Other'
                    ),
                zod.enum(['']),
                zod.literal(null),
            ])
            .nullish(),
    }),
})

/**
 * List tickets with person data attached.
 */
export const ConversationsTicketsListResponse = /* @__PURE__ */ zod.object({
    count: zod.number(),
    next: zod.url().nullish(),
    previous: zod.url().nullish(),
    results: zod.array(
        zod
            .object({
                id: zod.uuid(),
                ticket_number: zod.number(),
                channel_source: zod
                    .enum(['widget', 'email', 'slack'])
                    .describe('* `widget` - Widget\n* `email` - Email\n* `slack` - Slack'),
                channel_detail: zod
                    .union([
                        zod
                            .enum([
                                'slack_channel_message',
                                'slack_bot_mention',
                                'slack_emoji_reaction',
                                'widget_embedded',
                                'widget_api',
                            ])
                            .describe(
                                '* `slack_channel_message` - Channel message\n* `slack_bot_mention` - Bot mention\n* `slack_emoji_reaction` - Emoji reaction\n* `widget_embedded` - Widget\n* `widget_api` - API'
                            ),
                        zod.literal(null),
                    ])
                    .nullable(),
                distinct_id: zod.string(),
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
                        zod
                            .enum(['low', 'medium', 'high'])
                            .describe('* `low` - Low\n* `medium` - Medium\n* `high` - High'),
                        zod.enum(['']),
                        zod.literal(null),
                    ])
                    .nullish()
                    .describe(
                        'Ticket priority: low, medium, or high. Null if unset.\n\n* `low` - Low\n* `medium` - Medium\n* `high` - High'
                    ),
                assignee: zod
                    .object({
                        id: zod.string().nullable(),
                        type: zod.string(),
                        user: zod.record(zod.string(), zod.string()).nullable(),
                        role: zod.record(zod.string(), zod.string()).nullable(),
                    })
                    .describe('Serializer for ticket assignment (user or role).'),
                anonymous_traits: zod.unknown().optional().describe('Customer-provided traits such as name and email'),
                ai_resolved: zod.boolean().optional(),
                escalation_reason: zod.string().nullish(),
                created_at: zod.iso.datetime({}),
                updated_at: zod.iso.datetime({}),
                message_count: zod.number(),
                last_message_at: zod.iso.datetime({}).nullable(),
                last_message_text: zod.string().nullable(),
                unread_team_count: zod.number(),
                unread_customer_count: zod.number(),
                session_id: zod.string().nullable(),
                session_context: zod.unknown(),
                sla_due_at: zod.iso
                    .datetime({})
                    .nullish()
                    .describe('SLA deadline set via workflows. Null means no SLA.'),
                slack_channel_id: zod.string().nullable(),
                slack_thread_ts: zod.string().nullable(),
                slack_team_id: zod.string().nullable(),
                email_subject: zod.string().nullable(),
                email_from: zod.email().nullable(),
                email_to: zod.string().nullable(),
                cc_participants: zod.unknown(),
                person: zod
                    .object({
                        id: zod.uuid(),
                        name: zod.string(),
                        distinct_ids: zod.array(zod.string()),
                        properties: zod.record(zod.string(), zod.unknown()),
                        created_at: zod.iso.datetime({}),
                        is_identified: zod.boolean(),
                    })
                    .describe('Minimal person serializer for embedding in ticket responses.')
                    .nullable(),
                tags: zod.array(zod.unknown()).optional(),
            })
            .describe('Serializer mixin that handles tags for objects.')
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
        tags: zod.array(zod.unknown()).optional(),
    })
    .describe('Serializer mixin that handles tags for objects.')

/**
 * Get single ticket and mark as read by team.
 */
export const ConversationsTicketsRetrieveResponse = /* @__PURE__ */ zod
    .object({
        id: zod.uuid(),
        ticket_number: zod.number(),
        channel_source: zod
            .enum(['widget', 'email', 'slack'])
            .describe('* `widget` - Widget\n* `email` - Email\n* `slack` - Slack'),
        channel_detail: zod
            .union([
                zod
                    .enum([
                        'slack_channel_message',
                        'slack_bot_mention',
                        'slack_emoji_reaction',
                        'widget_embedded',
                        'widget_api',
                    ])
                    .describe(
                        '* `slack_channel_message` - Channel message\n* `slack_bot_mention` - Bot mention\n* `slack_emoji_reaction` - Emoji reaction\n* `widget_embedded` - Widget\n* `widget_api` - API'
                    ),
                zod.literal(null),
            ])
            .nullable(),
        distinct_id: zod.string(),
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
        assignee: zod
            .object({
                id: zod.string().nullable(),
                type: zod.string(),
                user: zod.record(zod.string(), zod.string()).nullable(),
                role: zod.record(zod.string(), zod.string()).nullable(),
            })
            .describe('Serializer for ticket assignment (user or role).'),
        anonymous_traits: zod.unknown().optional().describe('Customer-provided traits such as name and email'),
        ai_resolved: zod.boolean().optional(),
        escalation_reason: zod.string().nullish(),
        created_at: zod.iso.datetime({}),
        updated_at: zod.iso.datetime({}),
        message_count: zod.number(),
        last_message_at: zod.iso.datetime({}).nullable(),
        last_message_text: zod.string().nullable(),
        unread_team_count: zod.number(),
        unread_customer_count: zod.number(),
        session_id: zod.string().nullable(),
        session_context: zod.unknown(),
        sla_due_at: zod.iso.datetime({}).nullish().describe('SLA deadline set via workflows. Null means no SLA.'),
        slack_channel_id: zod.string().nullable(),
        slack_thread_ts: zod.string().nullable(),
        slack_team_id: zod.string().nullable(),
        email_subject: zod.string().nullable(),
        email_from: zod.email().nullable(),
        email_to: zod.string().nullable(),
        cc_participants: zod.unknown(),
        person: zod
            .object({
                id: zod.uuid(),
                name: zod.string(),
                distinct_ids: zod.array(zod.string()),
                properties: zod.record(zod.string(), zod.unknown()),
                created_at: zod.iso.datetime({}),
                is_identified: zod.boolean(),
            })
            .describe('Minimal person serializer for embedding in ticket responses.')
            .nullable(),
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
        tags: zod.array(zod.unknown()).optional(),
    })
    .describe('Serializer mixin that handles tags for objects.')

export const ConversationsTicketsUpdateResponse = /* @__PURE__ */ zod
    .object({
        id: zod.uuid(),
        ticket_number: zod.number(),
        channel_source: zod
            .enum(['widget', 'email', 'slack'])
            .describe('* `widget` - Widget\n* `email` - Email\n* `slack` - Slack'),
        channel_detail: zod
            .union([
                zod
                    .enum([
                        'slack_channel_message',
                        'slack_bot_mention',
                        'slack_emoji_reaction',
                        'widget_embedded',
                        'widget_api',
                    ])
                    .describe(
                        '* `slack_channel_message` - Channel message\n* `slack_bot_mention` - Bot mention\n* `slack_emoji_reaction` - Emoji reaction\n* `widget_embedded` - Widget\n* `widget_api` - API'
                    ),
                zod.literal(null),
            ])
            .nullable(),
        distinct_id: zod.string(),
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
        assignee: zod
            .object({
                id: zod.string().nullable(),
                type: zod.string(),
                user: zod.record(zod.string(), zod.string()).nullable(),
                role: zod.record(zod.string(), zod.string()).nullable(),
            })
            .describe('Serializer for ticket assignment (user or role).'),
        anonymous_traits: zod.unknown().optional().describe('Customer-provided traits such as name and email'),
        ai_resolved: zod.boolean().optional(),
        escalation_reason: zod.string().nullish(),
        created_at: zod.iso.datetime({}),
        updated_at: zod.iso.datetime({}),
        message_count: zod.number(),
        last_message_at: zod.iso.datetime({}).nullable(),
        last_message_text: zod.string().nullable(),
        unread_team_count: zod.number(),
        unread_customer_count: zod.number(),
        session_id: zod.string().nullable(),
        session_context: zod.unknown(),
        sla_due_at: zod.iso.datetime({}).nullish().describe('SLA deadline set via workflows. Null means no SLA.'),
        slack_channel_id: zod.string().nullable(),
        slack_thread_ts: zod.string().nullable(),
        slack_team_id: zod.string().nullable(),
        email_subject: zod.string().nullable(),
        email_from: zod.email().nullable(),
        email_to: zod.string().nullable(),
        cc_participants: zod.unknown(),
        person: zod
            .object({
                id: zod.uuid(),
                name: zod.string(),
                distinct_ids: zod.array(zod.string()),
                properties: zod.record(zod.string(), zod.unknown()),
                created_at: zod.iso.datetime({}),
                is_identified: zod.boolean(),
            })
            .describe('Minimal person serializer for embedding in ticket responses.')
            .nullable(),
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
        tags: zod.array(zod.unknown()).optional(),
    })
    .describe('Serializer mixin that handles tags for objects.')

export const ConversationsTicketsPartialUpdateResponse = /* @__PURE__ */ zod
    .object({
        id: zod.uuid(),
        ticket_number: zod.number(),
        channel_source: zod
            .enum(['widget', 'email', 'slack'])
            .describe('* `widget` - Widget\n* `email` - Email\n* `slack` - Slack'),
        channel_detail: zod
            .union([
                zod
                    .enum([
                        'slack_channel_message',
                        'slack_bot_mention',
                        'slack_emoji_reaction',
                        'widget_embedded',
                        'widget_api',
                    ])
                    .describe(
                        '* `slack_channel_message` - Channel message\n* `slack_bot_mention` - Bot mention\n* `slack_emoji_reaction` - Emoji reaction\n* `widget_embedded` - Widget\n* `widget_api` - API'
                    ),
                zod.literal(null),
            ])
            .nullable(),
        distinct_id: zod.string(),
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
        assignee: zod
            .object({
                id: zod.string().nullable(),
                type: zod.string(),
                user: zod.record(zod.string(), zod.string()).nullable(),
                role: zod.record(zod.string(), zod.string()).nullable(),
            })
            .describe('Serializer for ticket assignment (user or role).'),
        anonymous_traits: zod.unknown().optional().describe('Customer-provided traits such as name and email'),
        ai_resolved: zod.boolean().optional(),
        escalation_reason: zod.string().nullish(),
        created_at: zod.iso.datetime({}),
        updated_at: zod.iso.datetime({}),
        message_count: zod.number(),
        last_message_at: zod.iso.datetime({}).nullable(),
        last_message_text: zod.string().nullable(),
        unread_team_count: zod.number(),
        unread_customer_count: zod.number(),
        session_id: zod.string().nullable(),
        session_context: zod.unknown(),
        sla_due_at: zod.iso.datetime({}).nullish().describe('SLA deadline set via workflows. Null means no SLA.'),
        slack_channel_id: zod.string().nullable(),
        slack_thread_ts: zod.string().nullable(),
        slack_team_id: zod.string().nullable(),
        email_subject: zod.string().nullable(),
        email_from: zod.email().nullable(),
        email_to: zod.string().nullable(),
        cc_participants: zod.unknown(),
        person: zod
            .object({
                id: zod.uuid(),
                name: zod.string(),
                distinct_ids: zod.array(zod.string()),
                properties: zod.record(zod.string(), zod.unknown()),
                created_at: zod.iso.datetime({}),
                is_identified: zod.boolean(),
            })
            .describe('Minimal person serializer for embedding in ticket responses.')
            .nullable(),
        tags: zod.array(zod.unknown()).optional(),
    })
    .describe('Serializer mixin that handles tags for objects.')

export const ConversationsTicketsSuggestReplyCreateResponse = /* @__PURE__ */ zod.object({
    suggestion: zod.string(),
})

/**
 * Get total unread ticket count for the team.

Returns the sum of unread_team_count for all non-resolved tickets.
Cached in Redis for 30 seconds, invalidated on changes.
 */
export const ConversationsTicketsUnreadCountRetrieveResponse = /* @__PURE__ */ zod
    .object({
        id: zod.uuid(),
        ticket_number: zod.number(),
        channel_source: zod
            .enum(['widget', 'email', 'slack'])
            .describe('* `widget` - Widget\n* `email` - Email\n* `slack` - Slack'),
        channel_detail: zod
            .union([
                zod
                    .enum([
                        'slack_channel_message',
                        'slack_bot_mention',
                        'slack_emoji_reaction',
                        'widget_embedded',
                        'widget_api',
                    ])
                    .describe(
                        '* `slack_channel_message` - Channel message\n* `slack_bot_mention` - Bot mention\n* `slack_emoji_reaction` - Emoji reaction\n* `widget_embedded` - Widget\n* `widget_api` - API'
                    ),
                zod.literal(null),
            ])
            .nullable(),
        distinct_id: zod.string(),
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
        assignee: zod
            .object({
                id: zod.string().nullable(),
                type: zod.string(),
                user: zod.record(zod.string(), zod.string()).nullable(),
                role: zod.record(zod.string(), zod.string()).nullable(),
            })
            .describe('Serializer for ticket assignment (user or role).'),
        anonymous_traits: zod.unknown().optional().describe('Customer-provided traits such as name and email'),
        ai_resolved: zod.boolean().optional(),
        escalation_reason: zod.string().nullish(),
        created_at: zod.iso.datetime({}),
        updated_at: zod.iso.datetime({}),
        message_count: zod.number(),
        last_message_at: zod.iso.datetime({}).nullable(),
        last_message_text: zod.string().nullable(),
        unread_team_count: zod.number(),
        unread_customer_count: zod.number(),
        session_id: zod.string().nullable(),
        session_context: zod.unknown(),
        sla_due_at: zod.iso.datetime({}).nullish().describe('SLA deadline set via workflows. Null means no SLA.'),
        slack_channel_id: zod.string().nullable(),
        slack_thread_ts: zod.string().nullable(),
        slack_team_id: zod.string().nullable(),
        email_subject: zod.string().nullable(),
        email_from: zod.email().nullable(),
        email_to: zod.string().nullable(),
        cc_participants: zod.unknown(),
        person: zod
            .object({
                id: zod.uuid(),
                name: zod.string(),
                distinct_ids: zod.array(zod.string()),
                properties: zod.record(zod.string(), zod.unknown()),
                created_at: zod.iso.datetime({}),
                is_identified: zod.boolean(),
            })
            .describe('Minimal person serializer for embedding in ticket responses.')
            .nullable(),
        tags: zod.array(zod.unknown()).optional(),
    })
    .describe('Serializer mixin that handles tags for objects.')
