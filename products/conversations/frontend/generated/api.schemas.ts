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
    idle: 'idle',
    in_progress: 'in_progress',
    canceling: 'canceling',
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
    engineering: 'engineering',
    data: 'data',
    product: 'product',
    founder: 'founder',
    leadership: 'leadership',
    marketing: 'marketing',
    sales: 'sales',
    other: 'other',
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
    assistant: 'assistant',
    tool_call: 'tool_call',
    deep_research: 'deep_research',
    slack: 'slack',
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
 */
export type AgentModeEnumApi = (typeof AgentModeEnumApi)[keyof typeof AgentModeEnumApi]

export const AgentModeEnumApi = {
    product_analytics: 'product_analytics',
    sql: 'sql',
    session_replay: 'session_replay',
    error_tracking: 'error_tracking',
    plan: 'plan',
    execution: 'execution',
    survey: 'survey',
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
    deep_research_mode?: boolean
    agent_mode?: AgentModeEnumApi
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
    /** Return pending approval cards as structured data.

Combines metadata from conversation.approval_decisions with payload from checkpoint
interrupts (single source of truth for payload data). */
    readonly pending_approvals?: readonly PatchedConversationApiPendingApprovalsItem[]
}

/**
 * * `widget` - Widget
 * `email` - Email
 * `slack` - Slack
 */
export type ChannelSourceEnumApi = (typeof ChannelSourceEnumApi)[keyof typeof ChannelSourceEnumApi]

export const ChannelSourceEnumApi = {
    widget: 'widget',
    email: 'email',
    slack: 'slack',
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
    new: 'new',
    open: 'open',
    pending: 'pending',
    on_hold: 'on_hold',
    resolved: 'resolved',
} as const

/**
 * * `low` - Low
 * `medium` - Medium
 * `high` - High
 */
export type PriorityEnumApi = (typeof PriorityEnumApi)[keyof typeof PriorityEnumApi]

export const PriorityEnumApi = {
    low: 'low',
    medium: 'medium',
    high: 'high',
} as const

/**
 * Serializer for ticket assignment (user or role).
 */
export interface TicketAssignmentApi {
    readonly id: string
    readonly type: string
}

export interface TicketApi {
    readonly id: string
    readonly ticket_number: number
    readonly channel_source: ChannelSourceEnumApi
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
    /** @nullable */
    readonly session_id: string | null
    readonly session_context: unknown
}

export interface PaginatedTicketListApi {
    count: number
    /** @nullable */
    next?: string | null
    /** @nullable */
    previous?: string | null
    results: TicketApi[]
}

export interface PatchedTicketApi {
    readonly id?: string
    readonly ticket_number?: number
    readonly channel_source?: ChannelSourceEnumApi
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
    /** @nullable */
    readonly session_id?: string | null
    readonly session_context?: unknown
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
     * Number of results to return per page.
     */
    limit?: number
    /**
     * The initial index from which to return the results.
     */
    offset?: number
}
