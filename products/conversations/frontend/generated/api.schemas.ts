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
 * `in_progress` - In progress
 * `canceling` - Canceling
 */
export type ConversationStatusEnumApi = (typeof ConversationStatusEnumApi)[keyof typeof ConversationStatusEnumApi]

export const ConversationStatusEnumApi = {
    Idle: 'idle',
    InProgress: 'in_progress',
    Canceling: 'canceling',
} as const

/**
 * * `engineering` - Engineering
 * `data` - Data
 * `product` - Product Management
 * `founder` - Founder
 * `leadership` - Leadership
 * `marketing` - Marketing
 * `sales` - Sales / Success
 * `other` - Other
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

export type NullEnumApi = (typeof NullEnumApi)[keyof typeof NullEnumApi]

export const NullEnumApi = {} as const

/**
 * @nullable
 */
export type UserBasicApiHedgehogConfig = { [key: string]: unknown } | null | null

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
    role_at_organization?: RoleAtOrganizationEnumApi | BlankEnumApi | NullEnumApi | null
}

/**
 * * `assistant` - Assistant
 * `tool_call` - Tool call
 * `deep_research` - Deep research
 * `slack` - Slack
 */
export type ConversationTypeEnumApi = (typeof ConversationTypeEnumApi)[keyof typeof ConversationTypeEnumApi]

export const ConversationTypeEnumApi = {
    Assistant: 'assistant',
    ToolCall: 'tool_call',
    DeepResearch: 'deep_research',
    Slack: 'slack',
} as const

export type ConversationApiMessagesItem = { [key: string]: unknown }

export type ConversationApiPendingApprovalsItem = { [key: string]: unknown }

export interface ConversationApi {
    readonly id: string
    readonly status: ConversationStatusEnumApi
    /**
     * Title of the conversation.
     * @nullable
     */
    readonly title: string | null
    readonly user: UserBasicApi
    /** @nullable */
    readonly created_at: string | null
    /** @nullable */
    readonly updated_at: string | null
    readonly type: ConversationTypeEnumApi
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
    readonly is_sandbox: boolean
    /** Return pending approval cards as structured data.

Combines metadata from conversation.approval_decisions with payload from checkpoint
interrupts (single source of truth for payload data). */
    readonly pending_approvals: readonly ConversationApiPendingApprovalsItem[]
}

export interface PaginatedConversationListApi {
    count: number
    /** @nullable */
    next?: string | null
    /** @nullable */
    previous?: string | null
    results: ConversationApi[]
}

export type MessageApiContextualTools = { [key: string]: unknown }

/**
 * * `product_analytics` - product_analytics
 * `sql` - sql
 * `session_replay` - session_replay
 * `error_tracking` - error_tracking
 * `plan` - plan
 * `execution` - execution
 * `survey` - survey
 * `research` - research
 * `flags` - flags
 * `llm_analytics` - llm_analytics
 * `sandbox` - sandbox
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
    resume_payload?: unknown | null
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
    readonly status?: ConversationStatusEnumApi
    /**
     * Title of the conversation.
     * @nullable
     */
    readonly title?: string | null
    readonly user?: UserBasicApi
    /** @nullable */
    readonly created_at?: string | null
    /** @nullable */
    readonly updated_at?: string | null
    readonly type?: ConversationTypeEnumApi
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
    readonly is_sandbox?: boolean
    /** Return pending approval cards as structured data.

Combines metadata from conversation.approval_decisions with payload from checkpoint
interrupts (single source of truth for payload data). */
    readonly pending_approvals?: readonly PatchedConversationApiPendingApprovalsItem[]
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

/**
 * * `widget` - Widget
 * `email` - Email
 * `slack` - Slack
 */
export type ChannelSourceEnumApi = (typeof ChannelSourceEnumApi)[keyof typeof ChannelSourceEnumApi]

export const ChannelSourceEnumApi = {
    Widget: 'widget',
    Email: 'email',
    Slack: 'slack',
} as const

/**
 * * `slack_channel_message` - Channel message
 * `slack_bot_mention` - Bot mention
 * `slack_emoji_reaction` - Emoji reaction
 * `widget_embedded` - Widget
 * `widget_api` - API
 */
export type ChannelDetailEnumApi = (typeof ChannelDetailEnumApi)[keyof typeof ChannelDetailEnumApi]

export const ChannelDetailEnumApi = {
    SlackChannelMessage: 'slack_channel_message',
    SlackBotMention: 'slack_bot_mention',
    SlackEmojiReaction: 'slack_emoji_reaction',
    WidgetEmbedded: 'widget_embedded',
    WidgetApi: 'widget_api',
} as const

/**
 * * `new` - New
 * `open` - Open
 * `pending` - Pending
 * `on_hold` - On hold
 * `resolved` - Resolved
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
 * `medium` - Medium
 * `high` - High
 */
export type PriorityEnumApi = (typeof PriorityEnumApi)[keyof typeof PriorityEnumApi]

export const PriorityEnumApi = {
    Low: 'low',
    Medium: 'medium',
    High: 'high',
} as const

/**
 * @nullable
 */
export type TicketAssignmentApiUser = { [key: string]: string } | null | null

/**
 * @nullable
 */
export type TicketAssignmentApiRole = { [key: string]: string } | null | null

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
    readonly channel_detail: ChannelDetailEnumApi | NullEnumApi | null
    readonly distinct_id: string
    status?: TicketStatusEnumApi
    priority?: PriorityEnumApi | BlankEnumApi | NullEnumApi | null
    readonly assignee: TicketAssignmentApi
    anonymous_traits?: unknown
    ai_resolved?: boolean
    /** @nullable */
    escalation_reason?: string | null
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
    /** @nullable */
    sla_due_at?: string | null
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
    readonly channel_detail?: ChannelDetailEnumApi | NullEnumApi | null
    readonly distinct_id?: string
    status?: TicketStatusEnumApi
    priority?: PriorityEnumApi | BlankEnumApi | NullEnumApi | null
    readonly assignee?: TicketAssignmentApi
    anonymous_traits?: unknown
    ai_resolved?: boolean
    /** @nullable */
    escalation_reason?: string | null
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
    /** @nullable */
    sla_due_at?: string | null
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
    readonly person?: TicketPersonApi | null
    tags?: unknown[]
}

export interface SuggestReplyResponseApi {
    suggestion: string
}

export interface SuggestReplyErrorApi {
    detail: string
    error_type?: string
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

export type ConversationsTicketsListParams = {
    /**
     * Number of results to return per page.
     */
    limit?: number
    /**
     * The initial index from which to return the results.
     */
    offset?: number
}
