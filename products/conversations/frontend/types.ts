import type { AccessControlLevel } from '~/types'

import { MAX_ASSIGNEE_FILTER_ENTRIES } from './components/Assignee'
import type { AssigneeFilterEntry, TicketAssignee } from './components/Assignee'
import type { AiTriageResultEnumApi, TicketViewFiltersApi } from './generated/api.schemas'

export type { AssigneeFilterEntry }

export type NotificationPermission = 'default' | 'granted' | 'denied'
export type TicketStatus = 'new' | 'open' | 'pending' | 'on_hold' | 'resolved'
export type TicketChannel = 'widget' | 'slack' | 'email' | 'teams' | 'github'
export type TicketChannelDetail =
    | 'slack_channel_message'
    | 'slack_bot_mention'
    | 'slack_emoji_reaction'
    | 'teams_channel_message'
    | 'teams_bot_mention'
    | 'widget_embedded'
    | 'widget_api'
    | 'github_issue'
export type TicketSlaState = 'on-track' | 'at-risk' | 'breached'
export type TicketPriority = 'low' | 'medium' | 'high' | 'critical'
export type SceneTabKey = 'tickets' | 'settings'
export type MessageAuthorType = 'customer' | 'AI' | 'human'
export type MessageDeliveryStatus = 'sent' | 'read'
export type SidePanelViewState = 'list' | 'ticket' | 'new' | 'restore'
export type RestoreFlowState = 'idle' | 'sending' | 'sent' | 'error'
/** Legacy single-value shape, still present in old saved views and persisted filter state. */
export type AssigneeFilterValue = 'all' | 'unassigned' | TicketAssignee

function isAssigneeFilterEntry(value: unknown): value is AssigneeFilterEntry {
    if (value === 'unassigned' || value === 'me') {
        return true
    }
    if (typeof value !== 'object' || value === null) {
        return false
    }
    const candidate = value as { type?: unknown; id?: unknown }
    return (
        (candidate.type === 'user' || candidate.type === 'role') &&
        (typeof candidate.id === 'string' || typeof candidate.id === 'number')
    )
}

export function normalizeAssigneeFilter(value: unknown): AssigneeFilterEntry[] {
    if (Array.isArray(value)) {
        return value.filter(isAssigneeFilterEntry).slice(0, MAX_ASSIGNEE_FILTER_ENTRIES)
    }
    return isAssigneeFilterEntry(value) ? [value] : []
}

export type TicketTagsMatch = 'any' | 'all'

export type AITriageStatus = 'in_progress' | 'done' | 'awaiting_clarification'
export type AITriageFilterValue = AiTriageResultEnumApi
export type AITriageResult = Exclude<AiTriageResultEnumApi, 'in_progress'>
export type AITriageVerdict = 'answerable' | 'blocked_on_customer' | 'blocked_on_knowledge' | 'out_of_scope'
export type AITriageBlocker = 'none' | 'customer_info' | 'knowledge' | 'contradiction'
export type AIPersistAs = 'reply' | 'findings' | 'clarification'

export interface AITriageSource {
    ref: string
    title: string
    source_id?: string | null
    url?: string | null
    is_generated?: boolean
    learned_from_ticket_number?: number | null
}

export interface AITriage {
    schema_version?: number
    status?: AITriageStatus
    result?: AITriageResult
    ticket_type?: 'how_to' | 'diagnostic' | 'account_billing' | 'bug' | 'unactionable'
    needs_diagnostics?: boolean
    diagnostics_allowed?: boolean
    confidence?: number
    attempts?: number
    started_at?: string
    finished_at?: string
    workflow_id?: string
    run_id?: string
    ai_trace_id?: string
    missing?: string[]
    verdict?: AITriageVerdict
    blocker?: AITriageBlocker
    unknowns?: string[]
    clarifying_questions?: string[]
    investigation_summary?: string
    citations?: string[]
    sources?: AITriageSource[]
    draft_confidence?: number
    validator_confidence?: number
    coverage?: number
    grounded?: boolean
    clarification_rounds?: number
    cost?: {
        sandbox_seconds?: number
        llm_calls?: number
    }
    human_outcome?: 'used' | 'edited' | 'ignored'
}

export type AiReplyFeedbackRating = 'good' | 'bad'

/**
 * Canonical saved-view filter shape, generated from the backend's TicketViewFiltersSerializer.
 * `assignee` is widened locally: the API stores filters raw, so old saved views can still
 * return the legacy single-value shape — always read it through normalizeAssigneeFilter.
 */
export type TicketViewFilters = Omit<TicketViewFiltersApi, 'assignee'> & {
    assignee?: AssigneeFilterEntry[] | AssigneeFilterValue
}

export interface SavedTicketView {
    id: string
    short_id: string
    name: string
    filters: TicketViewFilters
    created_at: string
    created_by: { id: number; first_name?: string; email?: string } | null
    is_favorited: boolean
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
    identity_verified: boolean | null
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
        replay_url?: string
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
    github_repo?: string | null
    github_issue_number?: number | null
    zendesk_ticket_id?: number | null
    organization_id?: string | null
    organization_id_source?: string | null
    person?: TicketPerson | null
    tags?: string[]
    ai_triage?: AITriage
    /** The effective access level the current user has for this ticket. */
    user_access_level?: AccessControlLevel
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
        replay_url?: string
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
    id?: number
    first_name?: string
    last_name?: string
    email?: string
}

/** Delivery state of an outbound email reply, denormalized from the backend outbox. */
export type EmailDeliveryStatus = 'sending' | 'sent' | 'failed'

export interface ChatMessage {
    id: string
    content: string
    richContent?: Record<string, unknown> | null
    authorType: MessageAuthorType
    authorName: string
    createdBy?: MessageAuthor | null
    createdAt: string
    isPrivate?: boolean
    /** Edit count from the comment row. 0 means never edited. */
    version?: number
    emailDeliveryStatus?: EmailDeliveryStatus
    /** Imported from an external tool (e.g. Zendesk). Such content is untrusted, so its Markdown
     * is rendered with external image auto-loading disabled. */
    fromZendesk?: boolean
    hasFullEmailContent?: boolean
    citations?: string[]
    confidence?: number
    persistAs?: AIPersistAs
    clarifyingQuestions?: string[]
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
    { value: 'critical', label: 'Critical' },
]

// Multiselect-compatible options for LemonInputSelect
export const priorityMultiselectOptions: { key: TicketPriority; label: string }[] = [
    { key: 'low', label: 'Low' },
    { key: 'medium', label: 'Medium' },
    { key: 'high', label: 'High' },
    { key: 'critical', label: 'Critical' },
]

export const channelOptions: { value: TicketChannel | 'all'; label: string }[] = [
    { value: 'all', label: 'All channels' },
    { value: 'widget', label: 'Widget' },
    { value: 'slack', label: 'Slack' },
    { value: 'teams', label: 'Microsoft Teams' },
    { value: 'email', label: 'Email' },
    { value: 'github', label: 'GitHub' },
]

export const slaOptions: { value: TicketSlaState | 'all'; label: string }[] = [
    { value: 'all', label: 'All SLA states' },
    { value: 'on-track', label: 'On track' },
    { value: 'at-risk', label: 'At risk' },
    { value: 'breached', label: 'Breached' },
]

export const aiTriageResultLabel: Record<AITriageResult, string> = {
    persisted: 'Resolved',
    suggested: 'Suggested reply',
    escalated_with_findings: 'Escalated with notes',
    escalated_with_best: 'Escalated with draft',
    escalated_no_reply: 'Escalated, no draft',
    skipped_unactionable: 'Skipped',
    blocked_unsafe: 'Blocked unsafe ticket',
    blocked_unsafe_reply: 'Blocked unsafe reply',
    clarified: 'Asked a question',
    suggested_clarification: 'Suggested a question',
}

export const aiTriageStatusLabel: Record<AITriageStatus, string> = {
    in_progress: 'In progress',
    done: 'Done',
    awaiting_clarification: 'Waiting for the customer',
}

export const aiTriageVerdictLabel: Record<AITriageVerdict, string> = {
    answerable: 'Answerable',
    blocked_on_customer: 'Needs customer info',
    blocked_on_knowledge: 'Needs knowledge',
    out_of_scope: 'Out of scope',
}

export const aiTriageBlockerLabel: Record<AITriageBlocker, string> = {
    none: 'None',
    customer_info: 'Customer info',
    knowledge: 'Knowledge',
    contradiction: 'Contradiction',
}

export const aiTriageProcessingLabel = 'Processing'

export const aiTriageFilterOptions: { key: AITriageFilterValue; label: string }[] = [
    { key: 'in_progress', label: aiTriageProcessingLabel },
    ...(Object.entries(aiTriageResultLabel) as [AITriageResult, string][]).map(([key, label]) => ({ key, label })),
]

export type AITriageTagType = 'success' | 'warning' | 'danger' | 'default'

const AI_TRIAGE_RESULT_TAG_TYPE: Record<AITriageResult, AITriageTagType> = {
    persisted: 'success',
    suggested: 'warning',
    escalated_with_findings: 'warning',
    escalated_with_best: 'warning',
    escalated_no_reply: 'warning',
    skipped_unactionable: 'default',
    blocked_unsafe: 'danger',
    blocked_unsafe_reply: 'danger',
    clarified: 'warning',
    suggested_clarification: 'warning',
}

export function aiTriageResultTagType(result: AITriageResult): AITriageTagType {
    return AI_TRIAGE_RESULT_TAG_TYPE[result]
}

export type TicketListAiTriage =
    | { kind: 'empty' }
    | { kind: 'processing' }
    | { kind: 'tag'; label: string; tagType: AITriageTagType }

export function ticketListAiTriage(triage: AITriage | undefined): TicketListAiTriage {
    if (!triage?.status) {
        return { kind: 'empty' }
    }
    if (triage.status === 'in_progress') {
        return { kind: 'processing' }
    }
    if (triage.status === 'awaiting_clarification') {
        return { kind: 'tag', label: aiTriageStatusLabel.awaiting_clarification, tagType: 'warning' }
    }
    if (triage.result) {
        return {
            kind: 'tag',
            label: aiTriageResultLabel[triage.result],
            tagType: aiTriageResultTagType(triage.result),
        }
    }
    return { kind: 'empty' }
}

export const aiTriageTicketTypeLabel: Record<string, string> = {
    how_to: 'How-to',
    diagnostic: 'Diagnostic',
    account_billing: 'Account/Billing',
    unactionable: 'Unactionable',
}

export const aiTriageTicketTypeDescription: Record<string, string> = {
    how_to: 'Customer needs guidance on how to use a feature or accomplish a task',
    diagnostic: 'Customer is experiencing a bug or issue that requires investigation',
    account_billing: 'Related to account settings, billing, or subscription management',
    unactionable: 'Ticket cannot be resolved by AI (e.g. feedback, spam, or out of scope)',
}
