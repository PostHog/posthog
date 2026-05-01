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
export type ConversationStatusApi = (typeof ConversationStatusApi)[keyof typeof ConversationStatusApi]

export const ConversationStatusApi = {
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
export type ConversationTypeApi = (typeof ConversationTypeApi)[keyof typeof ConversationTypeApi]

export const ConversationTypeApi = {
    Assistant: 'assistant',
    ToolCall: 'tool_call',
    DeepResearch: 'deep_research',
    Slack: 'slack',
} as const

export interface ConversationMinimalApi {
    readonly id: string
    readonly status: ConversationStatusApi
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

export type ConversationApiMessagesItem = { [key: string]: unknown }

export type ConversationApiPendingApprovalsItem = { [key: string]: unknown }

export interface ConversationApi {
    readonly id: string
    readonly status: ConversationStatusApi
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
    readonly is_sandbox: boolean
    /** Return pending approval cards as structured data.

Combines metadata from conversation.approval_decisions with payload from checkpoint
interrupts (single source of truth for payload data). */
    readonly pending_approvals: readonly ConversationApiPendingApprovalsItem[]
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
 * `teams` - Microsoft Teams
 */
export type ChannelSourceEnumApi = (typeof ChannelSourceEnumApi)[keyof typeof ChannelSourceEnumApi]

export const ChannelSourceEnumApi = {
    Widget: 'widget',
    Email: 'email',
    Slack: 'slack',
    Teams: 'teams',
} as const

/**
 * * `slack_channel_message` - Channel message
 * `slack_bot_mention` - Bot mention
 * `slack_emoji_reaction` - Emoji reaction
 * `teams_channel_message` - Teams channel message
 * `teams_bot_mention` - Teams bot mention
 * `widget_embedded` - Widget
 * `widget_api` - API
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
    /** Ticket status: new, open, pending, on_hold, or resolved

* `new` - New
* `open` - Open
* `pending` - Pending
* `on_hold` - On hold
* `resolved` - Resolved */
    status?: TicketStatusEnumApi
    /** Ticket priority: low, medium, or high. Null if unset.

* `low` - Low
* `medium` - Medium
* `high` - High */
    priority?: PriorityEnumApi | BlankEnumApi | NullEnumApi | null
    readonly assignee: TicketAssignmentApi
    /** Customer-provided traits such as name and email */
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
    /** Ticket status: new, open, pending, on_hold, or resolved

* `new` - New
* `open` - Open
* `pending` - Pending
* `on_hold` - On hold
* `resolved` - Resolved */
    status?: TicketStatusEnumApi
    /** Ticket priority: low, medium, or high. Null if unset.

* `low` - Low
* `medium` - Medium
* `high` - High */
    priority?: PriorityEnumApi | BlankEnumApi | NullEnumApi | null
    readonly assignee?: TicketAssignmentApi
    /** Customer-provided traits such as name and email */
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

/**
 * * `add` - add
 * `remove` - remove
 * `set` - set
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

* `add` - add
* `remove` - remove
* `set` - set */
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
     * JSON-encoded array of tag names to filter by, e.g. `["billing","urgent"]`.
     */
    tags?: string
}

export type ConversationsTicketsListChannelDetail =
    (typeof ConversationsTicketsListChannelDetail)[keyof typeof ConversationsTicketsListChannelDetail]

export const ConversationsTicketsListChannelDetail = {
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
