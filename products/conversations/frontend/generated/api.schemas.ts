/**
 * Auto-generated from the Django backend OpenAPI schema.
 * To modify these types, update the Django serializers or views, then run:
 *   hogli build:openapi
 * Questions or issues? #team-devex on Slack
 *
 * PostHog API - generated
 * OpenAPI spec version: 1.0.0
 */
/**
 * * `idle` - Idle
 * * `in_progress` - In progress
 * * `canceling` - Canceling
 */
export type ConversationStatusApi = (typeof ConversationStatusApi)[keyof typeof ConversationStatusApi]

export const ConversationStatusApi = {
    Idle: 'idle',
    InProgress: 'in_progress',
    Canceling: 'canceling',
} as const

/**
 * * `web_analytics` - Web analytics
 * * `product_analytics` - Product analytics
 * * `session_replay` - Session replay
 * * `surveys` - Surveys
 * * `feature_flags` - Feature flags
 * * `experiments` - Experiments
 * * `error_tracking` - Error tracking
 * * `data_warehouse` - Data warehouse
 * * `other` - Other
 */
export type TopicEnumApi = (typeof TopicEnumApi)[keyof typeof TopicEnumApi]

export const TopicEnumApi = {
    WebAnalytics: 'web_analytics',
    ProductAnalytics: 'product_analytics',
    SessionReplay: 'session_replay',
    Surveys: 'surveys',
    FeatureFlags: 'feature_flags',
    Experiments: 'experiments',
    ErrorTracking: 'error_tracking',
    DataWarehouse: 'data_warehouse',
    Other: 'other',
} as const

/**
 * * `engineering` - Engineering
 * * `data` - Data
 * * `product` - Product Management
 * * `founder` - Founder
 * * `leadership` - Leadership
 * * `marketing` - Marketing
 * * `sales` - Sales / Success
 * * `other` - Other
 */
export type RoleAtOrganizationEnumApi = (typeof RoleAtOrganizationEnumApi)[keyof typeof RoleAtOrganizationEnumApi]

export const RoleAtOrganizationEnumApi = {
    Engineering: 'engineering',
    Data: 'data',
    Product: 'product',
    Founder: 'founder',
    Leadership: 'leadership',
    Marketing: 'marketing',
    Sales: 'sales',
    Other: 'other',
} as const

export type BlankEnumApi = (typeof BlankEnumApi)[keyof typeof BlankEnumApi]

export const BlankEnumApi = {
    '': '',
} as const

/**
 * @nullable
 */
export type UserBasicApiHedgehogConfig = { [key: string]: unknown } | null

export interface UserBasicApi {
    readonly id: number
    readonly uuid: string
    /**
     * @maxLength 200
     * @nullable
     */
    distinct_id?: string | null
    /** @maxLength 150 */
    first_name?: string
    /** @maxLength 150 */
    last_name?: string
    /** @maxLength 254 */
    email: string
    /** @nullable */
    is_email_verified?: boolean | null
    /** @nullable */
    readonly hedgehog_config: UserBasicApiHedgehogConfig
    role_at_organization?: RoleAtOrganizationEnumApi | BlankEnumApi | null
}

/**
 * * `assistant` - Assistant
 * * `tool_call` - Tool call
 * * `deep_research` - Deep research
 * * `slack` - Slack
 */
export type ConversationTypeApi = (typeof ConversationTypeApi)[keyof typeof ConversationTypeApi]

export const ConversationTypeApi = {
    Assistant: 'assistant',
    ToolCall: 'tool_call',
    DeepResearch: 'deep_research',
    Slack: 'slack',
} as const

/**
 * @nullable
 */
export type TaskUserBasicInfoApiHedgehogConfig = { [key: string]: unknown } | null

/**
 * Response shape for a task creator, mirroring core ``UserBasicSerializer`` output.
 */
export interface TaskUserBasicInfoApi {
    id: number
    uuid: string
    distinct_id: string
    first_name: string
    last_name: string
    email: string
    /** @nullable */
    is_email_verified?: boolean | null
    /** @nullable */
    hedgehog_config?: TaskUserBasicInfoApiHedgehogConfig
    /** @nullable */
    role_at_organization?: string | null
}

/**
 * @nullable
 */
export type TaskDetailDTOApiJsonSchema = { [key: string]: unknown } | null

/**
 * Conversation envelope variant: ``latest_run`` is just the latest run's id, not the nested
 * run detail. The frontend only needs the id to reconnect to sandbox logs, and emitting the id
 * avoids presigning a log URL per conversation.
 *
 * Read access here follows the conversation (the share-by-link unit), not per-creator task
 * visibility — write/send stays creator-gated. See ``tasks_facade.get_conversation_task_dtos``.
 */
export interface TaskDetailDTOApi {
    id: string
    /** @nullable */
    task_number: number | null
    slug: string
    title: string
    title_manually_set: boolean
    description: string
    origin_product: string
    /** @nullable */
    repository: string | null
    /** @nullable */
    github_integration: number | null
    /** @nullable */
    github_user_integration: string | null
    /** @nullable */
    signal_report: string | null
    /** @nullable */
    json_schema: TaskDetailDTOApiJsonSchema
    internal: boolean
    archived: boolean
    /** @nullable */
    archived_at: string | null
    /**
     * Id of the latest TaskRun; null when the task has no runs.
     * @nullable
     */
    readonly latest_run: string | null
    /** @nullable */
    created_at?: string | null
    /** @nullable */
    updated_at?: string | null
    created_by?: TaskUserBasicInfoApi | null
    /** @nullable */
    ci_prompt: string | null
}

export interface ConversationMinimalApi {
    readonly id: string
    readonly status: ConversationStatusApi
    /**
     * Title of the conversation.
     * @nullable
     */
    readonly title: string | null
    /** Product domain the conversation is about, classified from the first question.
     *
     * * `web_analytics` - Web analytics
     * * `product_analytics` - Product analytics
     * * `session_replay` - Session replay
     * * `surveys` - Surveys
     * * `feature_flags` - Feature flags
     * * `experiments` - Experiments
     * * `error_tracking` - Error tracking
     * * `data_warehouse` - Data warehouse
     * * `other` - Other */
    readonly topic: TopicEnumApi | null
    readonly user: UserBasicApi
    /** @nullable */
    readonly created_at: string | null
    /** @nullable */
    readonly updated_at: string | null
    readonly type: ConversationTypeApi
    /**
     * Whether this conversation was created during an impersonated session (e.g., by support agents). Internal conversations are hidden from customers.
     * @nullable
     */
    readonly is_internal: boolean | null
    /**
     * Unique key for Slack thread: '{workspace_id}:{channel}:{thread_ts}'
     * @nullable
     */
    readonly slack_thread_key: string | null
    /**
     * Slack workspace subdomain (e.g. 'posthog' for posthog.slack.com)
     * @nullable
     */
    readonly slack_workspace_domain: string | null
    readonly task: TaskDetailDTOApi | null
}

export interface PaginatedConversationMinimalListApi {
    count: number
    /** @nullable */
    next?: string | null
    /** @nullable */
    previous?: string | null
    results: ConversationMinimalApi[]
}

export type MessageApiContextualTools = { [key: string]: unknown }

/**
 * * `product_analytics` - product_analytics
 * * `sql` - sql
 * * `session_replay` - session_replay
 * * `error_tracking` - error_tracking
 * * `plan` - plan
 * * `execution` - execution
 * * `survey` - survey
 * * `research` - research
 * * `flags` - flags
 * * `llm_analytics` - llm_analytics
 * * `sandbox` - sandbox
 * * `user_interview` - user_interview
 * * `customer_analytics` - customer_analytics
 */
export type AgentModeEnumApi = (typeof AgentModeEnumApi)[keyof typeof AgentModeEnumApi]

export const AgentModeEnumApi = {
    ProductAnalytics: 'product_analytics',
    Sql: 'sql',
    SessionReplay: 'session_replay',
    ErrorTracking: 'error_tracking',
    Plan: 'plan',
    Execution: 'execution',
    Survey: 'survey',
    Research: 'research',
    Flags: 'flags',
    LlmAnalytics: 'llm_analytics',
    Sandbox: 'sandbox',
    UserInterview: 'user_interview',
    CustomerAnalytics: 'customer_analytics',
} as const

/**
 * Serializer for appending a message to an existing conversation without triggering AI processing.
 */
export interface MessageApi {
    /**
     * @maxLength 40000
     * @nullable
     */
    content: string | null
    conversation: string
    contextual_tools?: MessageApiContextualTools
    ui_context?: unknown
    billing_context?: unknown
    trace_id: string
    session_id?: string
    agent_mode?: AgentModeEnumApi
    is_sandbox?: boolean
    resume_payload?: unknown
}

export type ConversationApiMessagesItem = { [key: string]: unknown }

export type ConversationApiPendingApprovalsItem = { [key: string]: unknown }

/**
 * * `langgraph` - LangGraph
 * * `sandbox` - Sandbox
 */
export type AgentRuntimeEnumApi = (typeof AgentRuntimeEnumApi)[keyof typeof AgentRuntimeEnumApi]

export const AgentRuntimeEnumApi = {
    Langgraph: 'langgraph',
    Sandbox: 'sandbox',
} as const

export interface ConversationApi {
    readonly id: string
    readonly status: ConversationStatusApi
    /**
     * Title of the conversation.
     * @nullable
     */
    readonly title: string | null
    /** Product domain the conversation is about, classified from the first question.
     *
     * * `web_analytics` - Web analytics
     * * `product_analytics` - Product analytics
     * * `session_replay` - Session replay
     * * `surveys` - Surveys
     * * `feature_flags` - Feature flags
     * * `experiments` - Experiments
     * * `error_tracking` - Error tracking
     * * `data_warehouse` - Data warehouse
     * * `other` - Other */
    readonly topic: TopicEnumApi | null
    readonly user: UserBasicApi
    /** @nullable */
    readonly created_at: string | null
    /** @nullable */
    readonly updated_at: string | null
    readonly type: ConversationTypeApi
    /**
     * Whether this conversation was created during an impersonated session (e.g., by support agents). Internal conversations are hidden from customers.
     * @nullable
     */
    readonly is_internal: boolean | null
    /**
     * Unique key for Slack thread: '{workspace_id}:{channel}:{thread_ts}'
     * @nullable
     */
    readonly slack_thread_key: string | null
    /**
     * Slack workspace subdomain (e.g. 'posthog' for posthog.slack.com)
     * @nullable
     */
    readonly slack_workspace_domain: string | null
    readonly messages: readonly ConversationApiMessagesItem[]
    readonly has_unsupported_content: boolean
    /** @nullable */
    readonly agent_mode: string | null
    /** Runtime that owns this conversation. 'langgraph' conversations return their messages in the `messages` field; born-'sandbox' conversations return an empty `messages` array and load history from the products/tasks logs endpoint. A converted conversation is 'sandbox' but still returns its legacy thread in `messages`.
     *
     * * `langgraph` - LangGraph
     * * `sandbox` - Sandbox */
    readonly agent_runtime: AgentRuntimeEnumApi
    readonly is_sandbox: boolean
    /** Return pending approval cards as structured data.
     *
     * Combines metadata from conversation.approval_decisions with payload from checkpoint
     * interrupts (single source of truth for payload data). */
    readonly pending_approvals: readonly ConversationApiPendingApprovalsItem[]
    readonly task: TaskDetailDTOApi | null
}

/**
 * Serializer for appending a message to an existing conversation without triggering AI processing.
 */
export interface MessageMinimalApi {
    /** @maxLength 10000 */
    content: string
}

export type PatchedConversationApiMessagesItem = { [key: string]: unknown }

export type PatchedConversationApiPendingApprovalsItem = { [key: string]: unknown }

export interface PatchedConversationApi {
    readonly id?: string
    readonly status?: ConversationStatusApi
    /**
     * Title of the conversation.
     * @nullable
     */
    readonly title?: string | null
    /** Product domain the conversation is about, classified from the first question.
     *
     * * `web_analytics` - Web analytics
     * * `product_analytics` - Product analytics
     * * `session_replay` - Session replay
     * * `surveys` - Surveys
     * * `feature_flags` - Feature flags
     * * `experiments` - Experiments
     * * `error_tracking` - Error tracking
     * * `data_warehouse` - Data warehouse
     * * `other` - Other */
    readonly topic?: TopicEnumApi | null
    readonly user?: UserBasicApi
    /** @nullable */
    readonly created_at?: string | null
    /** @nullable */
    readonly updated_at?: string | null
    readonly type?: ConversationTypeApi
    /**
     * Whether this conversation was created during an impersonated session (e.g., by support agents). Internal conversations are hidden from customers.
     * @nullable
     */
    readonly is_internal?: boolean | null
    /**
     * Unique key for Slack thread: '{workspace_id}:{channel}:{thread_ts}'
     * @nullable
     */
    readonly slack_thread_key?: string | null
    /**
     * Slack workspace subdomain (e.g. 'posthog' for posthog.slack.com)
     * @nullable
     */
    readonly slack_workspace_domain?: string | null
    readonly messages?: readonly PatchedConversationApiMessagesItem[]
    readonly has_unsupported_content?: boolean
    /** @nullable */
    readonly agent_mode?: string | null
    /** Runtime that owns this conversation. 'langgraph' conversations return their messages in the `messages` field; born-'sandbox' conversations return an empty `messages` array and load history from the products/tasks logs endpoint. A converted conversation is 'sandbox' but still returns its legacy thread in `messages`.
     *
     * * `langgraph` - LangGraph
     * * `sandbox` - Sandbox */
    readonly agent_runtime?: AgentRuntimeEnumApi
    readonly is_sandbox?: boolean
    /** Return pending approval cards as structured data.
     *
     * Combines metadata from conversation.approval_decisions with payload from checkpoint
     * interrupts (single source of truth for payload data). */
    readonly pending_approvals?: readonly PatchedConversationApiPendingApprovalsItem[]
    readonly task?: TaskDetailDTOApi | null
}

/**
 * * `action` - action
 * * `dashboard` - dashboard
 * * `error_tracking_issue` - error_tracking_issue
 * * `evaluation` - evaluation
 * * `event` - event
 * * `insight` - insight
 * * `notebook` - notebook
 * * `text` - text
 */
export type SandboxAttachedContextItemTypeEnumApi =
    (typeof SandboxAttachedContextItemTypeEnumApi)[keyof typeof SandboxAttachedContextItemTypeEnumApi]

export const SandboxAttachedContextItemTypeEnumApi = {
    Action: 'action',
    Dashboard: 'dashboard',
    ErrorTrackingIssue: 'error_tracking_issue',
    Evaluation: 'evaluation',
    Event: 'event',
    Insight: 'insight',
    Notebook: 'notebook',
    Text: 'text',
} as const

/**
 * One typed attachment carried by a sandbox message.
 */
export interface SandboxAttachedContextItemApi {
    /** Attachment kind. Entity types carry `id` (+ optional `name`); `text` carries `value`.
     *
     * * `action` - action
     * * `dashboard` - dashboard
     * * `error_tracking_issue` - error_tracking_issue
     * * `evaluation` - evaluation
     * * `event` - event
     * * `insight` - insight
     * * `notebook` - notebook
     * * `text` - text */
    type: SandboxAttachedContextItemTypeEnumApi
    /** Entity identifier — integer for `dashboard`/`action`, string short_id/UUID otherwise. Absent for `text`. */
    id?: unknown
    /** Optional human-readable label rendered in the context block. */
    name?: string
    /** Free-text content. Only for `text` attachments. */
    value?: string
}

/**
 * * `default` - default
 * * `acceptEdits` - acceptEdits
 * * `plan` - plan
 * * `bypassPermissions` - bypassPermissions
 * * `auto` - auto
 */
export type InitialPermissionModeEnumApi =
    (typeof InitialPermissionModeEnumApi)[keyof typeof InitialPermissionModeEnumApi]

export const InitialPermissionModeEnumApi = {
    Default: 'default',
    AcceptEdits: 'acceptEdits',
    Plan: 'plan',
    BypassPermissions: 'bypassPermissions',
    Auto: 'auto',
} as const

/**
 * Request body for `POST /conversations/{id}/open/`. A string `content` processes a turn; a
 * null/absent `content` warms a sandbox that idles awaiting the first message.
 */
export interface SandboxOpenApi {
    /**
     * The user's message text. Omit or null to warm a sandbox (boot + idle) ahead of the first message.
     * @maxLength 40000
     * @nullable
     */
    content?: string | null
    /** Client-generated trace id correlated with the resulting Run's SSE stream. */
    trace_id?: string
    /** Typed PostHog entities (and free text) attached to this message. */
    attached_context?: SandboxAttachedContextItemApi[]
    /** Initial permission mode for the sandbox agent session. Defaults to `auto`, which allows safe tool use while preserving explicit confirmations.
     *
     * * `default` - default
     * * `acceptEdits` - acceptEdits
     * * `plan` - plan
     * * `bypassPermissions` - bypassPermissions
     * * `auto` - auto */
    initial_permission_mode?: InitialPermissionModeEnumApi
    /** Bind a brand-new sandbox conversation to an existing Task so the first message resumes that Task's run. Honored only when this request creates the conversation row; ignored for an already-existing conversation. */
    task_id?: string
}

/**
 * Response for `POST /conversations/{id}/open/` — the IDs the frontend opens SSE against.
 */
export interface SandboxMessageResponseApi {
    /** The products/tasks Task backing the conversation. */
    task_id: string
    /** The Run the frontend opens SSE against. */
    run_id: string
    /**
     * Echo of the request trace id, if provided.
     * @nullable
     */
    trace_id: string | null
    /** Current status of the targeted Run (e.g. `queued`, `in_progress`). */
    run_status: string
    /** True when a new Run was created (first message, terminal resume, or fresh warm); false for an in-progress follow-up or a reused warm Run. */
    just_created_run: boolean
}

/**
 * * `widget` - Widget
 * * `email` - Email
 * * `slack` - Slack
 * * `teams` - Microsoft Teams
 * * `github` - GitHub
 */
export type ChannelSourceEnumApi = (typeof ChannelSourceEnumApi)[keyof typeof ChannelSourceEnumApi]

export const ChannelSourceEnumApi = {
    Widget: 'widget',
    Email: 'email',
    Slack: 'slack',
    Teams: 'teams',
    Github: 'github',
} as const

/**
 * * `slack_channel_message` - Channel message
 * * `slack_bot_mention` - Bot mention
 * * `slack_emoji_reaction` - Emoji reaction
 * * `teams_channel_message` - Teams channel message
 * * `teams_bot_mention` - Teams bot mention
 * * `widget_embedded` - Widget
 * * `widget_api` - API
 * * `github_issue` - GitHub issue
 */
export type ChannelDetailEnumApi = (typeof ChannelDetailEnumApi)[keyof typeof ChannelDetailEnumApi]

export const ChannelDetailEnumApi = {
    SlackChannelMessage: 'slack_channel_message',
    SlackBotMention: 'slack_bot_mention',
    SlackEmojiReaction: 'slack_emoji_reaction',
    TeamsChannelMessage: 'teams_channel_message',
    TeamsBotMention: 'teams_bot_mention',
    WidgetEmbedded: 'widget_embedded',
    WidgetApi: 'widget_api',
    GithubIssue: 'github_issue',
} as const

/**
 * * `new` - New
 * * `open` - Open
 * * `pending` - Pending
 * * `on_hold` - On hold
 * * `resolved` - Resolved
 */
export type TicketStatusEnumApi = (typeof TicketStatusEnumApi)[keyof typeof TicketStatusEnumApi]

export const TicketStatusEnumApi = {
    New: 'new',
    Open: 'open',
    Pending: 'pending',
    OnHold: 'on_hold',
    Resolved: 'resolved',
} as const

/**
 * * `low` - Low
 * * `medium` - Medium
 * * `high` - High
 */
export type TicketPriorityEnumApi = (typeof TicketPriorityEnumApi)[keyof typeof TicketPriorityEnumApi]

export const TicketPriorityEnumApi = {
    Low: 'low',
    Medium: 'medium',
    High: 'high',
} as const

/**
 * @nullable
 */
export type TicketAssignmentApiUser = { [key: string]: string } | null

/**
 * @nullable
 */
export type TicketAssignmentApiRole = { [key: string]: string } | null

/**
 * Serializer for ticket assignment (user or role).
 */
export interface TicketAssignmentApi {
    /** @nullable */
    readonly id: string | null
    readonly type: string
    /** @nullable */
    readonly user: TicketAssignmentApiUser
    /** @nullable */
    readonly role: TicketAssignmentApiRole
}

export type TicketPersonApiProperties = { [key: string]: unknown }

/**
 * Minimal person serializer for embedding in ticket responses.
 */
export interface TicketPersonApi {
    readonly id: string
    readonly name: string
    readonly distinct_ids: readonly string[]
    readonly properties: TicketPersonApiProperties
    readonly created_at: string
    readonly is_identified: boolean
}

/**
 * Serializer mixin that handles tags for objects.
 */
export interface TicketApi {
    readonly id: string
    readonly ticket_number: number
    readonly channel_source: ChannelSourceEnumApi
    readonly channel_detail: ChannelDetailEnumApi | null
    readonly distinct_id: string
    /** Ticket status: new, open, pending, on_hold, or resolved
     *
     * * `new` - New
     * * `open` - Open
     * * `pending` - Pending
     * * `on_hold` - On hold
     * * `resolved` - Resolved */
    status?: TicketStatusEnumApi
    /** Ticket priority: low, medium, or high. Null if unset.
     *
     * * `low` - Low
     * * `medium` - Medium
     * * `high` - High */
    priority?: TicketPriorityEnumApi | BlankEnumApi | null
    readonly assignee: TicketAssignmentApi
    /** Customer-provided traits such as name and email */
    anonymous_traits?: unknown
    /**
     * Trust signal indicating whether the ticket's claimed identity was attested by the server (widget HMAC, SPF-authenticated email, or a signature-validated platform webhook). True when verified, false when assessed but not attested, null when unknown (e.g. created before this signal existed).
     * @nullable
     */
    readonly identity_verified: boolean | null
    ai_resolved?: boolean
    /** @nullable */
    escalation_reason?: string | null
    /** AI support pipeline triage and outcome (status, result, ticket_type, confidence, attempts, etc.). */
    readonly ai_triage: unknown
    readonly created_at: string
    readonly updated_at: string
    readonly message_count: number
    /** @nullable */
    readonly last_message_at: string | null
    /** @nullable */
    readonly last_message_text: string | null
    readonly unread_team_count: number
    readonly unread_customer_count: number
    /** @nullable */
    readonly session_id: string | null
    readonly session_context: unknown
    /**
     * SLA deadline set via workflows. Null means no SLA.
     * @nullable
     */
    sla_due_at?: string | null
    /** @nullable */
    snoozed_until?: string | null
    /** @nullable */
    readonly slack_channel_id: string | null
    /** @nullable */
    readonly slack_thread_ts: string | null
    /** @nullable */
    readonly slack_team_id: string | null
    /** @nullable */
    readonly email_subject: string | null
    /** @nullable */
    readonly email_from: string | null
    /** @nullable */
    readonly email_to: string | null
    readonly cc_participants: unknown
    /** @nullable */
    readonly github_repo: string | null
    /** @nullable */
    readonly github_issue_number: number | null
    /** @nullable */
    readonly zendesk_ticket_id: number | null
    /**
     * Customer's PostHog organization group key, resolved at ticket creation. Null when unknown.
     * @nullable
     */
    readonly organization_id: string | null
    readonly person: TicketPersonApi | null
    tags?: unknown[]
}

export interface PaginatedTicketListApi {
    count: number
    /** @nullable */
    next?: string | null
    /** @nullable */
    previous?: string | null
    results: TicketApi[]
}

/**
 * Serializer mixin that handles tags for objects.
 */
export interface PatchedTicketApi {
    readonly id?: string
    readonly ticket_number?: number
    readonly channel_source?: ChannelSourceEnumApi
    readonly channel_detail?: ChannelDetailEnumApi | null
    readonly distinct_id?: string
    /** Ticket status: new, open, pending, on_hold, or resolved
     *
     * * `new` - New
     * * `open` - Open
     * * `pending` - Pending
     * * `on_hold` - On hold
     * * `resolved` - Resolved */
    status?: TicketStatusEnumApi
    /** Ticket priority: low, medium, or high. Null if unset.
     *
     * * `low` - Low
     * * `medium` - Medium
     * * `high` - High */
    priority?: TicketPriorityEnumApi | BlankEnumApi | null
    readonly assignee?: TicketAssignmentApi
    /** Customer-provided traits such as name and email */
    anonymous_traits?: unknown
    /**
     * Trust signal indicating whether the ticket's claimed identity was attested by the server (widget HMAC, SPF-authenticated email, or a signature-validated platform webhook). True when verified, false when assessed but not attested, null when unknown (e.g. created before this signal existed).
     * @nullable
     */
    readonly identity_verified?: boolean | null
    ai_resolved?: boolean
    /** @nullable */
    escalation_reason?: string | null
    /** AI support pipeline triage and outcome (status, result, ticket_type, confidence, attempts, etc.). */
    readonly ai_triage?: unknown
    readonly created_at?: string
    readonly updated_at?: string
    readonly message_count?: number
    /** @nullable */
    readonly last_message_at?: string | null
    /** @nullable */
    readonly last_message_text?: string | null
    readonly unread_team_count?: number
    readonly unread_customer_count?: number
    /** @nullable */
    readonly session_id?: string | null
    readonly session_context?: unknown
    /**
     * SLA deadline set via workflows. Null means no SLA.
     * @nullable
     */
    sla_due_at?: string | null
    /** @nullable */
    snoozed_until?: string | null
    /** @nullable */
    readonly slack_channel_id?: string | null
    /** @nullable */
    readonly slack_thread_ts?: string | null
    /** @nullable */
    readonly slack_team_id?: string | null
    /** @nullable */
    readonly email_subject?: string | null
    /** @nullable */
    readonly email_from?: string | null
    /** @nullable */
    readonly email_to?: string | null
    readonly cc_participants?: unknown
    /** @nullable */
    readonly github_repo?: string | null
    /** @nullable */
    readonly github_issue_number?: number | null
    /** @nullable */
    readonly zendesk_ticket_id?: number | null
    /**
     * Customer's PostHog organization group key, resolved at ticket creation. Null when unknown.
     * @nullable
     */
    readonly organization_id?: string | null
    readonly person?: TicketPersonApi | null
    tags?: unknown[]
}

/**
 * A single message in a ticket thread (output-only).
 */
export interface TicketMessageApi {
    /** Message (comment) UUID. */
    readonly id: string
    /** Plain-text message body. */
    readonly content: string
    /** TipTap rich content JSON, if any. */
    readonly rich_content: unknown
    /** One of: customer, support, AI. */
    readonly author_type: string
    /** Display name of the author. */
    readonly author_name: string
    /** True for internal notes not visible to the customer. */
    readonly is_private: boolean
    readonly created_at: string
}

export interface PaginatedTicketMessageListApi {
    count: number
    /** @nullable */
    next?: string | null
    /** @nullable */
    previous?: string | null
    results: TicketMessageApi[]
}

/**
 * Payload for posting a reply or internal note to a ticket.
 */
export interface TicketReplyRequestApi {
    /**
     * Reply content in markdown.
     * @maxLength 5000
     */
    message: string
    /** If true, store as an internal note (not sent to the customer). If false, the reply is delivered to the customer over the ticket's channel. */
    is_private?: boolean
    /** Optional TipTap rich content JSON for formatted messages. */
    rich_content?: unknown
}

export interface BulkUpdateStatusRequestApi {
    /**
     * List of ticket UUIDs to update.
     * @maxItems 500
     */
    ids: string[]
    /** New status to apply to all selected tickets: new, open, pending, on_hold, or resolved.
     *
     * * `new` - New
     * * `open` - Open
     * * `pending` - Pending
     * * `on_hold` - On hold
     * * `resolved` - Resolved */
    status: TicketStatusEnumApi
}

export interface BulkUpdateStatusResponseApi {
    /** Number of tickets whose status actually changed. */
    updated: number
    /** UUIDs of the tickets whose status changed. */
    ids: string[]
}

/**
 * * `add` - add
 * * `remove` - remove
 * * `set` - set
 */
export type ActionEnumApi = (typeof ActionEnumApi)[keyof typeof ActionEnumApi]

export const ActionEnumApi = {
    Add: 'add',
    Remove: 'remove',
    Set: 'set',
} as const

export interface BulkUpdateTagsRequestApi {
    /**
     * List of object IDs to update tags on.
     * @maxItems 500
     */
    ids: number[]
    /** 'add' merges with existing tags, 'remove' deletes specific tags, 'set' replaces all tags.
     *
     * * `add` - add
     * * `remove` - remove
     * * `set` - set */
    action: ActionEnumApi
    /** Tag names to add, remove, or set. */
    tags: string[]
}

export interface BulkUpdateTagsItemApi {
    id: number
    tags: string[]
}

export interface BulkUpdateTagsErrorApi {
    id: number
    reason: string
}

export interface BulkUpdateTagsResponseApi {
    updated: BulkUpdateTagsItemApi[]
    skipped: BulkUpdateTagsErrorApi[]
}

export interface ComposeTicketApi {
    /** Recipient email address. */
    recipient_email: string
    /**
     * PostHog distinct_id to link the ticket to a person. Falls back to recipient_email.
     * @maxLength 400
     */
    recipient_distinct_id?: string
    /**
     * Email subject line.
     * @maxLength 500
     */
    email_subject?: string
    /** ID of the EmailChannel to send from. */
    email_config_id: string
    /**
     * Message content in markdown.
     * @maxLength 5000
     */
    message: string
    /** TipTap rich content JSON for formatted messages. */
    rich_content?: unknown
}

export interface ComposeTicketResponseApi {
    /** Created ticket UUID. */
    id: string
    /** Human-readable ticket number. */
    ticket_number: number
}

export interface TicketErrorApi {
    detail: string
    error_type?: string
}

/**
 * Saved ticket filter criteria. May contain status, priority, channel, sla, assignee, tags, dateFrom, dateTo, and sorting keys.
 */
export type TicketViewApiFilters = { [key: string]: unknown }

export interface TicketViewApi {
    readonly id: string
    readonly short_id: string
    /** @maxLength 400 */
    name: string
    /** Saved ticket filter criteria. May contain status, priority, channel, sla, assignee, tags, dateFrom, dateTo, and sorting keys. */
    filters?: TicketViewApiFilters
    readonly created_at: string
    readonly created_by: UserBasicApi
}

export interface PaginatedTicketViewListApi {
    count: number
    /** @nullable */
    next?: string | null
    /** @nullable */
    previous?: string | null
    results: TicketViewApi[]
}

export interface ZendeskImportStartApi {
    /**
     * Zendesk subdomain (e.g. 'acme' from acme.zendesk.com).
     * @maxLength 255
     */
    subdomain: string
    /** Zendesk agent email tied to the API token. */
    email_address: string
    /**
     * Zendesk API token with ticket read access.
     * @maxLength 500
     */
    api_token: string
    /**
     * Optional fallback email channel for tickets whose original Zendesk recipient doesn't match a configured support address (or isn't an email). Omit or null to leave those tickets without an email channel.
     * @nullable
     */
    default_email_channel_id?: string | null
}

/**
 * * `pending` - Pending
 * * `running` - Running
 * * `completed` - Completed
 * * `failed` - Failed
 */
export type ZendeskImportJobStatusEnumApi =
    (typeof ZendeskImportJobStatusEnumApi)[keyof typeof ZendeskImportJobStatusEnumApi]

export const ZendeskImportJobStatusEnumApi = {
    Pending: 'pending',
    Running: 'running',
    Completed: 'completed',
    Failed: 'failed',
} as const

export interface ZendeskImportJobApi {
    /** Unique identifier for the import job. */
    readonly id: string
    /** Current job state: pending, running, completed, or failed.
     *
     * * `pending` - Pending
     * * `running` - Running
     * * `completed` - Completed
     * * `failed` - Failed */
    readonly status: ZendeskImportJobStatusEnumApi
    /**
     * Zendesk subdomain used for this import job.
     * @nullable
     */
    readonly subdomain: string | null
    /** Whether stored Zendesk credentials exist for this job (the token/email are never returned). */
    readonly has_credentials: boolean
    /** Total number of tickets discovered for import. */
    readonly total_tickets: number
    /** Number of tickets processed so far. */
    readonly processed_tickets: number
    /** Number of tickets successfully imported. */
    readonly imported_tickets: number
    /** Number of tickets skipped because they were already imported. */
    readonly skipped_tickets: number
    /** Number of tickets that failed to import. */
    readonly failed_tickets: number
    /**
     * When the import started running.
     * @nullable
     */
    readonly started_at: string | null
    /**
     * When the import reached a terminal state.
     * @nullable
     */
    readonly finished_at: string | null
    /**
     * Generic, user-safe error message when the job failed.
     * @nullable
     */
    readonly latest_error: string | null
    /** When the import job was created. */
    readonly created_at: string
    /** When the import job was last updated. */
    readonly updated_at: string
}

export interface ZendeskImportErrorApi {
    /** Human-readable error message. */
    detail: string
}

export type ConversationsListParams = {
    /**
     * Number of results to return per page.
     */
    limit?: number
    /**
     * The initial index from which to return the results.
     */
    offset?: number
}

export type ConversationsTicketsListParams = {
    /**
     * Filter by assignee. Use `unassigned` for tickets with no assignee, `user:<user_id>` for a specific user, or `role:<role_uuid>` for a role.
     */
    assignee?: string
    /**
     * Filter by the channel sub-type (e.g. `widget_embedded`, `slack_bot_mention`).
     */
    channel_detail?: ConversationsTicketsListChannelDetail
    /**
     * Filter by the channel the ticket originated from.
     */
    channel_source?: ConversationsTicketsListChannelSource
    /**
     * Only include tickets updated on or after this date. Accepts absolute dates (`2026-01-01`) or relative ones (`-7d`, `-1mStart`). Pass `all` to disable the filter.
     */
    date_from?: string
    /**
     * Only include tickets updated on or before this date. Same format as `date_from`.
     */
    date_to?: string
    /**
     * Comma-separated list of person `distinct_id`s to filter by (max 100).
     */
    distinct_ids?: string
    /**
     * Number of results to return per page.
     */
    limit?: number
    /**
     * The initial index from which to return the results.
     */
    offset?: number
    /**
     * Sort order. Prefix with `-` for descending. Defaults to `-updated_at`.
     */
    order_by?: string
    /**
     * Filter by priority. Accepts a single value or a comma-separated list (e.g. `medium,high`). Valid values: `low`, `medium`, `high`.
     */
    priority?: string
    /**
     * Free-text search. A numeric value matches a ticket number exactly; otherwise matches against the customer's name or email (case-insensitive, partial match).
     */
    search?: string
    /**
     * Filter by SLA state. `breached` = past `sla_due_at`, `at-risk` = due within the next hour, `on-track` = more than an hour remaining.
     */
    sla?: ConversationsTicketsListSla
    /**
     * Filter by status. Accepts a single value or a comma-separated list (e.g. `new,open,pending`). Valid values: `new`, `open`, `pending`, `on_hold`, `resolved`.
     */
    status?: string
    /**
     * JSON-encoded array of tag names; returns tickets with ANY of them (OR), e.g. `["billing","urgent"]`.
     */
    tags?: string
    /**
     * JSON-encoded array of tag names; returns tickets that have ALL of them (AND), e.g. `["billing","urgent"]`.
     */
    tags_all?: string
    /**
     * JSON-encoded array of tag names; returns tickets that have NONE of them (NOT), e.g. `["escalated"]`.
     */
    tags_exclude?: string
}

export type ConversationsTicketsListChannelDetail =
    (typeof ConversationsTicketsListChannelDetail)[keyof typeof ConversationsTicketsListChannelDetail]

export const ConversationsTicketsListChannelDetail = {
    GithubIssue: 'github_issue',
    SlackBotMention: 'slack_bot_mention',
    SlackChannelMessage: 'slack_channel_message',
    SlackEmojiReaction: 'slack_emoji_reaction',
    TeamsBotMention: 'teams_bot_mention',
    TeamsChannelMessage: 'teams_channel_message',
    WidgetApi: 'widget_api',
    WidgetEmbedded: 'widget_embedded',
} as const

export type ConversationsTicketsListChannelSource =
    (typeof ConversationsTicketsListChannelSource)[keyof typeof ConversationsTicketsListChannelSource]

export const ConversationsTicketsListChannelSource = {
    Email: 'email',
    Github: 'github',
    Slack: 'slack',
    Teams: 'teams',
    Widget: 'widget',
} as const

export type ConversationsTicketsListSla = (typeof ConversationsTicketsListSla)[keyof typeof ConversationsTicketsListSla]

export const ConversationsTicketsListSla = {
    AtRisk: 'at-risk',
    Breached: 'breached',
    OnTrack: 'on-track',
} as const

export type ConversationsTicketsMessagesListParams = {
    /**
     * Number of results to return per page.
     */
    limit?: number
    /**
     * The initial index from which to return the results.
     */
    offset?: number
}

export type ConversationsViewsListParams = {
    /**
     * Number of results to return per page.
     */
    limit?: number
    /**
     * The initial index from which to return the results.
     */
    offset?: number
}
