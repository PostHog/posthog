import type { TicketAssignee } from './components/Assignee'

export type TicketStatus = 'new' | 'open' | 'pending' | 'on_hold' | 'resolved'
export type TicketChannel = 'widget' | 'slack' | 'email'
export type TicketSlaState = 'on-track' | 'at-risk' | 'breached'
export type TicketPriority = 'low' | 'medium' | 'high'
export type SceneTabKey = 'tickets' | 'settings'
export type MessageAuthorType = 'customer' | 'AI' | 'human'
export type SidePanelViewState = 'list' | 'ticket' | 'new'
export type AssigneeFilterValue = 'all' | 'unassigned' | TicketAssignee

export interface UserBasic {
    id: number
    uuid: string
    distinct_id: string
    first_name: string
    last_name: string
    email: string
    is_email_verified: boolean
}

export interface Ticket {
    id: string
    ticket_number: number
    distinct_id: string
    status: TicketStatus
    priority?: TicketPriority
    assignee?: TicketAssignee
    channel_source: TicketChannel
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
    authorType: MessageAuthorType
    authorName: string
    createdBy?: MessageAuthor | null
    createdAt: string
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

export const priorityOptions: { value: TicketPriority; label: string }[] = [
    { value: 'low', label: 'Low' },
    { value: 'medium', label: 'Medium' },
    { value: 'high', label: 'High' },
]

export const channelOptions: { value: TicketChannel | 'all'; label: string }[] = [
    { value: 'all', label: 'All channels' },
    { value: 'widget', label: 'Widget' },
    { value: 'slack', label: 'Slack' },
    { value: 'email', label: 'Email' },
]

export const slaOptions: { value: TicketSlaState | 'all'; label: string }[] = [
    { value: 'all', label: 'All SLA states' },
    { value: 'on-track', label: 'On track' },
    { value: 'at-risk', label: 'At risk' },
    { value: 'breached', label: 'Breached' },
]
