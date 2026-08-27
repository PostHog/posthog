import { JSONContent } from '@tiptap/core'
import {
    MakeLogicType,
    actions,
    afterMount,
    beforeUnmount,
    connect,
    kea,
    key,
    listeners,
    path,
    props,
    reducers,
    selectors,
} from 'kea'
import { loaders } from 'kea-loaders'
import { beforeUnload, router } from 'kea-router'
import posthog from 'posthog-js'

import { lemonToast } from '@posthog/lemon-ui'

import { FEATURE_FLAGS } from 'lib/constants'
import { dayjs } from 'lib/dayjs'
import { LemonDialog } from 'lib/lemon-ui/LemonDialog'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { getCurrentTeamId } from 'lib/utils/getAppContext'
import { isUUIDLike } from 'lib/utils/guards'
import { markdownToHtml } from 'lib/utils/markdown'
import { objectsEqual } from 'lib/utils/objects'
import { fullName } from 'lib/utils/strings'
import { commentsLogic } from 'scenes/comments/commentsLogic'
import { teamLogic } from 'scenes/teamLogic'
import { urls } from 'scenes/urls'
import { userLogic } from 'scenes/userLogic'

import { SIDE_PANEL_CONTEXT_KEY, SidePanelSceneContext } from '~/layout/navigation-3000/sidepanel/types'
import { impersonationNoticeLogic } from '~/layout/navigation/ImpersonationNotice/impersonationNoticeLogic'
import api from '~/lib/api'
import { PERSON_DISPLAY_NAME_COLUMN_NAME } from '~/lib/constants'
import { CLOUD_HOSTNAMES } from '~/lib/constants'
import { tagsModel } from '~/models/tagsModel'
import { defaultDataTableColumns } from '~/queries/nodes/DataTable/utils'
import { DataTableNode, NodeKind } from '~/queries/schema/schema-general'
import type { Breadcrumb, CommentType, PersonType, UserType } from '~/types'
import { ActivityScope, PropertyFilterType, PropertyOperator, Region } from '~/types'

import {
    businessKnowledgeGapSuggestionsDismissCreate,
    businessKnowledgeGapSuggestionsList,
} from 'products/business_knowledge/frontend/generated/api'
import {
    conversationsTicketsNotesDestroy,
    conversationsTicketsNotesPartialUpdate,
    conversationsTicketsPartialUpdate,
} from 'products/conversations/frontend/generated/api'
import type { PatchedTicketUpdateRequestApi } from 'products/conversations/frontend/generated/api.schemas'
import { getCommentsCreateUrl } from 'products/platform_features/frontend/generated/api'
import { signalsReportsList } from 'products/signals/frontend/generated/api'
import type { SignalReportApi } from 'products/signals/frontend/generated/api.schemas'
import { SignalSourceProductApi } from 'products/signals/frontend/generated/api.schemas'

import type { FeatureFlagsSet } from '../../../../../frontend/src/lib/logic/featureFlagLogic'
import type { TeamPublicType, TeamType } from '../../../../../frontend/src/types'
import { assigneeSelectLogic } from '../../components/Assignee'
import type { Assignee, TicketAssignee } from '../../components/Assignee'
import { supportTicketCounterLogic } from '../../supportTicketCounterLogic'
import { priorityOptions } from '../../types'
import type {
    AiReplyFeedbackRating,
    ChatMessage,
    KnowledgeGapSuggestion,
    Ticket,
    TicketPriority,
    TicketStatus,
} from '../../types'
import { conversationsDraftModeLogic } from '../settings/conversationsDraftModeLogic'
import { supportTicketsSceneLogic } from '../tickets/supportTicketsSceneLogic'

const MESSAGE_POLL_INTERVAL = 5000 // 5 seconds
/** Discussions ride the message timer at 1/4 the rate, so ~20s. */
const DISCUSSION_POLL_EVERY_N_TICKS = 4
/** Must not exceed the server's replay window, or recovery could adopt a message from an older send. */
const SEND_RECOVERY_WINDOW_SECONDS = 120

/**
 * How a failed send request should be treated. `null` means the send definitely did not happen:
 * the server rejected the request before writing anything, so the draft is safe to keep and resend.
 * Every other value means we don't know, and have to look at the thread before telling the operator.
 */
type UnconfirmedSendReason = 'network' | 'timeout' | 'in_progress' | 'server_error' | null

function classifySendFailure(error: any): UnconfirmedSendReason {
    const status = error?.status
    if (typeof status !== 'number') {
        // No response reached us, so the request may still have been processed.
        return 'network'
    }
    if (status === 408) {
        return 'timeout'
    }
    if (status === 409) {
        // The dedupe guard is still creating an identical message from an earlier attempt.
        return 'in_progress'
    }
    if (status >= 500) {
        return 'server_error'
    }
    // Includes 429: throttling rejects before the request body is handled, so nothing was written.
    return null
}

function regionFromUrl(url?: string): Region | undefined {
    if (url) {
        try {
            const hostname = new URL(url).hostname
            for (const [region, domain] of Object.entries(CLOUD_HOSTNAMES)) {
                if (hostname === domain || hostname.endsWith(`.${domain}`)) {
                    return region as Region
                }
            }
        } catch {
            // ignore malformed URLs
        }
    }
    return undefined
}

function createEventsQuery(personId: string, sessionId?: string, ticketCreatedAt?: string): DataTableNode {
    // Show events around ticket creation time (5 min before/after) or last 24h if no timestamp
    const after = ticketCreatedAt ? new Date(new Date(ticketCreatedAt).getTime() - 5 * 60 * 1000).toISOString() : '-24h'
    const before = ticketCreatedAt
        ? new Date(new Date(ticketCreatedAt).getTime() + 5 * 60 * 1000).toISOString()
        : undefined

    return {
        kind: NodeKind.DataTableNode,
        full: false,
        showEventsFilter: false,
        hiddenColumns: [PERSON_DISPLAY_NAME_COLUMN_NAME],
        source: {
            kind: NodeKind.EventsQuery,
            select: defaultDataTableColumns(NodeKind.EventsQuery),
            personId: personId,
            after,
            before,
            // Filter by session_id if available (shows events from the exact session)
            ...(sessionId && {
                properties: [
                    {
                        type: PropertyFilterType.Event,
                        key: '$session_id',
                        value: sessionId,
                        operator: PropertyOperator.Exact,
                    },
                ],
            }),
        },
    }
}

function createExceptionsQuery(sessionId?: string, ticketCreatedAt?: string): DataTableNode {
    // Show exceptions from the session or around ticket creation time
    const after = ticketCreatedAt ? new Date(new Date(ticketCreatedAt).getTime() - 5 * 60 * 1000).toISOString() : '-24h'
    const before = ticketCreatedAt
        ? new Date(new Date(ticketCreatedAt).getTime() + 5 * 60 * 1000).toISOString()
        : undefined

    return {
        kind: NodeKind.DataTableNode,
        full: false,
        showEventFilter: false,
        hiddenColumns: [PERSON_DISPLAY_NAME_COLUMN_NAME],
        source: {
            kind: NodeKind.EventsQuery,
            select: defaultDataTableColumns(NodeKind.EventsQuery),
            event: '$exception',
            after,
            before,
            // Filter by session_id if available
            ...(sessionId && {
                properties: [
                    {
                        type: PropertyFilterType.Event,
                        key: '$session_id',
                        value: sessionId,
                        operator: PropertyOperator.Exact,
                    },
                ],
            }),
        },
    }
}

/** Why a customer-facing email reply on this ticket can never be delivered. */
export type EmailReplyBlockedReason = 'email_disabled' | 'no_recipient' | 'no_channel'

/**
 * Mirrors the backend gates in send_email_reply_on_team_message / _process_outbox_row:
 * a reply that fails any of these is saved as a comment but never delivered.
 */
export function getEmailReplyBlockedReason(
    ticket: Pick<Ticket, 'channel_source' | 'email_from' | 'email_to'> | null,
    conversationsSettings: { email_enabled?: boolean } | null | undefined
): EmailReplyBlockedReason | null {
    if (ticket?.channel_source !== 'email') {
        return null
    }
    if (!conversationsSettings?.email_enabled) {
        return 'email_disabled'
    }
    if (!ticket.email_from) {
        return 'no_recipient'
    }
    if (!ticket.email_to) {
        return 'no_channel'
    }
    return null
}

/**
 * An AI draft the pipeline saved as an internal note, i.e. one the customer never received.
 * Gated behind PRODUCT_SUPPORT_AI_NOTES because agents who don't want the drafts read them as
 * noise. A published AI reply is not one of these: hiding what the customer already got would
 * make the thread misrepresent the conversation.
 */
export function isAiPrivateNote(message: Pick<CommentType, 'item_context'>): boolean {
    return message.item_context?.author_type === 'AI' && message.item_context?.is_private === true
}

// Generated by kea-typegen. Update if you're an agent, ignore if you're human.
export interface supportTicketSceneLogicValues {
    resolveAssignee: (assignee: TicketAssignee) => Assignee // assigneeSelectLogic
    draftModeDefault: boolean // conversationsDraftModeLogic
    featureFlags: FeatureFlagsSet // featureFlagLogic
    availableTags: string[] // tagsModel
    currentTeam: TeamPublicType | TeamType | null // teamLogic
    user: UserType | null // userLogic
    assignee: TicketAssignee
    breadcrumbs: Breadcrumb[]
    chatMessages: ChatMessage[]
    chatPanelWidth: (desiredSize: number | null) => number
    discussionsEnabled: boolean
    draftContent: string | JSONContent | null
    draftIsPrivate: boolean
    draftModeEnabled: boolean
    editingMessageId: string | null
    emailReplyBlockedReason: EmailReplyBlockedReason | null
    eventsQuery: DataTableNode | null
    exceptionsQuery: DataTableNode | null
    feedbackByMessageId: Record<string, AiReplyFeedbackRating>
    hasMoreMessages: boolean
    hasPendingWork: boolean
    hasUnsavedChanges: boolean
    knowledgeGaps: KnowledgeGapSuggestion[]
    knowledgeGapsLoading: boolean
    latestAiMessage: ChatMessage | null
    linkedReports: SignalReportApi[]
    linkedReportsLoading: boolean
    messageSending: boolean
    messages: CommentType[]
    messagesLoading: boolean
    olderMessagesLoading: boolean
    person: PersonType | null
    personLoading: boolean
    previousTickets: Ticket[]
    previousTicketsLoading: boolean
    priority: TicketPriority | null
    replyRecipientDescription: string
    sidePanelContext: SidePanelSceneContext | null
    snoozedUntil: string | null
    stashedDraftContent: string | JSONContent | null
    stashedDraftIsPrivate: boolean
    status: TicketStatus | null
    tags: string[]
    ticket: Ticket | null
    ticketLoading: boolean
    ticketUpdating: boolean
    unsavedTicketChanges: string[]
}

// Generated by kea-typegen. Update if you're an agent, ignore if you're human.
export interface supportTicketSceneLogicActions {
    loadTickets: () => {
        value: true
    } // supportTicketsSceneLogic
    loadTags: () => any // tagsModel
    appendMessage: (message: CommentType) => {
        message: CommentType
    }
    cancelEditingMessage: () => {
        value: true
    }
    clearEditingMessage: () => {
        value: true
    }
    deleteMessage: (messageId: string) => {
        messageId: string
    }
    dismissKnowledgeGap: (suggestionId: string) => {
        suggestionId: string
    }
    incrementUnreadCustomerCount: () => {
        value: true
    }
    loadKnowledgeGaps: () => {
        value: true
    }
    loadKnowledgeGapsFailure: (
        error: string,
        errorObject?: any
    ) => {
        error: string
        errorObject?: any
    }
    loadKnowledgeGapsSuccess: (
        knowledgeGaps: KnowledgeGapSuggestion[],
        payload?: {
            value: true
        }
    ) => {
        knowledgeGaps: KnowledgeGapSuggestion[]
        payload?: {
            value: true
        }
    }
    loadLinkedReports: () => {
        value: true
    }
    loadLinkedReportsFailure: (
        error: string,
        errorObject?: any
    ) => {
        error: string
        errorObject?: any
    }
    loadLinkedReportsSuccess: (
        linkedReports: SignalReportApi[],
        payload?: {
            value: true
        }
    ) => {
        linkedReports: SignalReportApi[]
        payload?: {
            value: true
        }
    }
    loadMessages: () => {
        value: true
    }
    loadOlderMessages: () => {
        value: true
    }
    loadPerson: () => {
        value: true
    }
    loadPersonFailure: (
        error: string,
        errorObject?: any
    ) => {
        error: string
        errorObject?: any
    }
    loadPersonSuccess: (
        person: PersonType | null,
        payload?: {
            value: true
        }
    ) => {
        person: PersonType | null
        payload?: {
            value: true
        }
    }
    loadPreviousTickets: () => {
        value: true
    }
    loadPreviousTicketsFailure: (
        error: string,
        errorObject?: any
    ) => {
        error: string
        errorObject?: any
    }
    loadPreviousTicketsSuccess: (
        previousTickets: Ticket[],
        payload?: {
            value: true
        }
    ) => {
        previousTickets: Ticket[]
        payload?: {
            value: true
        }
    }
    loadTicket: () => {
        value: true
    }
    pollDiscussionThread: () => {
        value: true
    }
    recordAiReplyFeedback: (
        messageId: string,
        rating: AiReplyFeedbackRating
    ) => {
        messageId: string
        rating: AiReplyFeedbackRating
    }
    sendMessage: (
        content: string,
        richContent: Record<string, unknown> | null,
        isPrivate: boolean,
        onSuccess?: () => void,
        statusAfterSend?: TicketStatus
    ) => {
        content: string
        isPrivate: boolean
        onSuccess: (() => void) | undefined
        richContent: Record<string, unknown> | null
        statusAfterSend: TicketStatus | undefined
    }
    setAssignee: (assignee: TicketAssignee) => {
        assignee: TicketAssignee
    }
    setDraftContent: (content: string | JSONContent | null) => {
        content: string | JSONContent | null
    }
    setDraftIsPrivate: (isPrivate: boolean) => {
        isPrivate: boolean
    }
    setDraftModeEnabled: (enabled: boolean) => {
        enabled: boolean
    }
    setHasMoreMessages: (hasMore: boolean) => {
        hasMore: boolean
    }
    setMessageSending: (sending: boolean) => {
        sending: boolean
    }
    setMessages: (messages: CommentType[]) => {
        messages: CommentType[]
    }
    setMessagesLoading: (loading: boolean) => {
        loading: boolean
    }
    setOlderMessages: (olderMessages: CommentType[]) => {
        olderMessages: CommentType[]
    }
    setOlderMessagesLoading: (loading: boolean) => {
        loading: boolean
    }
    setPriority: (priority: TicketPriority) => {
        priority: TicketPriority
    }
    setSnoozedUntil: (snoozedUntil: string | null) => {
        snoozedUntil: string | null
    }
    setStatus: (status: TicketStatus) => {
        status: TicketStatus
    }
    setTags: (tags: string[]) => {
        tags: string[]
    }
    setTicket: (ticket: Ticket | null) => {
        ticket: Ticket | null
    }
    setTicketLoading: (loading: boolean) => {
        loading: boolean
    }
    setTicketUpdating: (updating: boolean) => {
        updating: boolean
    }
    startEditingMessage: (message: ChatMessage) => {
        message: ChatMessage
    }
    stashDraftForEdit: (
        content: string | JSONContent | null,
        isPrivate: boolean
    ) => {
        content: string | JSONContent | null
        isPrivate: boolean
    }
    submitAiReplyFeedback: (
        messageId: string,
        rating: AiReplyFeedbackRating,
        feedbackText?: string
    ) => {
        feedbackText: string | undefined
        messageId: string
        rating: AiReplyFeedbackRating
    }
    updateTicket: () => {
        value: true
    }
}

// Generated by kea-typegen. Update if you're an agent, ignore if you're human.
export interface supportTicketSceneLogicProps {
    id: number | string
}

// Generated by kea-typegen. Update if you're an agent, ignore if you're human.
export interface supportTicketSceneLogicMeta {
    key: number | string
    __keaTypeGenInternalSelectorTypes: {
        breadcrumbs: (id: number | string) => Breadcrumb[]
        emailReplyBlockedReason: (
            ticket: Ticket | null,
            currentTeam: TeamPublicType | TeamType | null
        ) => EmailReplyBlockedReason | null
        discussionsEnabled: (ticket: Ticket | null, featureFlags: FeatureFlagsSet) => boolean
        sidePanelContext: (ticket: Ticket | null, discussionsEnabled: boolean) => SidePanelSceneContext | null
        replyRecipientDescription: (ticket: Ticket | null) => string
        unsavedTicketChanges: (
            priority: TicketPriority | null,
            assignee: TicketAssignee,
            tags: string[],
            snoozedUntil: string | null,
            ticket: Ticket | null,
            resolveAssignee: (assignee: TicketAssignee) => Assignee // assigneeSelectLogic
        ) => string[]
        hasUnsavedChanges: (
            status: TicketStatus | null,
            ticket: Ticket | null,
            unsavedTicketChanges: string[]
        ) => boolean
        hasPendingWork: (hasUnsavedChanges: boolean, editingMessageId: string | null) => boolean
        chatMessages: (
            messages: CommentType[],
            ticket: Ticket | null,
            featureFlags: FeatureFlagsSet // featureFlagLogic
        ) => ChatMessage[]
        eventsQuery: (ticket: Ticket | null) => DataTableNode | null
        exceptionsQuery: (ticket: Ticket | null) => DataTableNode | null
        latestAiMessage: (chatMessages: ChatMessage[]) => ChatMessage | null
    }
}

export type supportTicketSceneLogicType = MakeLogicType<
    supportTicketSceneLogicValues,
    supportTicketSceneLogicActions,
    supportTicketSceneLogicProps,
    supportTicketSceneLogicMeta
>

export const supportTicketSceneLogic = kea<supportTicketSceneLogicType>([
    path(['products', 'conversations', 'frontend', 'scenes', 'ticket', 'supportTicketSceneLogic']),
    props({ id: 'new' as string | number }),
    key((props) => props.id),
    connect(() => ({
        actions: [supportTicketsSceneLogic, ['loadTickets'], tagsModel, ['loadTags']],
        values: [
            teamLogic,
            ['currentTeam'],
            featureFlagLogic,
            ['featureFlags'],
            conversationsDraftModeLogic,
            ['draftModeDefault'],
            assigneeSelectLogic,
            ['resolveAssignee'],
            tagsModel,
            ['tags as availableTags'],
            userLogic,
            ['user'],
        ],
    })),
    actions({
        loadTicket: true,
        setTicket: (ticket: Ticket | null) => ({ ticket }),
        setTicketLoading: (loading: boolean) => ({ loading }),
        incrementUnreadCustomerCount: true,
        updateTicket: true,
        setTicketUpdating: (updating: boolean) => ({ updating }),

        loadMessages: true,
        setMessages: (messages: CommentType[]) => ({ messages }),
        setMessagesLoading: (loading: boolean) => ({ loading }),
        appendMessage: (message: CommentType) => ({ message }),

        pollDiscussionThread: true,

        loadOlderMessages: true,
        setOlderMessages: (olderMessages: CommentType[]) => ({ olderMessages }),
        setOlderMessagesLoading: (loading: boolean) => ({ loading }),
        setHasMoreMessages: (hasMore: boolean) => ({ hasMore }),

        sendMessage: (
            content: string,
            richContent: Record<string, unknown> | null,
            isPrivate: boolean,
            onSuccess?: () => void,
            statusAfterSend?: TicketStatus
        ) => ({
            content,
            richContent,
            isPrivate,
            onSuccess,
            statusAfterSend,
        }),
        setMessageSending: (sending: boolean) => ({ sending }),

        setStatus: (status: TicketStatus) => ({ status }),
        setPriority: (priority: TicketPriority) => ({ priority }),
        setAssignee: (assignee: TicketAssignee) => ({ assignee }),
        setTags: (tags: string[]) => ({ tags }),
        setSnoozedUntil: (snoozedUntil: string | null) => ({ snoozedUntil }),

        // Session context actions
        loadPerson: true,
        loadPreviousTickets: true,
        loadLinkedReports: true,

        // Knowledge gap suggestions
        loadKnowledgeGaps: true,
        dismissKnowledgeGap: (suggestionId: string) => ({ suggestionId }),

        // Draft message state (persists across tab switches)
        setDraftContent: (content: string | JSONContent | null) => ({ content }),
        setDraftIsPrivate: (isPrivate: boolean) => ({ isPrivate }),
        // Per-ticket draft mode override, seeded from the browser-local default on open
        setDraftModeEnabled: (enabled: boolean) => ({ enabled }),

        startEditingMessage: (message: ChatMessage) => ({ message }),
        cancelEditingMessage: true,
        clearEditingMessage: true,
        stashDraftForEdit: (content: string | JSONContent | null, isPrivate: boolean) => ({ content, isPrivate }),
        deleteMessage: (messageId: string) => ({ messageId }),

        submitAiReplyFeedback: (messageId: string, rating: AiReplyFeedbackRating, feedbackText?: string) => ({
            messageId,
            rating,
            feedbackText,
        }),
        recordAiReplyFeedback: (messageId: string, rating: AiReplyFeedbackRating) => ({
            messageId,
            rating,
        }),
    }),
    loaders(({ values, props }) => ({
        person: [
            null as PersonType | null,
            {
                loadPerson: async (): Promise<PersonType | null> => {
                    const ticket = values.ticket
                    if (!ticket?.distinct_id) {
                        return null
                    }

                    try {
                        // First try to load by distinct_id
                        const response = await api.persons.list({ distinct_id: ticket.distinct_id })
                        if (response.results.length > 0) {
                            return response.results[0]
                        }

                        // If not found, return null
                        return null
                    } catch (error) {
                        console.error('Failed to load person:', error)
                        return null
                    }
                },
            },
        ],
        linkedReports: [
            [] as SignalReportApi[],
            {
                loadLinkedReports: async (): Promise<SignalReportApi[]> => {
                    const ticketUuid = values.ticket?.id
                    if (!ticketUuid) {
                        return []
                    }
                    try {
                        const response = await signalsReportsList(getCurrentTeamId().toString(), {
                            source_id: ticketUuid,
                            source_product: SignalSourceProductApi.Conversations,
                            // A teammate answering a customer needs to know an investigation was
                            // dismissed just as much as that one is running.
                            include_all_statuses: true,
                        })
                        return response.results
                    } catch (error) {
                        // Supplementary context: a signals or ClickHouse hiccup must not break the ticket.
                        console.error('Failed to load linked reports:', error)
                        return []
                    }
                },
            },
        ],
        previousTickets: [
            [] as Ticket[],
            {
                loadPreviousTickets: async (): Promise<Ticket[]> => {
                    const person = values.person
                    const currentTicketId = props.id

                    if (!person?.distinct_ids || person.distinct_ids.length === 0) {
                        return []
                    }

                    // Widen the match to email only when the current ticket's identity was positively
                    // attested (e.g. SPF-authenticated email). email_from is attacker-controllable on
                    // unverified tickets, and person.properties.email is customer-controlled analytics
                    // data with no trusted mapping — trusting either would let a spoofed sender pull a
                    // real customer's ticket history into their own ticket view.
                    const emails = new Set<string>()
                    if (values.ticket?.identity_verified === true && values.ticket.email_from) {
                        emails.add(values.ticket.email_from)
                    }

                    try {
                        const response = await api.conversationsTickets.list({
                            distinct_ids: person.distinct_ids.join(','),
                            ...(emails.size > 0 ? { emails: Array.from(emails).join(',') } : {}),
                        })
                        const allTickets = response.results || []

                        // Exclude current ticket
                        const uniqueTickets = allTickets.filter(
                            (ticket) => ticket.ticket_number !== parseInt(currentTicketId.toString())
                        )

                        // Sort by created_at descending (most recent first)
                        return uniqueTickets.sort(
                            (a, b) => new Date(b.created_at).getTime() - new Date(a.created_at).getTime()
                        )
                    } catch (error) {
                        console.error('Failed to load previous tickets:', error)
                        return []
                    }
                },
            },
        ],
        knowledgeGaps: [
            [] as KnowledgeGapSuggestion[],
            {
                loadKnowledgeGaps: async (): Promise<KnowledgeGapSuggestion[]> => {
                    const ticket = values.ticket
                    if (!ticket) {
                        return []
                    }
                    try {
                        const response = await businessKnowledgeGapSuggestionsList(String(getCurrentTeamId()), {
                            ticket_id: ticket.id,
                        })
                        const data = Array.isArray(response) ? response : (response.results ?? [])
                        return data as unknown as KnowledgeGapSuggestion[]
                    } catch {
                        return []
                    }
                },
            },
        ],
    })),
    reducers({
        ticket: [
            null as Ticket | null,
            {
                setTicket: (_, { ticket }) => ticket,
                incrementUnreadCustomerCount: (state) =>
                    state ? { ...state, unread_customer_count: state.unread_customer_count + 1 } : state,
            },
        ],
        ticketUpdating: [
            false,
            {
                updateTicket: () => true,
                setTicketUpdating: (_, { updating }) => updating,
                setTicket: () => false,
            },
        ],
        ticketLoading: [
            false,
            {
                loadTicket: () => true,
                setTicket: () => false,
                setTicketLoading: (_, { loading }) => loading,
            },
        ],
        status: [
            null as TicketStatus | null,
            {
                setStatus: (_, { status }) => status,
                setTicket: (_, { ticket }) => ticket?.status || null,
            },
        ],
        priority: [
            null as TicketPriority | null,
            {
                setPriority: (_, { priority }) => priority,
                setTicket: (_, { ticket }) => ticket?.priority || null,
            },
        ],
        assignee: [
            null as TicketAssignee,
            {
                setAssignee: (_, { assignee }) => assignee,
                setTicket: (_, { ticket }) => ticket?.assignee || null,
            },
        ],
        tags: [
            [] as string[],
            {
                setTags: (_, { tags }) => tags,
                setTicket: (_, { ticket }) => ticket?.tags || [],
            },
        ],
        snoozedUntil: [
            null as string | null,
            {
                setSnoozedUntil: (_, { snoozedUntil }) => snoozedUntil,
                setTicket: (_, { ticket }) => ticket?.snoozed_until || null,
            },
        ],
        messages: [
            [] as CommentType[],
            {
                setMessages: (_, { messages }) => messages,
                setOlderMessages: (state, { olderMessages }) => [...olderMessages, ...state],
                appendMessage: (state, { message }) => {
                    if (state.some((existing) => existing.id === message.id)) {
                        return state
                    }
                    return [...state, message].sort((a, b) => a.created_at.localeCompare(b.created_at))
                },
            },
        ],
        messagesLoading: [
            false,
            {
                loadMessages: () => true,
                setMessages: () => false,
                setMessagesLoading: (_, { loading }) => loading,
            },
        ],
        olderMessagesLoading: [
            false,
            {
                loadOlderMessages: () => true,
                setOlderMessages: () => false,
                setOlderMessagesLoading: (_, { loading }) => loading,
            },
        ],
        hasMoreMessages: [
            true,
            {
                setMessages: (_, { messages }) => messages.length >= 100,
                setHasMoreMessages: (_, { hasMore }) => hasMore,
            },
        ],
        messageSending: [
            false,
            {
                sendMessage: () => true,
                setMessageSending: (_, { sending }) => sending,
            },
        ],
        draftContent: [
            null as string | JSONContent | null,
            {
                setDraftContent: (_, { content }) => content,
            },
        ],
        draftIsPrivate: [
            false,
            {
                setDraftIsPrivate: (_, { isPrivate }) => isPrivate,
            },
        ],
        draftModeEnabled: [
            false,
            {
                setDraftModeEnabled: (_, { enabled }) => enabled,
            },
        ],
        editingMessageId: [
            null as string | null,
            {
                startEditingMessage: (_, { message }) => message.id,
                clearEditingMessage: () => null,
            },
        ],
        stashedDraftContent: [
            null as string | JSONContent | null,
            {
                stashDraftForEdit: (_, { content }) => content,
                clearEditingMessage: () => null,
            },
        ],
        stashedDraftIsPrivate: [
            false,
            {
                stashDraftForEdit: (_, { isPrivate }) => isPrivate,
                clearEditingMessage: () => false,
            },
        ],
        feedbackByMessageId: [
            {} as Record<string, AiReplyFeedbackRating>,
            { persist: true, storageKey: 'conversations_ai_reply_feedback' },
            {
                recordAiReplyFeedback: (state, { messageId, rating }) => ({
                    ...state,
                    [messageId]: rating,
                }),
            },
        ],
    }),
    selectors({
        breadcrumbs: [
            (_, p) => [p.id],
            (id: number | string): Breadcrumb[] => {
                let name: string
                if (id === 'new') {
                    name = 'New ticket'
                } else if (typeof id === 'string' && isUUIDLike(id)) {
                    // Legacy UUID URLs: show the first segment without a # (which implies a number)
                    name = `Ticket ${id.split('-')[0]}`
                } else {
                    name = `Ticket #${id}`
                }
                return [{ key: ['SupportTicketDetail', id], name }]
            },
        ],
        emailReplyBlockedReason: [
            (s) => [s.ticket, s.currentTeam],
            (
                ticket: Ticket | null,
                currentTeam: null | import('~/types').TeamPublicType | import('~/types').TeamType
            ): EmailReplyBlockedReason | null =>
                getEmailReplyBlockedReason(ticket, currentTeam?.conversations_settings),
        ],
        // Whether this ticket has a discussion at all. The side-panel context, the in-thread discussion
        // cards and the "Discuss with team" button all hang off this one gate so they can't drift into
        // a state where one of them offers a discussion the others don't know about.
        discussionsEnabled: [
            (s) => [s.ticket, s.featureFlags],
            (ticket: Ticket | null, featureFlags: FeatureFlagsSet): boolean =>
                !!ticket?.id && !!featureFlags[FEATURE_FLAGS.DISCUSSIONS_SLACK_SYNC],
        ],
        [SIDE_PANEL_CONTEXT_KEY]: [
            (s) => [s.ticket, s.discussionsEnabled],
            (ticket: Ticket | null, discussionsEnabled: boolean): SidePanelSceneContext | null =>
                ticket?.id
                    ? {
                          access_control_resource: 'ticket',
                          access_control_resource_id: `${ticket.id}`,
                          // Scoping the discussion thread to the ticket is still flag-gated; the
                          // access control fields above are not, so the panel stays gated on
                          // ticket access either way.
                          ...(discussionsEnabled
                              ? {
                                    activity_scope: ActivityScope.TICKET,
                                    activity_item_id: `${ticket.id}`,
                                }
                              : {}),
                      }
                    : null,
        ],
        replyRecipientDescription: [
            (s) => [s.ticket],
            (ticket: Ticket | null): string => {
                switch (ticket?.channel_source) {
                    case 'email': {
                        // email_from is the customer's address; email_to is our sending identity.
                        const recipients = [ticket.email_from, ...(ticket.cc_participants ?? [])].filter(Boolean)
                        return recipients.length ? recipients.join(', ') : 'the customer'
                    }
                    case 'slack':
                        return 'the linked Slack thread'
                    case 'teams':
                        return 'the linked Microsoft Teams channel'
                    case 'github':
                        return 'the linked GitHub issue'
                    default:
                        return 'the customer'
                }
            },
        ],
        // Human-readable list of unsaved edits other than status, shown in the send-and-set-status
        // confirmation. Status is excluded because that action overrides it anyway.
        unsavedTicketChanges: [
            (s) => [s.priority, s.assignee, s.tags, s.snoozedUntil, s.ticket, s.resolveAssignee],
            (
                priority: TicketPriority | null,
                assignee: TicketAssignee,
                tags: string[],
                snoozedUntil: string | null,
                ticket: Ticket | null,
                resolveAssignee: (assignee: TicketAssignee) => Assignee
            ): string[] => {
                if (!ticket) {
                    return []
                }
                const changes: string[] = []
                if (priority && priority !== ticket.priority) {
                    changes.push(`Priority: ${priorityOptions.find((o) => o.value === priority)?.label ?? priority}`)
                }
                if (JSON.stringify(assignee) !== JSON.stringify(ticket.assignee)) {
                    const resolved = resolveAssignee(assignee)
                    const label =
                        resolved?.type === 'user'
                            ? fullName(resolved.user) || resolved.user.email
                            : resolved?.type === 'role'
                              ? resolved.role.name
                              : assignee
                                ? 'updated'
                                : 'unassigned'
                    changes.push(`Assignee: ${label}`)
                }
                if (JSON.stringify([...tags].sort()) !== JSON.stringify([...(ticket.tags || [])].sort())) {
                    changes.push(tags.length > 0 ? `Tags: ${tags.join(', ')}` : 'Tags: none')
                }
                if (
                    (snoozedUntil ? dayjs(snoozedUntil).unix() : null) !==
                    (ticket.snoozed_until ? dayjs(ticket.snoozed_until).unix() : null)
                ) {
                    changes.push(
                        snoozedUntil
                            ? `Snoozed until ${dayjs(snoozedUntil).format('D MMM YYYY, h:mm A')}`
                            : 'Snooze removed'
                    )
                }
                return changes
            },
        ],
        hasUnsavedChanges: [
            (s) => [s.status, s.ticket, s.unsavedTicketChanges],
            (status: TicketStatus | null, ticket: Ticket | null, unsavedTicketChanges: string[]): boolean => {
                if (!ticket) {
                    return false
                }
                return status !== ticket.status || unsavedTicketChanges.length > 0
            },
        ],
        hasPendingWork: [
            (s) => [s.hasUnsavedChanges, s.editingMessageId],
            (hasUnsavedChanges: boolean, editingMessageId: string | null): boolean =>
                hasUnsavedChanges || !!editingMessageId,
        ],
        chatPanelWidth: [
            () => [],
            () =>
                (desiredSize: number | null): number => {
                    const minWidth = 400
                    const defaultWidth = 600
                    if (desiredSize === null) {
                        return defaultWidth
                    }
                    return desiredSize < minWidth ? minWidth : desiredSize
                },
        ],
        chatMessages: [
            (s) => [s.messages, s.ticket, s.featureFlags],
            (messages: CommentType[], ticket: Ticket | null, featureFlags: FeatureFlagsSet): ChatMessage[] => {
                const showAiNotes = !!featureFlags[FEATURE_FLAGS.PRODUCT_SUPPORT_AI_NOTES]
                return messages
                    .filter((message) => showAiNotes || !isAiPrivateNote(message))
                    .map((message) => {
                        const authorType = message.item_context?.author_type || 'customer'
                        let displayName = 'Anonymous user'
                        if (message.created_by) {
                            displayName =
                                [message.created_by.first_name, message.created_by.last_name]
                                    .filter(Boolean)
                                    .join(' ') ||
                                message.created_by.email ||
                                'Support'
                        } else if (authorType === 'AI') {
                            displayName = 'PostHog Assistant'
                        } else {
                            // Per-message author identity (e.g. Zendesk import stores each comment's own
                            // author) takes precedence over the ticket-level requester, so a reply from a
                            // second requester or an agent shows the real name instead of the ticket owner.
                            const messageAuthorName =
                                message.item_context?.author_name ||
                                message.item_context?.author_email ||
                                message.item_context?.slack_author_name ||
                                message.item_context?.teams_author_name ||
                                message.item_context?.teams_author_email ||
                                message.item_context?.email_from_name
                            if (messageAuthorName) {
                                displayName = messageAuthorName
                            } else if (authorType === 'customer') {
                                displayName =
                                    ticket?.person?.properties?.name ||
                                    ticket?.person?.properties?.email ||
                                    ticket?.anonymous_traits?.name ||
                                    ticket?.anonymous_traits?.email ||
                                    'Anonymous user'
                            } else {
                                // Staff message with no resolvable author (e.g. deleted ex-agent).
                                displayName = 'Support'
                            }
                        }

                        return {
                            id: message.id,
                            content: message.content || '',
                            richContent: message.rich_content,
                            authorType: authorType === 'support' ? 'human' : authorType,
                            authorName: displayName,
                            createdBy: message.created_by,
                            createdAt: message.created_at,
                            isPrivate: message.item_context?.is_private || false,
                            version: message.version,
                            emailDeliveryStatus: message.item_context?.email_delivery_status,
                            fromZendesk: message.item_context?.from_zendesk === true,
                        }
                    })
            },
        ],
        eventsQuery: [
            (s) => [s.ticket],
            (ticket: Ticket | null): DataTableNode | null => {
                // Use person from ticket (no extra API call needed)
                if (!ticket?.person?.id) {
                    return null
                }
                return createEventsQuery(ticket.person.id, ticket.session_id, ticket.created_at)
            },
        ],
        exceptionsQuery: [
            (s) => [s.ticket],
            (ticket: Ticket | null): DataTableNode | null => {
                if (!ticket) {
                    return null
                }
                return createExceptionsQuery(ticket.session_id, ticket.created_at)
            },
        ],
        latestAiMessage: [
            (s) => [s.chatMessages],
            (chatMessages: ChatMessage[]): ChatMessage | null => {
                for (let i = chatMessages.length - 1; i >= 0; i--) {
                    if (chatMessages[i].authorType === 'AI') {
                        return chatMessages[i]
                    }
                }
                return null
            },
        ],
    }),
    listeners(({ actions, values, props, cache }) => ({
        loadTicket: async () => {
            if (values.editingMessageId) {
                actions.cancelEditingMessage()
            }
            if (props.id === 'new') {
                actions.setTicket(null)
                return
            }
            try {
                const ticket = await api.conversationsTickets.get(props.id.toString())

                // If accessed via UUID, redirect to ticket_number URL for cleaner URLs
                const isUuid = props.id.toString().includes('-')
                if (isUuid && ticket.ticket_number) {
                    router.actions.replace(urls.supportTicketDetail(ticket.ticket_number))
                    return
                }

                actions.setTicket(ticket)
                actions.loadMessages()

                impersonationNoticeLogic.findMounted()?.actions.setTicketContext({
                    ticketId: ticket.id,
                    // email_from is the customer's address on email tickets, and it's the only
                    // place it lives on tickets whose traits were never populated.
                    email: ticket.anonymous_traits?.email || ticket.email_from || '',
                    region: regionFromUrl(ticket.session_context?.current_url),
                })

                // Load session context data
                actions.loadPerson()
                actions.loadKnowledgeGaps()
                actions.loadLinkedReports()

                // Refresh the unread count since viewing a ticket marks it as read
                supportTicketCounterLogic.findMounted()?.actions.refreshCount()

                // Start message polling using disposables pattern
                cache.disposables.dispose('messagePolling')
                cache.discussionPollTick = 0
                cache.disposables.add(() => {
                    const intervalId = setInterval(() => {
                        actions.loadMessages()
                        // A discussion is a slower conversation than the ticket itself, and a Slack
                        // reply landing a few seconds late costs nothing — so it rides the same timer
                        // at a fraction of the rate rather than starting a second one.
                        cache.discussionPollTick = (cache.discussionPollTick ?? 0) + 1
                        if (cache.discussionPollTick % DISCUSSION_POLL_EVERY_N_TICKS === 0) {
                            actions.pollDiscussionThread()
                        }
                    }, MESSAGE_POLL_INTERVAL)
                    return () => clearInterval(intervalId)
                }, 'messagePolling')
            } catch (error) {
                console.error('Failed to load ticket:', error)
                lemonToast.error('Failed to load ticket')
                actions.setTicketLoading(false)
            }
        },
        loadPersonSuccess: async () => {
            // Load previous tickets after person is loaded
            actions.loadPreviousTickets()
        },
        updateTicket: async (_, breakpoint) => {
            if (props.id === 'new') {
                actions.setTicketUpdating(false)
                return
            }
            // Serialize overlapping saves: wait out any in-flight PATCH so requests can't land out of
            // order, then let only the newest dispatch proceed with the latest local edits.
            while (cache.ticketUpdateRequest) {
                await cache.ticketUpdateRequest.catch(() => {})
            }
            breakpoint()

            const data: PatchedTicketUpdateRequestApi = {}

            if (values.status && values.status !== values.ticket?.status) {
                data.status = values.status
            }
            if (values.priority && values.priority !== values.ticket?.priority) {
                data.priority = values.priority
            }
            data.assignee = values.assignee
            data.tags = values.tags
            data.snoozed_until = values.snoozedUntil

            const request = conversationsTicketsPartialUpdate(String(getCurrentTeamId()), props.id.toString(), data)
            cache.ticketUpdateRequest = request
            try {
                const ticket = await request
                breakpoint()
                actions.setTicket(ticket as Ticket)
                lemonToast.success('Ticket updated')
                actions.loadTickets()
                // tagsModel loads once per session and never refetches, so newly created tags need an explicit reload
                if (values.tags.some((tag) => !values.availableTags.includes(tag))) {
                    actions.loadTags()
                }
            } catch (error: any) {
                if (error?.isBreakpoint) {
                    throw error
                }
                actions.setTicketUpdating(false)
                lemonToast.error('Failed to update ticket')
            } finally {
                if (cache.ticketUpdateRequest === request) {
                    cache.ticketUpdateRequest = null
                }
            }
        },
        // Refetches the whole discussion rather than checking a count first. A count only moves when a
        // comment is added or removed, so an edit or a task being completed would leave the card and the
        // open side panel showing text nobody has written for a while.
        //
        // `refreshComments` rather than `loadComments` because refreshing must not move the reader:
        // `loadComments` scrolls the panel to the newest comment on every success, which is right when
        // someone opens the thread and wrong every 20 seconds while they read back through it.
        pollDiscussionThread: async () => {
            const ticketId = values.ticket?.id
            if (!values.discussionsEnabled || !ticketId) {
                return
            }
            // findMounted is a null guard, not an optimisation: the ticket page mounts this logic to
            // render its discussion cards, so on a flagged team it is mounted for every open ticket
            // whether or not that ticket has any discussion. Every such ticket therefore pays one
            // indexed comment query per interval. That is deliberate — a teammate starting a
            // discussion elsewhere should make the card appear here, which is the moment this whole
            // surface exists for, and it cannot be detected without asking.
            commentsLogic.findMounted({ scope: ActivityScope.TICKET, item_id: ticketId })?.actions.refreshComments()
        },
        loadMessages: async () => {
            if (props.id === 'new' || !values.ticket?.id) {
                actions.setMessages([])
                return
            }
            const revision = ++cache.messageRevision
            const ticketId = values.ticket.id
            try {
                const response = await api.comments.list({
                    scope: 'conversations_ticket',
                    item_id: ticketId,
                })
                if (cache.messageRevision !== revision || values.ticket?.id !== ticketId) {
                    // setMessages replaces the list wholesale, so a poll that started before a
                    // newer load or a local write must not apply its older snapshot.
                    actions.setMessagesLoading(false)
                    return
                }
                // Reverse to show oldest first (bottom = newest)
                actions.setMessages((response.results || []).reverse())
            } catch {
                lemonToast.error('Failed to load messages')
                actions.setMessagesLoading(false)
            }
        },
        loadOlderMessages: async () => {
            const currentMessages = values.messages
            if (props.id === 'new' || !values.ticket?.id || currentMessages.length === 0 || !values.hasMoreMessages) {
                actions.setOlderMessagesLoading(false)
                actions.setHasMoreMessages(false)
                return
            }

            try {
                const oldestMessage = currentMessages[0]
                const response = await api.comments.list({
                    scope: 'conversations_ticket',
                    item_id: values.ticket.id,
                })

                const allMessages = response.results || []
                const olderMessages = allMessages
                    .filter((msg) => new Date(msg.created_at) < new Date(oldestMessage.created_at))
                    .reverse()

                // Prepending is a local write too: a poll that started earlier would replace the
                // list with just the newest page and drop what we just loaded.
                cache.messageRevision += 1
                actions.setOlderMessages(olderMessages)
                actions.setHasMoreMessages(olderMessages.length > 0)
            } catch {
                lemonToast.error('Failed to load older messages')
                actions.setOlderMessagesLoading(false)
            }
        },
        sendMessage: async ({ content, richContent, isPrivate, onSuccess, statusAfterSend }) => {
            if (props.id === 'new' || !values.ticket?.id) {
                actions.setMessageSending(false)
                return
            }
            const ticketId = values.ticket.id

            if (values.editingMessageId) {
                const editingId = values.editingMessageId
                try {
                    await conversationsTicketsNotesPartialUpdate(String(getCurrentTeamId()), ticketId, editingId, {
                        message: content,
                        rich_content: richContent,
                    })
                } catch {
                    // A failed PATCH leaves the note as it was, so this is always a definite failure
                    // and never goes through the create-recovery path below.
                    lemonToast.error('Failed to update note')
                    actions.setMessageSending(false)
                    return
                }
                // Optimistic local update so the thread reflects the edit before comments.list returns.
                cache.messageRevision += 1
                actions.setMessages(
                    values.messages.map((message) =>
                        message.id === editingId
                            ? {
                                  ...message,
                                  content,
                                  rich_content: richContent,
                                  version: (message.version ?? 0) + 1,
                              }
                            : message
                    )
                )
                lemonToast.success('Private note updated')
                actions.setMessageSending(false)
                // Restore the stashed composer draft; skip onSuccess (it clears the editor).
                actions.cancelEditingMessage()
                actions.loadMessages()
                return
            }

            const attemptStartedAt = dayjs()
            let sent: CommentType | null = null
            let unconfirmedReason: UnconfirmedSendReason = null
            let alreadySent = false

            try {
                const response = await api.createResponse(getCommentsCreateUrl(String(getCurrentTeamId())), {
                    content,
                    rich_content: richContent,
                    scope: 'conversations_ticket',
                    item_id: ticketId,
                    item_context: {
                        author_type: 'support',
                        is_private: isPrivate,
                    },
                })
                alreadySent = response.status === 200
                sent = (await response.json()) as CommentType
            } catch (error: any) {
                unconfirmedReason = classifySendFailure(error)
                if (unconfirmedReason === null) {
                    lemonToast.error('Failed to send message')
                    actions.setMessageSending(false)
                    return
                }
                // The message may already be in the thread, so look before telling the operator
                // anything. A silent fetch keeps this off the normal loading and error paths.
                const authorId = values.user?.id
                try {
                    const response = await api.comments.list({ scope: 'conversations_ticket', item_id: ticketId })
                    const earliestAcceptable = attemptStartedAt.subtract(SEND_RECOVERY_WINDOW_SECONDS, 'second')
                    sent =
                        (response.results || []).find(
                            (message) =>
                                message.content === content &&
                                objectsEqual(message.rich_content ?? null, richContent ?? null) &&
                                message.item_context?.is_private === isPrivate &&
                                message.item_context?.author_type === 'support' &&
                                // Without a known author we can't tell our own send from a
                                // colleague's identical one, so treat the outcome as unresolved.
                                authorId !== undefined &&
                                message.created_by?.id === authorId &&
                                !dayjs(message.created_at).isBefore(earliestAcceptable)
                        ) ?? null
                } catch {
                    // Leave `sent` null: an unresolved outcome is the safe answer, and the operator
                    // does not need a second toast about a fetch they never asked for.
                }
            }

            if (!sent) {
                posthog.capture('support reply send unconfirmed', {
                    reason: unconfirmedReason,
                    is_private: isPrivate,
                })
                lemonToast.error(
                    "We couldn't confirm that your message was added. Check the thread before sending it again."
                )
                actions.setMessageSending(false)
                return
            }

            if (alreadySent) {
                posthog.capture('support reply send deduplicated', { is_private: isPrivate })
                cache.messageRevision += 1
                actions.appendMessage(sent)
                lemonToast.warning(
                    isPrivate
                        ? "You just added this note, so we didn't add it again. Edit your draft to add something different."
                        : "You just sent this reply, so we didn't send it again. Edit your draft to send something different."
                )
                actions.setMessageSending(false)
                return
            }

            // "Added", not "sent": email delivery is async (outbox + Celery) and can still fail
            // after this API call succeeds; the per-message delivery status is the send signal.
            cache.messageRevision += 1
            actions.appendMessage(sent)
            lemonToast.success(isPrivate ? 'Private note added' : 'Reply added')
            actions.setMessageSending(false)
            onSuccess?.()
            if (!isPrivate) {
                actions.incrementUnreadCustomerCount()
            }
            if (statusAfterSend) {
                actions.setStatus(statusAfterSend)
                actions.updateTicket()
            }
            actions.loadTickets()
        },
        startEditingMessage: ({ message }) => {
            // Only stash the composer draft on first enter; switching notes keeps the original stash.
            if (!cache.noteEditActive) {
                actions.stashDraftForEdit(values.draftContent, values.draftIsPrivate)
                cache.noteEditActive = true
            }
            actions.setDraftIsPrivate(true)
            if (message.richContent) {
                actions.setDraftContent(message.richContent as JSONContent)
            } else {
                // Notes from MCP/reply API are markdown-only; TipTap parses HTML from marked.
                actions.setDraftContent(markdownToHtml(message.content || ''))
            }
        },
        cancelEditingMessage: () => {
            actions.setDraftContent(values.stashedDraftContent)
            actions.setDraftIsPrivate(values.stashedDraftIsPrivate)
            cache.noteEditActive = false
            actions.clearEditingMessage()
        },
        setMessages: ({ messages }) => {
            if (values.editingMessageId && !messages.some((m) => m.id === values.editingMessageId)) {
                actions.cancelEditingMessage()
            }
        },
        deleteMessage: async ({ messageId }) => {
            if (!values.ticket?.id) {
                return
            }
            LemonDialog.open({
                title: 'Delete private note?',
                description: 'This removes the note from the ticket thread.',
                primaryButton: {
                    children: 'Delete',
                    status: 'danger',
                    onClick: async () => {
                        try {
                            await conversationsTicketsNotesDestroy(
                                String(getCurrentTeamId()),
                                values.ticket!.id,
                                messageId
                            )
                            lemonToast.success('Private note deleted')
                            if (values.editingMessageId === messageId) {
                                actions.cancelEditingMessage()
                            }
                            actions.loadMessages()
                        } catch {
                            lemonToast.error('Failed to delete note')
                        }
                    },
                },
                secondaryButton: { children: 'Cancel' },
            })
        },
        dismissKnowledgeGap: async ({ suggestionId }) => {
            try {
                await businessKnowledgeGapSuggestionsDismissCreate(String(getCurrentTeamId()), suggestionId)
                actions.loadKnowledgeGaps()
            } catch {
                lemonToast.error('Failed to dismiss suggestion')
            }
        },
        submitAiReplyFeedback: async ({ messageId, rating, feedbackText }) => {
            const ticket = values.ticket
            if (!ticket) {
                return
            }
            try {
                if (feedbackText) {
                    if (rating !== 'bad') {
                        return
                    }
                    await api.conversationsTickets.submitAiFeedback(ticket.id, {
                        message_id: messageId,
                        rating,
                        feedback_text: feedbackText,
                    })
                    return
                }
                if (values.feedbackByMessageId[messageId]) {
                    return
                }
                await api.conversationsTickets.submitAiFeedback(ticket.id, {
                    message_id: messageId,
                    rating,
                })
                actions.recordAiReplyFeedback(messageId, rating)
            } catch {
                lemonToast.error('Failed to submit feedback')
            }
        },
    })),
    afterMount(({ actions, props, values, cache }) => {
        // Guards against a slow poll landing after a newer load or a local message write.
        cache.messageRevision = 0
        actions.setDraftModeEnabled(values.draftModeDefault)
        if (props.id !== 'new') {
            actions.loadTicket()
        }
    }),
    beforeUnmount(() => {
        // The message poller is registered through cache.disposables, which the plugin tears down.
        impersonationNoticeLogic.findMounted()?.actions.setTicketContext(null)
    }),
    beforeUnload(({ values, actions }) => ({
        enabled: (newLocation) => {
            if (!values.hasPendingWork) {
                return false
            }
            // Ignore in-page navigations (e.g. opening a side panel) that keep the same path
            if (newLocation && newLocation.pathname === router.values.location.pathname) {
                return false
            }
            return true
        },
        message: 'You have unsaved changes. Are you sure you want to leave?',
        onConfirm: () => {
            // Re-sync local form reducers to the last-known server ticket so hasUnsavedChanges
            // recomputes to false and the prompt does not re-fire on the next navigation.
            if (values.ticket) {
                actions.setTicket(values.ticket)
            }
        },
    })),
])
