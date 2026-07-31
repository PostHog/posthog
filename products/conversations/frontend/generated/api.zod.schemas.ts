/**
 * Auto-generated Zod validation schemas from the Django backend OpenAPI schema.
 * To modify these schemas, update the Django serializers or views, then run:
 *   hogli build:openapi
 * Questions or issues? #team-devex on Slack
 *
 * PostHog API - generated
 * OpenAPI spec version: 1.0.0
 */
import { z as zod } from 'zod'

export const ConversationStatusApi = zod
    .enum(['idle', 'in_progress', 'canceling'])
    .describe('\* `idle` - Idle\n\* `in_progress` - In progress\n\* `canceling` - Canceling')

export type ConversationStatusApi = zod.input<typeof ConversationStatusApi>
export type ConversationStatusApiOutput = zod.output<typeof ConversationStatusApi>

export const TopicEnumApi = zod
    .enum([
        'web_analytics',
        'product_analytics',
        'session_replay',
        'surveys',
        'feature_flags',
        'experiments',
        'error_tracking',
        'data_warehouse',
        'other',
    ])
    .describe(
        '\* `web_analytics` - Web analytics\n\* `product_analytics` - Product analytics\n\* `session_replay` - Session replay\n\* `surveys` - Surveys\n\* `feature_flags` - Feature flags\n\* `experiments` - Experiments\n\* `error_tracking` - Error tracking\n\* `data_warehouse` - Data warehouse\n\* `other` - Other'
    )

export type TopicEnumApi = zod.input<typeof TopicEnumApi>
export type TopicEnumApiOutput = zod.output<typeof TopicEnumApi>

export const RoleAtOrganizationEnumApi = zod
    .enum(['engineering', 'data', 'product', 'founder', 'leadership', 'marketing', 'sales', 'other'])
    .describe(
        '\* `engineering` - Engineering\n\* `data` - Data\n\* `product` - Product Management\n\* `founder` - Founder\n\* `leadership` - Leadership\n\* `marketing` - Marketing\n\* `sales` - Sales \/ Success\n\* `other` - Other'
    )

export type RoleAtOrganizationEnumApi = zod.input<typeof RoleAtOrganizationEnumApi>
export type RoleAtOrganizationEnumApiOutput = zod.output<typeof RoleAtOrganizationEnumApi>

export const BlankEnumApi = zod.enum([''])

export type BlankEnumApi = zod.input<typeof BlankEnumApi>
export type BlankEnumApiOutput = zod.output<typeof BlankEnumApi>

export const userBasicApiDistinctIdMax = 200

export const userBasicApiFirstNameMax = 150

export const userBasicApiLastNameMax = 150

export const userBasicApiEmailMax = 254

export const UserBasicApi = zod.object({
    id: zod.number(),
    uuid: zod.uuid(),
    distinct_id: zod.string().max(userBasicApiDistinctIdMax).nullish(),
    first_name: zod.string().max(userBasicApiFirstNameMax).optional(),
    last_name: zod.string().max(userBasicApiLastNameMax).optional(),
    email: zod.email().max(userBasicApiEmailMax),
    is_email_verified: zod.boolean().nullish(),
    hedgehog_config: zod.record(zod.string(), zod.unknown()).nullable(),
    role_at_organization: zod.union([RoleAtOrganizationEnumApi, BlankEnumApi, zod.null()]).optional(),
})

export type UserBasicApi = zod.input<typeof UserBasicApi>
export type UserBasicApiOutput = zod.output<typeof UserBasicApi>

export const ConversationTypeApi = zod
    .enum(['assistant', 'tool_call', 'deep_research', 'slack'])
    .describe(
        '\* `assistant` - Assistant\n\* `tool_call` - Tool call\n\* `deep_research` - Deep research\n\* `slack` - Slack'
    )

export type ConversationTypeApi = zod.input<typeof ConversationTypeApi>
export type ConversationTypeApiOutput = zod.output<typeof ConversationTypeApi>

export const RuntimeEnumApi = zod.enum(['acp', 'pi']).describe('\* `acp` - ACP\n\* `pi` - Pi')

export type RuntimeEnumApi = zod.input<typeof RuntimeEnumApi>
export type RuntimeEnumApiOutput = zod.output<typeof RuntimeEnumApi>

export const TaskUserBasicInfoApi = zod
    .object({
        id: zod.number(),
        uuid: zod.uuid(),
        distinct_id: zod.string(),
        first_name: zod.string(),
        last_name: zod.string(),
        email: zod.string(),
        is_email_verified: zod.boolean().nullish(),
        hedgehog_config: zod.record(zod.string(), zod.unknown()).nullish(),
        role_at_organization: zod.string().nullish(),
    })
    .describe('Response shape for a task creator, mirroring core ``UserBasicSerializer`` output.')

export type TaskUserBasicInfoApi = zod.input<typeof TaskUserBasicInfoApi>
export type TaskUserBasicInfoApiOutput = zod.output<typeof TaskUserBasicInfoApi>

export const ConversationTaskApi = zod
    .object({
        id: zod.uuid(),
        task_number: zod.number().nullable(),
        slug: zod.string(),
        title: zod.string(),
        title_manually_set: zod.boolean(),
        description: zod.string(),
        origin_product: zod.string(),
        runtime: RuntimeEnumApi.describe(
            "Agent protocol and harness used for this task's runs.\n\n\* `acp` - ACP\n\* `pi` - Pi"
        ),
        repository: zod.string().nullable(),
        github_integration: zod.number().nullable(),
        github_user_integration: zod.uuid().nullable(),
        signal_report: zod.uuid().nullable(),
        json_schema: zod.record(zod.string(), zod.unknown()).nullable(),
        internal: zod.boolean(),
        archived: zod.boolean(),
        archived_at: zod.iso.datetime({ offset: true }).nullable(),
        latest_run: zod.uuid().nullable().describe('Id of the latest TaskRun; null when the task has no runs.'),
        created_at: zod.iso.datetime({ offset: true }).nullish(),
        updated_at: zod.iso.datetime({ offset: true }).nullish(),
        created_by: zod.union([TaskUserBasicInfoApi, zod.null()]).optional(),
        ci_prompt: zod.string().nullable(),
    })
    .describe(
        "Conversation envelope variant: ``latest_run`` is just the latest run's id, not the nested\nrun detail. The frontend only needs the id to reconnect to sandbox logs, and emitting the id\navoids presigning a log URL per conversation.\n\nRead access here follows the conversation (the share-by-link unit), not per-creator task\nvisibility — write\/send stays creator-gated. See ``tasks_facade.get_conversation_task_dtos``."
    )

export type ConversationTaskApi = zod.input<typeof ConversationTaskApi>
export type ConversationTaskApiOutput = zod.output<typeof ConversationTaskApi>

export const ConversationMinimalApi = zod.object({
    id: zod.uuid(),
    status: ConversationStatusApi,
    title: zod.string().nullable().describe('Title of the conversation.'),
    topic: zod
        .union([TopicEnumApi, zod.null()])
        .describe(
            'Product domain the conversation is about, classified from the first question.\n\n\* `web_analytics` - Web analytics\n\* `product_analytics` - Product analytics\n\* `session_replay` - Session replay\n\* `surveys` - Surveys\n\* `feature_flags` - Feature flags\n\* `experiments` - Experiments\n\* `error_tracking` - Error tracking\n\* `data_warehouse` - Data warehouse\n\* `other` - Other'
        ),
    user: UserBasicApi,
    created_at: zod.iso.datetime({ offset: true }).nullable(),
    updated_at: zod.iso.datetime({ offset: true }).nullable(),
    type: ConversationTypeApi,
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
    task: zod.union([ConversationTaskApi, zod.null()]),
})

export type ConversationMinimalApi = zod.input<typeof ConversationMinimalApi>
export type ConversationMinimalApiOutput = zod.output<typeof ConversationMinimalApi>

export const PaginatedConversationMinimalListApi = zod.object({
    count: zod.number(),
    next: zod.url().nullish(),
    previous: zod.url().nullish(),
    results: zod.array(ConversationMinimalApi),
})

export type PaginatedConversationMinimalListApi = zod.input<typeof PaginatedConversationMinimalListApi>
export type PaginatedConversationMinimalListApiOutput = zod.output<typeof PaginatedConversationMinimalListApi>

export const AgentModeEnumApi = zod
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
    .describe(
        '\* `product_analytics` - product_analytics\n\* `sql` - sql\n\* `session_replay` - session_replay\n\* `error_tracking` - error_tracking\n\* `plan` - plan\n\* `execution` - execution\n\* `survey` - survey\n\* `research` - research\n\* `flags` - flags\n\* `llm_analytics` - llm_analytics\n\* `sandbox` - sandbox\n\* `user_interview` - user_interview\n\* `customer_analytics` - customer_analytics'
    )

export type AgentModeEnumApi = zod.input<typeof AgentModeEnumApi>
export type AgentModeEnumApiOutput = zod.output<typeof AgentModeEnumApi>

export const messageApiContentMax = 40000

export const messageApiIsSandboxDefault = false

export const MessageApi = zod
    .object({
        content: zod.string().max(messageApiContentMax).nullable(),
        conversation: zod.uuid(),
        contextual_tools: zod.record(zod.string(), zod.unknown()).optional(),
        ui_context: zod.unknown().optional(),
        billing_context: zod.unknown().optional(),
        trace_id: zod.uuid(),
        session_id: zod.string().optional(),
        agent_mode: AgentModeEnumApi.optional(),
        is_sandbox: zod.boolean().default(messageApiIsSandboxDefault),
        resume_payload: zod.unknown().optional(),
    })
    .describe('Serializer for appending a message to an existing conversation without triggering AI processing.')

export type MessageApi = zod.input<typeof MessageApi>
export type MessageApiOutput = zod.output<typeof MessageApi>

export const AgentRuntimeEnumApi = zod
    .enum(['langgraph', 'sandbox'])
    .describe('\* `langgraph` - LangGraph\n\* `sandbox` - Sandbox')

export type AgentRuntimeEnumApi = zod.input<typeof AgentRuntimeEnumApi>
export type AgentRuntimeEnumApiOutput = zod.output<typeof AgentRuntimeEnumApi>

export const ConversationApi = zod.object({
    id: zod.uuid(),
    status: ConversationStatusApi,
    title: zod.string().nullable().describe('Title of the conversation.'),
    topic: zod
        .union([TopicEnumApi, zod.null()])
        .describe(
            'Product domain the conversation is about, classified from the first question.\n\n\* `web_analytics` - Web analytics\n\* `product_analytics` - Product analytics\n\* `session_replay` - Session replay\n\* `surveys` - Surveys\n\* `feature_flags` - Feature flags\n\* `experiments` - Experiments\n\* `error_tracking` - Error tracking\n\* `data_warehouse` - Data warehouse\n\* `other` - Other'
        ),
    user: UserBasicApi,
    created_at: zod.iso.datetime({ offset: true }).nullable(),
    updated_at: zod.iso.datetime({ offset: true }).nullable(),
    type: ConversationTypeApi,
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
    agent_runtime: AgentRuntimeEnumApi.describe(
        "Runtime that owns this conversation. 'langgraph' conversations return their messages in the `messages` field; born-'sandbox' conversations return an empty `messages` array and load history from the products\/tasks logs endpoint. A converted conversation is 'sandbox' but still returns its legacy thread in `messages`.\n\n\* `langgraph` - LangGraph\n\* `sandbox` - Sandbox"
    ),
    is_sandbox: zod.boolean(),
    pending_approvals: zod
        .array(zod.record(zod.string(), zod.unknown()))
        .describe(
            'Return pending approval cards as structured data.\n\nCombines metadata from conversation.approval_decisions with payload from checkpoint\ninterrupts (single source of truth for payload data).'
        ),
    task: zod.union([ConversationTaskApi, zod.null()]),
})

export type ConversationApi = zod.input<typeof ConversationApi>
export type ConversationApiOutput = zod.output<typeof ConversationApi>

export const messageMinimalApiContentMax = 10000

export const MessageMinimalApi = zod
    .object({
        content: zod.string().max(messageMinimalApiContentMax),
    })
    .describe('Serializer for appending a message to an existing conversation without triggering AI processing.')

export type MessageMinimalApi = zod.input<typeof MessageMinimalApi>
export type MessageMinimalApiOutput = zod.output<typeof MessageMinimalApi>

export const PatchedConversationApi = zod.object({
    id: zod.uuid().optional(),
    status: ConversationStatusApi.optional(),
    title: zod.string().nullish().describe('Title of the conversation.'),
    topic: zod
        .union([TopicEnumApi, zod.null()])
        .optional()
        .describe(
            'Product domain the conversation is about, classified from the first question.\n\n\* `web_analytics` - Web analytics\n\* `product_analytics` - Product analytics\n\* `session_replay` - Session replay\n\* `surveys` - Surveys\n\* `feature_flags` - Feature flags\n\* `experiments` - Experiments\n\* `error_tracking` - Error tracking\n\* `data_warehouse` - Data warehouse\n\* `other` - Other'
        ),
    user: UserBasicApi.optional(),
    created_at: zod.iso.datetime({ offset: true }).nullish(),
    updated_at: zod.iso.datetime({ offset: true }).nullish(),
    type: ConversationTypeApi.optional(),
    is_internal: zod
        .boolean()
        .nullish()
        .describe(
            'Whether this conversation was created during an impersonated session (e.g., by support agents). Internal conversations are hidden from customers.'
        ),
    slack_thread_key: zod
        .string()
        .nullish()
        .describe("Unique key for Slack thread: '{workspace_id}:{channel}:{thread_ts}'"),
    slack_workspace_domain: zod
        .string()
        .nullish()
        .describe("Slack workspace subdomain (e.g. 'posthog' for posthog.slack.com)"),
    messages: zod.array(zod.record(zod.string(), zod.unknown())).optional(),
    has_unsupported_content: zod.boolean().optional(),
    agent_mode: zod.string().nullish(),
    agent_runtime: AgentRuntimeEnumApi.optional().describe(
        "Runtime that owns this conversation. 'langgraph' conversations return their messages in the `messages` field; born-'sandbox' conversations return an empty `messages` array and load history from the products\/tasks logs endpoint. A converted conversation is 'sandbox' but still returns its legacy thread in `messages`.\n\n\* `langgraph` - LangGraph\n\* `sandbox` - Sandbox"
    ),
    is_sandbox: zod.boolean().optional(),
    pending_approvals: zod
        .array(zod.record(zod.string(), zod.unknown()))
        .optional()
        .describe(
            'Return pending approval cards as structured data.\n\nCombines metadata from conversation.approval_decisions with payload from checkpoint\ninterrupts (single source of truth for payload data).'
        ),
    task: zod.union([ConversationTaskApi, zod.null()]).optional(),
})

export type PatchedConversationApi = zod.input<typeof PatchedConversationApi>
export type PatchedConversationApiOutput = zod.output<typeof PatchedConversationApi>

export const SandboxAttachedContextItemTypeEnumApi = zod
    .enum(['action', 'dashboard', 'error_tracking_issue', 'evaluation', 'event', 'insight', 'notebook', 'text'])
    .describe(
        '\* `action` - action\n\* `dashboard` - dashboard\n\* `error_tracking_issue` - error_tracking_issue\n\* `evaluation` - evaluation\n\* `event` - event\n\* `insight` - insight\n\* `notebook` - notebook\n\* `text` - text'
    )

export type SandboxAttachedContextItemTypeEnumApi = zod.input<typeof SandboxAttachedContextItemTypeEnumApi>
export type SandboxAttachedContextItemTypeEnumApiOutput = zod.output<typeof SandboxAttachedContextItemTypeEnumApi>

export const SandboxAttachedContextItemApi = zod
    .object({
        type: SandboxAttachedContextItemTypeEnumApi.describe(
            'Attachment kind. Entity types carry `id` (+ optional `name`); `text` carries `value`.\n\n\* `action` - action\n\* `dashboard` - dashboard\n\* `error_tracking_issue` - error_tracking_issue\n\* `evaluation` - evaluation\n\* `event` - event\n\* `insight` - insight\n\* `notebook` - notebook\n\* `text` - text'
        ),
        id: zod
            .unknown()
            .optional()
            .describe(
                'Entity identifier — integer for `dashboard`\/`action`, string short_id\/UUID otherwise. Absent for `text`.'
            ),
        name: zod.string().optional().describe('Optional human-readable label rendered in the context block.'),
        value: zod.string().optional().describe('Free-text content. Only for `text` attachments.'),
    })
    .describe(
        'One typed attachment carried by a sandbox message.\n\nDEPRECATED PATH — do not extend. This structured `attached_context` (and its server-side wrap in\n`context_wrapper.py`) exists only for the legacy Max conversations bridge and is removed with it;\nthe live path wraps context client-side (`products\/posthog_ai\/frontend\/utils\/posthogContextBlock.ts`).'
    )

export type SandboxAttachedContextItemApi = zod.input<typeof SandboxAttachedContextItemApi>
export type SandboxAttachedContextItemApiOutput = zod.output<typeof SandboxAttachedContextItemApi>

export const InitialPermissionModeEnumApi = zod
    .enum(['default', 'acceptEdits', 'plan', 'bypassPermissions', 'auto'])
    .describe(
        '\* `default` - default\n\* `acceptEdits` - acceptEdits\n\* `plan` - plan\n\* `bypassPermissions` - bypassPermissions\n\* `auto` - auto'
    )

export type InitialPermissionModeEnumApi = zod.input<typeof InitialPermissionModeEnumApi>
export type InitialPermissionModeEnumApiOutput = zod.output<typeof InitialPermissionModeEnumApi>

export const sandboxOpenApiContentMax = 40000

export const SandboxOpenApi = zod
    .object({
        content: zod
            .string()
            .max(sandboxOpenApiContentMax)
            .nullish()
            .describe(
                "The user's message text. Omit or null to warm a sandbox (boot + idle) ahead of the first message."
            ),
        trace_id: zod
            .uuid()
            .optional()
            .describe("Client-generated trace id correlated with the resulting Run's SSE stream."),
        attached_context: zod
            .array(SandboxAttachedContextItemApi)
            .optional()
            .describe('Typed PostHog entities (and free text) attached to this message.'),
        initial_permission_mode: InitialPermissionModeEnumApi.optional().describe(
            'Initial permission mode for the sandbox agent session. Defaults to `auto`, which allows safe tool use while preserving explicit confirmations.\n\n\* `default` - default\n\* `acceptEdits` - acceptEdits\n\* `plan` - plan\n\* `bypassPermissions` - bypassPermissions\n\* `auto` - auto'
        ),
        task_id: zod
            .uuid()
            .optional()
            .describe(
                "Bind a brand-new sandbox conversation to an existing Task so the first message resumes that Task's run. Honored only when this request creates the conversation row; ignored for an already-existing conversation."
            ),
    })
    .describe(
        'Request body for `POST \/conversations\/{id}\/open\/`. A string `content` processes a turn; a\nnull\/absent `content` warms a sandbox that idles awaiting the first message.'
    )

export type SandboxOpenApi = zod.input<typeof SandboxOpenApi>
export type SandboxOpenApiOutput = zod.output<typeof SandboxOpenApi>

export const SandboxMessageResponseApi = zod
    .object({
        task_id: zod.string().describe('The products\/tasks Task backing the conversation.'),
        run_id: zod.string().describe('The Run the frontend opens SSE against.'),
        trace_id: zod.string().nullable().describe('Echo of the request trace id, if provided.'),
        run_status: zod.string().describe('Current status of the targeted Run (e.g. `queued`, `in_progress`).'),
        just_created_run: zod
            .boolean()
            .describe(
                'True when a new Run was created (first message, terminal resume, or fresh warm); false for an in-progress follow-up or a reused warm Run.'
            ),
    })
    .describe('Response for `POST \/conversations\/{id}\/open\/` — the IDs the frontend opens SSE against.')

export type SandboxMessageResponseApi = zod.input<typeof SandboxMessageResponseApi>
export type SandboxMessageResponseApiOutput = zod.output<typeof SandboxMessageResponseApi>

export const ChannelSourceEnumApi = zod
    .enum(['widget', 'email', 'slack', 'teams', 'github'])
    .describe(
        '\* `widget` - Widget\n\* `email` - Email\n\* `slack` - Slack\n\* `teams` - Microsoft Teams\n\* `github` - GitHub'
    )

export type ChannelSourceEnumApi = zod.input<typeof ChannelSourceEnumApi>
export type ChannelSourceEnumApiOutput = zod.output<typeof ChannelSourceEnumApi>

export const ChannelDetailEnumApi = zod
    .enum([
        'slack_channel_message',
        'slack_bot_mention',
        'slack_emoji_reaction',
        'teams_channel_message',
        'teams_bot_mention',
        'widget_embedded',
        'widget_api',
        'github_issue',
    ])
    .describe(
        '\* `slack_channel_message` - Channel message\n\* `slack_bot_mention` - Bot mention\n\* `slack_emoji_reaction` - Emoji reaction\n\* `teams_channel_message` - Teams channel message\n\* `teams_bot_mention` - Teams bot mention\n\* `widget_embedded` - Widget\n\* `widget_api` - API\n\* `github_issue` - GitHub issue'
    )

export type ChannelDetailEnumApi = zod.input<typeof ChannelDetailEnumApi>
export type ChannelDetailEnumApiOutput = zod.output<typeof ChannelDetailEnumApi>

export const TicketStatusEnumApi = zod
    .enum(['new', 'open', 'pending', 'on_hold', 'resolved'])
    .describe(
        '\* `new` - New\n\* `open` - Open\n\* `pending` - Pending\n\* `on_hold` - On hold\n\* `resolved` - Resolved'
    )

export type TicketStatusEnumApi = zod.input<typeof TicketStatusEnumApi>
export type TicketStatusEnumApiOutput = zod.output<typeof TicketStatusEnumApi>

export const TicketPriorityEnumApi = zod
    .enum(['low', 'medium', 'high', 'critical'])
    .describe('\* `low` - Low\n\* `medium` - Medium\n\* `high` - High\n\* `critical` - Critical')

export type TicketPriorityEnumApi = zod.input<typeof TicketPriorityEnumApi>
export type TicketPriorityEnumApiOutput = zod.output<typeof TicketPriorityEnumApi>

export const TicketAssignmentApi = zod
    .object({
        id: zod.string().nullable(),
        type: zod.string(),
        user: zod.record(zod.string(), zod.string()).nullable(),
        role: zod.record(zod.string(), zod.string()).nullable(),
    })
    .describe('Serializer for ticket assignment (user or role).')

export type TicketAssignmentApi = zod.input<typeof TicketAssignmentApi>
export type TicketAssignmentApiOutput = zod.output<typeof TicketAssignmentApi>

export const TicketPersonApi = zod
    .object({
        id: zod.uuid(),
        name: zod.string(),
        distinct_ids: zod.array(zod.string()),
        properties: zod.record(zod.string(), zod.unknown()),
        created_at: zod.iso.datetime({ offset: true }),
        is_identified: zod.boolean(),
    })
    .describe('Minimal person serializer for embedding in ticket responses.')

export type TicketPersonApi = zod.input<typeof TicketPersonApi>
export type TicketPersonApiOutput = zod.output<typeof TicketPersonApi>

export const TicketApi = zod
    .object({
        id: zod.uuid(),
        ticket_number: zod.number(),
        channel_source: ChannelSourceEnumApi,
        channel_detail: zod.union([ChannelDetailEnumApi, zod.null()]),
        distinct_id: zod.string(),
        status: TicketStatusEnumApi.optional().describe(
            'Ticket status: new, open, pending, on_hold, or resolved\n\n\* `new` - New\n\* `open` - Open\n\* `pending` - Pending\n\* `on_hold` - On hold\n\* `resolved` - Resolved'
        ),
        priority: zod
            .union([TicketPriorityEnumApi, BlankEnumApi, zod.null()])
            .optional()
            .describe(
                'Ticket priority: low, medium, high, or critical. Null if unset.\n\n\* `low` - Low\n\* `medium` - Medium\n\* `high` - High\n\* `critical` - Critical'
            ),
        assignee: TicketAssignmentApi,
        anonymous_traits: zod.unknown().optional().describe('Customer-provided traits such as name and email'),
        identity_verified: zod
            .boolean()
            .nullable()
            .describe(
                "Trust signal indicating whether the ticket's claimed identity was attested by the server (widget HMAC, SPF-authenticated email, or a signature-validated platform webhook). True when verified, false when assessed but not attested, null when unknown (e.g. created before this signal existed)."
            ),
        ai_resolved: zod.boolean().optional(),
        escalation_reason: zod.string().nullish(),
        ai_triage: zod
            .unknown()
            .describe(
                'AI support pipeline triage and outcome (status, result, ticket_type, confidence, attempts, etc.).'
            ),
        created_at: zod.iso.datetime({ offset: true }),
        updated_at: zod.iso.datetime({ offset: true }),
        message_count: zod.number(),
        last_message_at: zod.iso.datetime({ offset: true }).nullable(),
        last_message_text: zod.string().nullable(),
        unread_team_count: zod.number(),
        unread_customer_count: zod.number(),
        session_id: zod.string().nullable(),
        session_context: zod.unknown(),
        sla_due_at: zod.iso
            .datetime({ offset: true })
            .nullish()
            .describe('SLA deadline set via workflows. Null means no SLA.'),
        snoozed_until: zod.iso.datetime({ offset: true }).nullish(),
        slack_channel_id: zod.string().nullable(),
        slack_thread_ts: zod.string().nullable(),
        slack_team_id: zod.string().nullable(),
        email_subject: zod.string().nullable(),
        email_from: zod.email().nullable(),
        email_to: zod.string().nullable(),
        cc_participants: zod.unknown(),
        github_repo: zod.string().nullable(),
        github_issue_number: zod.number().nullable(),
        zendesk_ticket_id: zod.number().nullable(),
        organization_id: zod
            .string()
            .nullable()
            .describe("Customer's PostHog organization group key, resolved at ticket creation. Null when unknown."),
        organization_id_source: zod
            .string()
            .nullable()
            .describe(
                "How organization_id was resolved: 'person' (from the requester's identity) or 'slack_channel_account' (inferred from the customer analytics account linked to the ticket's Slack channel). Null when organization_id is unset."
            ),
        person: zod.union([TicketPersonApi, zod.null()]),
        tags: zod.array(zod.unknown()).optional(),
        user_access_level: zod.string().nullable().describe('The effective access level the user has for this object'),
    })
    .describe('Mixin for serializers to add user access control fields')

export type TicketApi = zod.input<typeof TicketApi>
export type TicketApiOutput = zod.output<typeof TicketApi>

export const PaginatedTicketListApi = zod.object({
    count: zod.number(),
    next: zod.url().nullish(),
    previous: zod.url().nullish(),
    results: zod.array(TicketApi),
})

export type PaginatedTicketListApi = zod.input<typeof PaginatedTicketListApi>
export type PaginatedTicketListApiOutput = zod.output<typeof PaginatedTicketListApi>

export const PatchedTicketApi = zod
    .object({
        id: zod.uuid().optional(),
        ticket_number: zod.number().optional(),
        channel_source: ChannelSourceEnumApi.optional(),
        channel_detail: zod.union([ChannelDetailEnumApi, zod.null()]).optional(),
        distinct_id: zod.string().optional(),
        status: TicketStatusEnumApi.optional().describe(
            'Ticket status: new, open, pending, on_hold, or resolved\n\n\* `new` - New\n\* `open` - Open\n\* `pending` - Pending\n\* `on_hold` - On hold\n\* `resolved` - Resolved'
        ),
        priority: zod
            .union([TicketPriorityEnumApi, BlankEnumApi, zod.null()])
            .optional()
            .describe(
                'Ticket priority: low, medium, high, or critical. Null if unset.\n\n\* `low` - Low\n\* `medium` - Medium\n\* `high` - High\n\* `critical` - Critical'
            ),
        assignee: TicketAssignmentApi.optional(),
        anonymous_traits: zod.unknown().optional().describe('Customer-provided traits such as name and email'),
        identity_verified: zod
            .boolean()
            .nullish()
            .describe(
                "Trust signal indicating whether the ticket's claimed identity was attested by the server (widget HMAC, SPF-authenticated email, or a signature-validated platform webhook). True when verified, false when assessed but not attested, null when unknown (e.g. created before this signal existed)."
            ),
        ai_resolved: zod.boolean().optional(),
        escalation_reason: zod.string().nullish(),
        ai_triage: zod
            .unknown()
            .optional()
            .describe(
                'AI support pipeline triage and outcome (status, result, ticket_type, confidence, attempts, etc.).'
            ),
        created_at: zod.iso.datetime({ offset: true }).optional(),
        updated_at: zod.iso.datetime({ offset: true }).optional(),
        message_count: zod.number().optional(),
        last_message_at: zod.iso.datetime({ offset: true }).nullish(),
        last_message_text: zod.string().nullish(),
        unread_team_count: zod.number().optional(),
        unread_customer_count: zod.number().optional(),
        session_id: zod.string().nullish(),
        session_context: zod.unknown().optional(),
        sla_due_at: zod.iso
            .datetime({ offset: true })
            .nullish()
            .describe('SLA deadline set via workflows. Null means no SLA.'),
        snoozed_until: zod.iso.datetime({ offset: true }).nullish(),
        slack_channel_id: zod.string().nullish(),
        slack_thread_ts: zod.string().nullish(),
        slack_team_id: zod.string().nullish(),
        email_subject: zod.string().nullish(),
        email_from: zod.email().nullish(),
        email_to: zod.string().nullish(),
        cc_participants: zod.unknown().optional(),
        github_repo: zod.string().nullish(),
        github_issue_number: zod.number().nullish(),
        zendesk_ticket_id: zod.number().nullish(),
        organization_id: zod
            .string()
            .nullish()
            .describe("Customer's PostHog organization group key, resolved at ticket creation. Null when unknown."),
        organization_id_source: zod
            .string()
            .nullish()
            .describe(
                "How organization_id was resolved: 'person' (from the requester's identity) or 'slack_channel_account' (inferred from the customer analytics account linked to the ticket's Slack channel). Null when organization_id is unset."
            ),
        person: zod.union([TicketPersonApi, zod.null()]).optional(),
        tags: zod.array(zod.unknown()).optional(),
        user_access_level: zod.string().nullish().describe('The effective access level the user has for this object'),
    })
    .describe('Mixin for serializers to add user access control fields')

export type PatchedTicketApi = zod.input<typeof PatchedTicketApi>
export type PatchedTicketApiOutput = zod.output<typeof PatchedTicketApi>

export const RatingEnumApi = zod.enum(['good', 'bad']).describe('\* `good` - good\n\* `bad` - bad')

export type RatingEnumApi = zod.input<typeof RatingEnumApi>
export type RatingEnumApiOutput = zod.output<typeof RatingEnumApi>

export const aiFeedbackRequestApiMessageIdMax = 200

export const aiFeedbackRequestApiFeedbackTextMax = 2000

export const AiFeedbackRequestApi = zod
    .object({
        message_id: zod.string().max(aiFeedbackRequestApiMessageIdMax).describe('ID of the AI message being rated.'),
        rating: RatingEnumApi.describe('Reviewer rating: good or bad.\n\n\* `good` - good\n\* `bad` - bad'),
        feedback_text: zod
            .string()
            .max(aiFeedbackRequestApiFeedbackTextMax)
            .optional()
            .describe('Optional text explaining a bad rating.'),
    })
    .describe('Payload for recording reviewer feedback on an AI reply.')

export type AiFeedbackRequestApi = zod.input<typeof AiFeedbackRequestApi>
export type AiFeedbackRequestApiOutput = zod.output<typeof AiFeedbackRequestApi>

export const TicketMessageApi = zod
    .object({
        id: zod.uuid().describe('Message (comment) UUID.'),
        content: zod.string().describe('Plain-text message body.'),
        rich_content: zod.unknown().describe('TipTap rich content JSON, if any.'),
        author_type: zod.string().describe('One of: customer, support, AI.'),
        author_name: zod.string().describe('Display name of the author.'),
        is_private: zod.boolean().describe('True for internal notes not visible to the customer.'),
        created_at: zod.iso.datetime({ offset: true }),
    })
    .describe('A single message in a ticket thread (output-only).')

export type TicketMessageApi = zod.input<typeof TicketMessageApi>
export type TicketMessageApiOutput = zod.output<typeof TicketMessageApi>

export const PaginatedTicketMessageListApi = zod.object({
    count: zod.number(),
    next: zod.url().nullish(),
    previous: zod.url().nullish(),
    results: zod.array(TicketMessageApi),
})

export type PaginatedTicketMessageListApi = zod.input<typeof PaginatedTicketMessageListApi>
export type PaginatedTicketMessageListApiOutput = zod.output<typeof PaginatedTicketMessageListApi>

export const ticketReplyRequestApiMessageMax = 5000

export const ticketReplyRequestApiIsPrivateDefault = false

export const TicketReplyRequestApi = zod
    .object({
        message: zod.string().max(ticketReplyRequestApiMessageMax).describe('Reply content in markdown.'),
        is_private: zod
            .boolean()
            .default(ticketReplyRequestApiIsPrivateDefault)
            .describe(
                "If true, store as an internal note (not sent to the customer). If false, the reply is delivered to the customer over the ticket's channel."
            ),
        rich_content: zod.unknown().optional().describe('Optional TipTap rich content JSON for formatted messages.'),
    })
    .describe('Payload for posting a reply or internal note to a ticket.')

export type TicketReplyRequestApi = zod.input<typeof TicketReplyRequestApi>
export type TicketReplyRequestApiOutput = zod.output<typeof TicketReplyRequestApi>

export const bulkUpdateStatusRequestApiIdsMax = 500

export const BulkUpdateStatusRequestApi = zod.object({
    ids: zod.array(zod.uuid()).max(bulkUpdateStatusRequestApiIdsMax).describe('List of ticket UUIDs to update.'),
    status: TicketStatusEnumApi.describe(
        'New status to apply to all selected tickets: new, open, pending, on_hold, or resolved.\n\n\* `new` - New\n\* `open` - Open\n\* `pending` - Pending\n\* `on_hold` - On hold\n\* `resolved` - Resolved'
    ),
})

export type BulkUpdateStatusRequestApi = zod.input<typeof BulkUpdateStatusRequestApi>
export type BulkUpdateStatusRequestApiOutput = zod.output<typeof BulkUpdateStatusRequestApi>

export const BulkUpdateStatusResponseApi = zod.object({
    updated: zod.number().describe('Number of tickets whose status actually changed.'),
    ids: zod.array(zod.uuid()).describe('UUIDs of the tickets whose status changed.'),
})

export type BulkUpdateStatusResponseApi = zod.input<typeof BulkUpdateStatusResponseApi>
export type BulkUpdateStatusResponseApiOutput = zod.output<typeof BulkUpdateStatusResponseApi>

export const BulkUpdateTagsActionEnumApi = zod
    .enum(['add', 'remove', 'set'])
    .describe('\* `add` - add\n\* `remove` - remove\n\* `set` - set')

export type BulkUpdateTagsActionEnumApi = zod.input<typeof BulkUpdateTagsActionEnumApi>
export type BulkUpdateTagsActionEnumApiOutput = zod.output<typeof BulkUpdateTagsActionEnumApi>

export const bulkUpdateTagsRequestApiIdsMax = 500

export const BulkUpdateTagsRequestApi = zod.object({
    ids: zod.array(zod.number()).max(bulkUpdateTagsRequestApiIdsMax).describe('List of object IDs to update tags on.'),
    action: BulkUpdateTagsActionEnumApi.describe(
        "'add' merges with existing tags, 'remove' deletes specific tags, 'set' replaces all tags.\n\n\* `add` - add\n\* `remove` - remove\n\* `set` - set"
    ),
    tags: zod.array(zod.string()).describe('Tag names to add, remove, or set.'),
})

export type BulkUpdateTagsRequestApi = zod.input<typeof BulkUpdateTagsRequestApi>
export type BulkUpdateTagsRequestApiOutput = zod.output<typeof BulkUpdateTagsRequestApi>

export const BulkUpdateTagsItemApi = zod.object({
    id: zod.number(),
    tags: zod.array(zod.string()),
})

export type BulkUpdateTagsItemApi = zod.input<typeof BulkUpdateTagsItemApi>
export type BulkUpdateTagsItemApiOutput = zod.output<typeof BulkUpdateTagsItemApi>

export const BulkUpdateTagsErrorApi = zod.object({
    id: zod.number(),
    reason: zod.string(),
})

export type BulkUpdateTagsErrorApi = zod.input<typeof BulkUpdateTagsErrorApi>
export type BulkUpdateTagsErrorApiOutput = zod.output<typeof BulkUpdateTagsErrorApi>

export const BulkUpdateTagsResponseApi = zod.object({
    updated: zod.array(BulkUpdateTagsItemApi),
    skipped: zod.array(BulkUpdateTagsErrorApi),
})

export type BulkUpdateTagsResponseApi = zod.input<typeof BulkUpdateTagsResponseApi>
export type BulkUpdateTagsResponseApiOutput = zod.output<typeof BulkUpdateTagsResponseApi>

export const composeTicketApiRecipientDistinctIdMax = 400

export const composeTicketApiEmailSubjectMax = 500

export const composeTicketApiMessageMax = 5000

export const ComposeTicketApi = zod.object({
    recipient_email: zod.email().describe('Recipient email address.'),
    recipient_distinct_id: zod
        .string()
        .max(composeTicketApiRecipientDistinctIdMax)
        .optional()
        .describe('PostHog distinct_id to link the ticket to a person. Falls back to recipient_email.'),
    email_subject: zod.string().max(composeTicketApiEmailSubjectMax).optional().describe('Email subject line.'),
    email_config_id: zod.uuid().describe('ID of the EmailChannel to send from.'),
    message: zod.string().max(composeTicketApiMessageMax).describe('Message content in markdown.'),
    rich_content: zod.unknown().optional().describe('TipTap rich content JSON for formatted messages.'),
})

export type ComposeTicketApi = zod.input<typeof ComposeTicketApi>
export type ComposeTicketApiOutput = zod.output<typeof ComposeTicketApi>

export const ComposeTicketResponseApi = zod.object({
    id: zod.uuid().describe('Created ticket UUID.'),
    ticket_number: zod.number().describe('Human-readable ticket number.'),
})

export type ComposeTicketResponseApi = zod.input<typeof ComposeTicketResponseApi>
export type ComposeTicketResponseApiOutput = zod.output<typeof ComposeTicketResponseApi>

export const TicketErrorApi = zod.object({
    detail: zod.string(),
    error_type: zod.string().optional(),
})

export type TicketErrorApi = zod.input<typeof TicketErrorApi>
export type TicketErrorApiOutput = zod.output<typeof TicketErrorApi>

export const ticketViewApiNameMax = 400

export const TicketViewApi = zod.object({
    id: zod.uuid(),
    short_id: zod.string(),
    name: zod.string().max(ticketViewApiNameMax),
    filters: zod
        .record(zod.string(), zod.unknown())
        .optional()
        .describe(
            'Saved ticket filter criteria. May contain status, priority, channel, sla, assignee, tags, dateFrom, dateTo, and sorting keys.'
        ),
    created_at: zod.iso.datetime({ offset: true }),
    created_by: UserBasicApi,
    is_favorited: zod
        .boolean()
        .optional()
        .describe(
            'Whether the current user has favorited this view. Favorited views sort to the top of the list. Favorites are personal to each user.'
        ),
})

export type TicketViewApi = zod.input<typeof TicketViewApi>
export type TicketViewApiOutput = zod.output<typeof TicketViewApi>

export const PaginatedTicketViewListApi = zod.object({
    count: zod.number(),
    next: zod.url().nullish(),
    previous: zod.url().nullish(),
    results: zod.array(TicketViewApi),
})

export type PaginatedTicketViewListApi = zod.input<typeof PaginatedTicketViewListApi>
export type PaginatedTicketViewListApiOutput = zod.output<typeof PaginatedTicketViewListApi>

export const patchedTicketViewApiNameMax = 400

export const PatchedTicketViewApi = zod.object({
    id: zod.uuid().optional(),
    short_id: zod.string().optional(),
    name: zod.string().max(patchedTicketViewApiNameMax).optional(),
    filters: zod
        .record(zod.string(), zod.unknown())
        .optional()
        .describe(
            'Saved ticket filter criteria. May contain status, priority, channel, sla, assignee, tags, dateFrom, dateTo, and sorting keys.'
        ),
    created_at: zod.iso.datetime({ offset: true }).optional(),
    created_by: UserBasicApi.optional(),
    is_favorited: zod
        .boolean()
        .optional()
        .describe(
            'Whether the current user has favorited this view. Favorited views sort to the top of the list. Favorites are personal to each user.'
        ),
})

export type PatchedTicketViewApi = zod.input<typeof PatchedTicketViewApi>
export type PatchedTicketViewApiOutput = zod.output<typeof PatchedTicketViewApi>

export const zendeskImportStartApiSubdomainMax = 255

export const zendeskImportStartApiApiTokenMax = 500

export const ZendeskImportStartApi = zod.object({
    subdomain: zod
        .string()
        .max(zendeskImportStartApiSubdomainMax)
        .describe("Zendesk subdomain (e.g. 'acme' from acme.zendesk.com)."),
    email_address: zod.email().describe('Zendesk agent email tied to the API token.'),
    api_token: zod
        .string()
        .max(zendeskImportStartApiApiTokenMax)
        .describe('Zendesk API token with ticket read access.'),
    default_email_channel_id: zod
        .uuid()
        .nullish()
        .describe(
            "Optional fallback email channel for tickets whose original Zendesk recipient doesn't match a configured support address (or isn't an email). Omit or null to leave those tickets without an email channel."
        ),
})

export type ZendeskImportStartApi = zod.input<typeof ZendeskImportStartApi>
export type ZendeskImportStartApiOutput = zod.output<typeof ZendeskImportStartApi>

export const ZendeskImportJobStatusEnumApi = zod
    .enum(['pending', 'running', 'completed', 'failed'])
    .describe('\* `pending` - Pending\n\* `running` - Running\n\* `completed` - Completed\n\* `failed` - Failed')

export type ZendeskImportJobStatusEnumApi = zod.input<typeof ZendeskImportJobStatusEnumApi>
export type ZendeskImportJobStatusEnumApiOutput = zod.output<typeof ZendeskImportJobStatusEnumApi>

export const ZendeskImportJobApi = zod.object({
    id: zod.uuid().describe('Unique identifier for the import job.'),
    status: ZendeskImportJobStatusEnumApi.describe(
        'Current job state: pending, running, completed, or failed.\n\n\* `pending` - Pending\n\* `running` - Running\n\* `completed` - Completed\n\* `failed` - Failed'
    ),
    subdomain: zod.string().nullable().describe('Zendesk subdomain used for this import job.'),
    has_credentials: zod
        .boolean()
        .describe('Whether stored Zendesk credentials exist for this job (the token\/email are never returned).'),
    total_tickets: zod.number().describe('Total number of tickets discovered for import.'),
    processed_tickets: zod.number().describe('Number of tickets processed so far.'),
    imported_tickets: zod.number().describe('Number of tickets successfully imported.'),
    skipped_tickets: zod.number().describe('Number of tickets skipped because they were already imported.'),
    failed_tickets: zod.number().describe('Number of tickets that failed to import.'),
    started_at: zod.iso.datetime({ offset: true }).nullable().describe('When the import started running.'),
    finished_at: zod.iso.datetime({ offset: true }).nullable().describe('When the import reached a terminal state.'),
    latest_error: zod.string().nullable().describe('Generic, user-safe error message when the job failed.'),
    created_at: zod.iso.datetime({ offset: true }).describe('When the import job was created.'),
    updated_at: zod.iso.datetime({ offset: true }).describe('When the import job was last updated.'),
})

export type ZendeskImportJobApi = zod.input<typeof ZendeskImportJobApi>
export type ZendeskImportJobApiOutput = zod.output<typeof ZendeskImportJobApi>

export const ZendeskImportErrorApi = zod.object({
    detail: zod.string().describe('Human-readable error message.'),
})

export type ZendeskImportErrorApi = zod.input<typeof ZendeskImportErrorApi>
export type ZendeskImportErrorApiOutput = zod.output<typeof ZendeskImportErrorApi>
