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
 * * `widget` - Widget
 * * `email` - Email
 * * `slack` - Slack
 * * `teams` - Microsoft Teams
 * * `github` - GitHub
 */
export type ChannelEnumApi = (typeof ChannelEnumApi)[keyof typeof ChannelEnumApi]

export const ChannelEnumApi = {
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
 * * `critical` - Critical
 */
export type TicketPriorityEnumApi = (typeof TicketPriorityEnumApi)[keyof typeof TicketPriorityEnumApi]

export const TicketPriorityEnumApi = {
    Low: 'low',
    Medium: 'medium',
    High: 'high',
    Critical: 'critical',
} as const

export type BlankEnumApi = (typeof BlankEnumApi)[keyof typeof BlankEnumApi]

export const BlankEnumApi = {
    '': '',
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
 * Mixin for serializers to add user access control fields
 */
export interface TicketApi {
    readonly id: string
    readonly ticket_number: number
    readonly channel_source: ChannelEnumApi
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
    /** Ticket priority: low, medium, high, or critical. Null if unset.
     *
     * * `low` - Low
     * * `medium` - Medium
     * * `high` - High
     * * `critical` - Critical */
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
    /**
     * How organization_id was resolved: 'person' (from the requester's identity) or 'slack_channel_account' (inferred from the customer analytics account linked to the ticket's Slack channel). Null when organization_id is unset.
     * @nullable
     */
    readonly organization_id_source: string | null
    readonly person: TicketPersonApi | null
    tags?: unknown[]
    /**
     * The effective access level the user has for this object
     * @nullable
     */
    readonly user_access_level: string | null
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
 * Assign the ticket to a user.
 */
export type UserTicketAssigneeRequestApiType =
    (typeof UserTicketAssigneeRequestApiType)[keyof typeof UserTicketAssigneeRequestApiType]

export const UserTicketAssigneeRequestApiType = {
    User: 'user',
} as const

export interface UserTicketAssigneeRequestApi {
    /** Assign the ticket to a user. */
    type: UserTicketAssigneeRequestApiType
    /** User ID. */
    id: number
}

/**
 * Assign the ticket to a role.
 */
export type RoleTicketAssigneeRequestApiType =
    (typeof RoleTicketAssigneeRequestApiType)[keyof typeof RoleTicketAssigneeRequestApiType]

export const RoleTicketAssigneeRequestApiType = {
    Role: 'role',
} as const

export interface RoleTicketAssigneeRequestApi {
    /** Assign the ticket to a role. */
    type: RoleTicketAssigneeRequestApiType
    /** Role ID. */
    id: string
}

export type TicketAssigneeRequestApi = UserTicketAssigneeRequestApi | RoleTicketAssigneeRequestApi

/**
 * Fields accepted when updating a ticket.
 */
export interface TicketUpdateRequestApi {
    /** Ticket status: new, open, pending, on_hold, or resolved.
     *
     * * `new` - New
     * * `open` - Open
     * * `pending` - Pending
     * * `on_hold` - On hold
     * * `resolved` - Resolved */
    status?: TicketStatusEnumApi
    /** Ticket priority: low, medium, high, or critical. Pass null to clear it.
     *
     * * `low` - Low
     * * `medium` - Medium
     * * `high` - High
     * * `critical` - Critical */
    priority?: TicketPriorityEnumApi | BlankEnumApi | null
    /** User or role to assign. Pass null to remove the current assignee. */
    assignee?: TicketAssigneeRequestApi | null
    /** Customer details such as name and email. */
    anonymous_traits?: unknown
    /** Whether AI resolved the ticket. */
    ai_resolved?: boolean
    /**
     * Reason the ticket was escalated. Pass null to clear it.
     * @nullable
     */
    escalation_reason?: string | null
    /**
     * SLA deadline. Pass null to clear it.
     * @nullable
     */
    sla_due_at?: string | null
    /**
     * Time to reopen the ticket. Pass null to reopen it now.
     * @nullable
     */
    snoozed_until?: string | null
    /** Tag names to set on the ticket. */
    tags?: string[]
}

/**
 * Fields accepted when updating a ticket.
 */
export interface PatchedTicketUpdateRequestApi {
    /** Ticket status: new, open, pending, on_hold, or resolved.
     *
     * * `new` - New
     * * `open` - Open
     * * `pending` - Pending
     * * `on_hold` - On hold
     * * `resolved` - Resolved */
    status?: TicketStatusEnumApi
    /** Ticket priority: low, medium, high, or critical. Pass null to clear it.
     *
     * * `low` - Low
     * * `medium` - Medium
     * * `high` - High
     * * `critical` - Critical */
    priority?: TicketPriorityEnumApi | BlankEnumApi | null
    /** User or role to assign. Pass null to remove the current assignee. */
    assignee?: TicketAssigneeRequestApi | null
    /** Customer details such as name and email. */
    anonymous_traits?: unknown
    /** Whether AI resolved the ticket. */
    ai_resolved?: boolean
    /**
     * Reason the ticket was escalated. Pass null to clear it.
     * @nullable
     */
    escalation_reason?: string | null
    /**
     * SLA deadline. Pass null to clear it.
     * @nullable
     */
    sla_due_at?: string | null
    /**
     * Time to reopen the ticket. Pass null to reopen it now.
     * @nullable
     */
    snoozed_until?: string | null
    /** Tag names to set on the ticket. */
    tags?: string[]
}

/**
 * * `good` - good
 * * `bad` - bad
 */
export type RatingEnumApi = (typeof RatingEnumApi)[keyof typeof RatingEnumApi]

export const RatingEnumApi = {
    Good: 'good',
    Bad: 'bad',
} as const

/**
 * Payload for recording reviewer feedback on an AI reply.
 */
export interface AiFeedbackRequestApi {
    /**
     * ID of the AI message being rated.
     * @maxLength 200
     */
    message_id: string
    /** Reviewer rating: good or bad.
     *
     * * `good` - good
     * * `bad` - bad */
    rating: RatingEnumApi
    /**
     * Optional text explaining a bad rating.
     * @maxLength 2000
     */
    feedback_text?: string
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
    /** Edit count. 0 means never edited. */
    readonly version: number
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
 * Payload for updating a private note on a ticket.
 */
export interface PatchedTicketNoteUpdateRequestApi {
    /**
     * Updated note content in markdown.
     * @maxLength 5000
     */
    message?: string
    /** Optional TipTap rich content JSON. Omit or pass null to clear previous rich content so the thread falls back to the markdown message. */
    rich_content?: unknown
}

export interface TicketErrorApi {
    detail: string
    error_type?: string
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
export type BulkUpdateTagsActionEnumApi = (typeof BulkUpdateTagsActionEnumApi)[keyof typeof BulkUpdateTagsActionEnumApi]

export const BulkUpdateTagsActionEnumApi = {
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
    action: BulkUpdateTagsActionEnumApi
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
    /**
     * Tags to apply to the new ticket, e.g. to mark its source. Each is normalized (lowercased, trimmed). Up to 100.
     * @maxItems 100
     * @items.maxLength 255
     */
    tags?: string[]
}

export interface ComposeTicketResponseApi {
    /** Created ticket UUID. */
    id: string
    /** Human-readable ticket number. */
    ticket_number: number
}

/**
 * * `widget` - widget
 * * `email` - email
 * * `slack` - slack
 * * `teams` - teams
 * * `github` - github
 * * `all` - all
 */
export type TicketChannelFilterEnumApi = (typeof TicketChannelFilterEnumApi)[keyof typeof TicketChannelFilterEnumApi]

export const TicketChannelFilterEnumApi = {
    Widget: 'widget',
    Email: 'email',
    Slack: 'slack',
    Teams: 'teams',
    Github: 'github',
    All: 'all',
} as const

/**
 * * `breached` - breached
 * * `at-risk` - at-risk
 * * `on-track` - on-track
 * * `all` - all
 */
export type TicketSlaFilterEnumApi = (typeof TicketSlaFilterEnumApi)[keyof typeof TicketSlaFilterEnumApi]

export const TicketSlaFilterEnumApi = {
    Breached: 'breached',
    AtRisk: 'at-risk',
    OnTrack: 'on-track',
    All: 'all',
} as const

/**
 * * `persisted` - persisted
 * * `escalated_with_best` - escalated_with_best
 * * `escalated_no_reply` - escalated_no_reply
 * * `skipped_unactionable` - skipped_unactionable
 * * `blocked_unsafe` - blocked_unsafe
 * * `blocked_unsafe_reply` - blocked_unsafe_reply
 * * `in_progress` - in_progress
 */
export type AiTriageResultEnumApi = (typeof AiTriageResultEnumApi)[keyof typeof AiTriageResultEnumApi]

export const AiTriageResultEnumApi = {
    Persisted: 'persisted',
    EscalatedWithBest: 'escalated_with_best',
    EscalatedNoReply: 'escalated_no_reply',
    SkippedUnactionable: 'skipped_unactionable',
    BlockedUnsafe: 'blocked_unsafe',
    BlockedUnsafeReply: 'blocked_unsafe_reply',
    InProgress: 'in_progress',
} as const

/**
 * * `any` - any
 * * `all` - all
 */
export type TicketTagsMatchEnumApi = (typeof TicketTagsMatchEnumApi)[keyof typeof TicketTagsMatchEnumApi]

export const TicketTagsMatchEnumApi = {
    Any: 'any',
    All: 'all',
} as const

/**
 * * `1` - 1
 * * `-1` - -1
 */
export type TicketSortOrderEnumApi = (typeof TicketSortOrderEnumApi)[keyof typeof TicketSortOrderEnumApi]

export const TicketSortOrderEnumApi = {
    Number1: 1,
    NumberMinus1: -1,
} as const

export interface TicketViewSortingApi {
    /** Ticket column to sort by (updated_at, sla_due_at, snoozed_until, created_at, ticket_number). Unknown columns fall back to updated_at. */
    columnKey: string
    /** 1 for ascending, -1 for descending.
     *
     * * `1` - 1
     * * `-1` - -1 */
    order: TicketSortOrderEnumApi
}

export type TicketViewFiltersApiAssigneeItem =
    | 'me'
    | 'unassigned'
    | {
          type: 'user' | 'role'
          id: string | number
      }

/**
 * Canonical shape of a saved ticket view's filters. Every field is optional; an omitted
 * field (or an 'all' sentinel) leaves that dimension unfiltered.
 */
export interface TicketViewFiltersApi {
    /** Ticket statuses to include. Empty or omitted means all statuses. */
    status?: TicketStatusEnumApi[]
    /** Ticket priorities to include. Empty or omitted means all priorities. */
    priority?: TicketPriorityEnumApi[]
    /** Channel the ticket originated from. 'all' disables the filter.
     *
     * * `widget` - widget
     * * `email` - email
     * * `slack` - slack
     * * `teams` - teams
     * * `github` - github
     * * `all` - all */
    channel?: TicketChannelFilterEnumApi
    /** SLA state: 'breached' is past due, 'at-risk' is due within the next hour, 'on-track' has more than an hour remaining. 'all' disables the filter.
     *
     * * `breached` - breached
     * * `at-risk` - at-risk
     * * `on-track` - on-track
     * * `all` - all */
    sla?: TicketSlaFilterEnumApi
    /** AI triage outcomes to include. 'in_progress' matches tickets still being triaged. */
    aiTriageResult?: AiTriageResultEnumApi[]
    /** Assignees to match (any of): 'unassigned', 'me' (resolved to the requesting user), or an object with type ('user' or 'role') and id. The legacy single-value shape is accepted and normalized to a list. */
    assignee?: TicketViewFiltersApiAssigneeItem[]
    /** Tag names to match, combined according to tagsMatch. */
    tags?: string[]
    /** 'any' returns tickets with at least one of tags (OR); 'all' requires every tag (AND).
     *
     * * `any` - any
     * * `all` - all */
    tagsMatch?: TicketTagsMatchEnumApi
    /** Tickets carrying any of these tags are excluded. */
    tagsExclude?: string[]
    /**
     * Only include tickets updated on or after this date. Accepts absolute dates (2026-01-01) or relative ones (-7d). 'all' or null disables the bound.
     * @nullable
     */
    dateFrom?: string | null
    /**
     * Only include tickets updated on or before this date. Same format as dateFrom.
     * @nullable
     */
    dateTo?: string | null
    /** Sort order for the ticket list. */
    sorting?: TicketViewSortingApi | null
    /**
     * Free-text search. A numeric value matches a ticket number exactly; otherwise matches the customer's name or email, the email subject, or message content.
     * @maxLength 200
     */
    search?: string
}

/**
 * * `engineering` - Engineering
 * * `data` - Data
 * * `product` - Product Management
 * * `founder` - Founder
 * * `leadership` - Leadership
 * * `marketing` - Marketing
 * * `sales` - Sales / Success
 * * `student` - Student
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
    Student: 'student',
    Other: 'other',
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

export interface TicketViewApi {
    readonly id: string
    readonly short_id: string
    /** @maxLength 400 */
    name: string
    /** Saved ticket filter criteria: status, priority, channel, sla, aiTriageResult, assignee, tags, tagsMatch, tagsExclude, dateFrom, dateTo, sorting, and search. */
    filters?: TicketViewFiltersApi
    readonly created_at: string
    readonly created_by: UserBasicApi
    /** Whether the current user has favorited this view. Favorited views sort to the top of the list. Favorites are personal to each user. */
    is_favorited?: boolean
}

export interface PaginatedTicketViewListApi {
    count: number
    /** @nullable */
    next?: string | null
    /** @nullable */
    previous?: string | null
    results: TicketViewApi[]
}

export interface PatchedTicketViewApi {
    readonly id?: string
    readonly short_id?: string
    /** @maxLength 400 */
    name?: string
    /** Saved ticket filter criteria: status, priority, channel, sla, aiTriageResult, assignee, tags, tagsMatch, tagsExclude, dateFrom, dateTo, sorting, and search. */
    filters?: TicketViewFiltersApi
    readonly created_at?: string
    readonly created_by?: UserBasicApi
    /** Whether the current user has favorited this view. Favorited views sort to the top of the list. Favorites are personal to each user. */
    is_favorited?: boolean
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

export type ConversationsTicketsListParams = {
    /**
     * Filter by AI triage outcome. Accepts a single value or a comma-separated list. Valid values: `persisted`, `escalated_with_best`, `escalated_no_reply`, `skipped_unactionable`, `blocked_unsafe`, `blocked_unsafe_reply`, `in_progress`.
     */
    ai_triage_result?: string
    /**
     * Filter by assignee. Accepts a single value or a comma-separated list (matches any, max 100 entries). Each entry is `unassigned` (no assignee), `me` (the requesting user), `user:<user_id>`, or `role:<role_uuid>`, e.g. `assignee=unassigned,user:123`.
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
     * Comma-separated list of email addresses to filter by, matched case-insensitively against `email_from` (max 100). When combined with `distinct_ids`, tickets matching either the distinct_ids or the emails are returned (OR).
     */
    emails?: string
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
     * Filter by priority. Accepts a single value or a comma-separated list (e.g. `medium,high`). Valid values: `low`, `medium`, `high`, `critical`.
     */
    priority?: string
    /**
     * Free-text search. A numeric value (optionally prefixed with `#`) matches a ticket number exactly; otherwise matches against the customer's name or email, the email subject, or message content (case-insensitive, partial match).
     */
    search?: string
    /**
     * Filter by SLA state. `breached` = past `sla_due_at`, `at-risk` = due within the next hour, `on-track` = more than an hour remaining.
     */
    sla?: ConversationsTicketsListSla
    /**
     * Filter by snooze state: `true` returns only snoozed tickets, `false` only non-snoozed.
     */
    snoozed?: boolean
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
    /**
     * Apply a saved ticket view's filters by its `short_id` (list views via the `conversations/views` endpoint). Any filter param passed explicitly overrides the view's saved value for that dimension. Returns 400 if no view matches.
     */
    view?: string
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
