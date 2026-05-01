import type { Sorting } from 'lib/lemon-ui/LemonTable/sorting'

import type { TicketAssignee } from './components/Assignee'

export type NotificationPermission = 'default' | 'granted' | 'denied'
export type TicketStatus = 'new' | 'open' | 'pending' | 'on_hold' | 'resolved'
export type TicketChannel = 'widget' | 'slack' | 'email' | 'teams'
export type TicketChannelDetail =
    | 'slack_channel_message'
    | 'slack_bot_mention'
    | 'slack_emoji_reaction'
    | 'teams_channel_message'
    | 'teams_bot_mention'
    | 'widget_embedded'
    | 'widget_api'
export type TicketSlaState = 'on-track' | 'at-risk' | 'breached'
export type TicketPriority = 'low' | 'medium' | 'high'
export type SceneTabKey = 'tickets' | 'settings'
export type MessageAuthorType = 'customer' | 'AI' | 'human'
export type MessageDeliveryStatus = 'sent' | 'read'
export type SidePanelViewState = 'list' | 'ticket' | 'new' | 'restore'
export type RestoreFlowState = 'idle' | 'sending' | 'sent' | 'error'
export type AssigneeFilterValue = 'all' | 'unassigned' | TicketAssignee

export interface TicketViewFilters {
    status?: TicketStatus[]
    priority?: TicketPriority[]
    channel?: TicketChannel | 'all'
    sla?: TicketSlaState | 'all'
    assignee?: AssigneeFilterValue
    tags?: string[]
    dateFrom?: string | null
    dateTo?: string | null
    sorting?: Sorting | null
    search?: string
}

export interface SavedTicketView {
    id: string
    short_id: string
    name: string
    filters: TicketViewFilters
    created_at: string
    created_by: { id: number; first_name?: string; email?: string } | null
}

export interface UserBasic {
    id: number
    uuid: string
    distinct_id: string
    first_name: string
    last_name: string
    email: string
    is_email_verified: boolean
}

export interface TicketPerson {
    id: string
    name: string
    distinct_ids: string[]
    properties: Record<string, any>
    created_at?: string
    is_identified?: boolean
}

export interface Ticket {
    id: string
    ticket_number: number
    distinct_id: string
    status: TicketStatus
    priority?: TicketPriority
    assignee?: TicketAssignee
    channel_source: TicketChannel
    channel_detail?: TicketChannelDetail | null
    anonymous_traits: Record<string, any>
    ai_resolved: boolean
    escalation_reason?: string
    created_at: string
    updated_at: string
    message_count: number
    last_message_at: string | null
    last_message_text: string | null
    unread_team_count: number
    unread_customer_count: number
    session_id?: string
    session_context?: {
        session_replay_url?: string
        current_url?: string
        [key: string]: any
    }
    sla_due_at?: string | null
    snoozed_until?: string | null
    slack_channel_id?: string | null
    slack_thread_ts?: string | null
    slack_team_id?: string | null
    email_subject?: string | null
    email_from?: string | null
    email_to?: string | null
    cc_participants?: string[]
    person?: TicketPerson | null
    tags?: string[]
}

export interface ConversationTicket {
    id: string
    ticket_number?: number
    status: TicketStatus
    last_message?: string
    last_message_at?: string
    message_count: number
    created_at: string
    unread_count?: number
    session_id?: string
    session_context?: {
        session_replay_url?: string
        current_url?: string
        [key: string]: any
    }
}

export interface ConversationMessage {
    id: string
    content: string
    rich_content?: Record<string, unknown> | null
    author_type: MessageAuthorType
    author_name?: string
    created_at: string
    is_private: boolean
}

export interface MessageAuthor {
    first_name?: string
    last_name?: string
    email?: string
}

export interface ChatMessage {
    id: string
    content: string
    richContent?: Record<string, unknown> | null
    authorType: MessageAuthorType
    authorName: string
    createdBy?: MessageAuthor | null
    createdAt: string
    isPrivate?: boolean
}

export const statusOptions: { value: TicketStatus | 'all'; label: string }[] = [
    { value: 'all', label: 'All statuses' },
    { value: 'new', label: 'New' },
    { value: 'open', label: 'Open' },
    { value: 'pending', label: 'Pending' },
    { value: 'on_hold', label: 'On hold' },
    { value: 'resolved', label: 'Resolved' },
]

export const statusOptionsWithoutAll: { value: TicketStatus; label: string }[] = [
    { value: 'new', label: 'New' },
    { value: 'open', label: 'Open' },
    { value: 'pending', label: 'Pending' },
    { value: 'on_hold', label: 'On hold' },
    { value: 'resolved', label: 'Resolved' },
]

// Multiselect-compatible options for LemonInputSelect
export const statusMultiselectOptions: { key: TicketStatus; label: string }[] = [
    { key: 'new', label: 'New' },
    { key: 'open', label: 'Open' },
    { key: 'pending', label: 'Pending' },
    { key: 'on_hold', label: 'On hold' },
    { key: 'resolved', label: 'Resolved' },
]

export const priorityOptions: { value: TicketPriority; label: string }[] = [
    { value: 'low', label: 'Low' },
    { value: 'medium', label: 'Medium' },
    { value: 'high', label: 'High' },
]

// Multiselect-compatible options for LemonInputSelect
export const priorityMultiselectOptions: { key: TicketPriority; label: string }[] = [
    { key: 'low', label: 'Low' },
    { key: 'medium', label: 'Medium' },
    { key: 'high', label: 'High' },
]

export const channelOptions: { value: TicketChannel | 'all'; label: string }[] = [
    { value: 'all', label: 'All channels' },
    { value: 'widget', label: 'Widget' },
    { value: 'slack', label: 'Slack' },
    { value: 'teams', label: 'Microsoft Teams' },
    { value: 'email', label: 'Email' },
]

export const slaOptions: { value: TicketSlaState | 'all'; label: string }[] = [
    { value: 'all', label: 'All SLA states' },
    { value: 'on-track', label: 'On track' },
    { value: 'at-risk', label: 'At risk' },
    { value: 'breached', label: 'Breached' },
]
