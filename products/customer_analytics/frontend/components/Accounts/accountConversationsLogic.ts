import { MakeLogicType, actions, afterMount, connect, kea, key, path, props, reducers, selectors } from 'kea'
import { loaders } from 'kea-loaders'
import posthog from 'posthog-js'

import { teamLogic } from 'scenes/teamLogic'

import {
    accountsEmailThreadsList,
    accountsSummariesList,
    accountsSupportTicketsList,
} from 'products/customer_analytics/frontend/generated/api'
import type {
    AccountChannelSummaryApi,
    AccountEmailThreadApi,
    SupportTicketApi,
} from 'products/customer_analytics/frontend/generated/api.schemas'

export type ConversationSource = 'email' | 'support' | 'slack'

export type AccountConversation =
    | { id: string; source: 'email'; occurredAt: string | null; email: AccountEmailThreadApi }
    | { id: string; source: 'support'; occurredAt: string | null; ticket: SupportTicketApi }
    | { id: string; source: 'slack'; occurredAt: string; summary: AccountChannelSummaryApi }

interface AccountConversationsResult {
    conversations: AccountConversation[] | null
    loadFailed?: boolean
}

export const NOT_LOADED: AccountConversationsResult = { conversations: null }
const LIST_LIMIT = 50

export interface AccountConversationsLogicProps {
    accountId: string
}

interface accountConversationsLogicValues {
    conversationsResult: AccountConversationsResult
    conversationsResultLoading: boolean
    currentTeamId: number | null
    expandedConversationId: string | null
    filteredConversations: AccountConversation[]
    searchTerm: string
    sources: ConversationSource[]
}

interface accountConversationsLogicActions {
    closeConversation: (conversationId: string) => { conversationId: string }
    loadConversations: () => void
    loadConversationsFailure: (error: string, errorObject?: unknown) => { error: string; errorObject?: unknown }
    loadConversationsSuccess: (
        conversationsResult: AccountConversationsResult,
        payload?: unknown
    ) => { conversationsResult: AccountConversationsResult; payload?: unknown }
    openConversation: (conversationId: string) => { conversationId: string }
    setSearchTerm: (searchTerm: string) => { searchTerm: string }
    setSources: (sources: ConversationSource[]) => { sources: ConversationSource[] }
}

interface accountConversationsLogicMeta {
    key: string
}

type accountConversationsLogicType = MakeLogicType<
    accountConversationsLogicValues,
    accountConversationsLogicActions,
    AccountConversationsLogicProps,
    accountConversationsLogicMeta
>

function searchableText(conversation: AccountConversation): string {
    if (conversation.source === 'email') {
        return `${conversation.email.subject} ${conversation.email.preview} ${conversation.email.participants
            .map((participant) => `${participant.display_name} ${participant.email}`)
            .join(' ')}`
    }
    if (conversation.source === 'support') {
        return `${conversation.ticket.ticket_number} ${conversation.ticket.last_message_text ?? ''} ${conversation.ticket.started_by}`
    }
    return `${conversation.summary.period_start} ${conversation.summary.period_end} ${conversation.summary.content}`
}

export const accountConversationsLogic = kea<accountConversationsLogicType>([
    path((key) => ['scenes', 'customerAnalytics', 'accounts', 'accountConversationsLogic', key]),
    props({} as AccountConversationsLogicProps),
    key((props) => props.accountId),
    connect(() => ({ values: [teamLogic, ['currentTeamId']] })),
    actions({
        setSearchTerm: (searchTerm: string) => ({ searchTerm }),
        setSources: (sources: ConversationSource[]) => ({ sources }),
        openConversation: (conversationId: string) => ({ conversationId }),
        closeConversation: (conversationId: string) => ({ conversationId }),
    }),
    loaders(({ props, values }) => ({
        conversationsResult: [
            NOT_LOADED,
            {
                loadConversations: async (): Promise<AccountConversationsResult> => {
                    try {
                        const [emailResponse, supportTickets, summaryResponse] = await Promise.all([
                            accountsEmailThreadsList(String(values.currentTeamId), props.accountId, {
                                limit: LIST_LIMIT,
                                offset: 0,
                            }),
                            accountsSupportTicketsList(String(values.currentTeamId), props.accountId),
                            accountsSummariesList(String(values.currentTeamId), props.accountId, {
                                limit: LIST_LIMIT,
                                offset: 0,
                            }),
                        ])
                        const conversations: AccountConversation[] = [
                            ...emailResponse.results.map(
                                (email): AccountConversation => ({
                                    id: `email:${email.id}`,
                                    source: 'email',
                                    occurredAt: email.last_message_at,
                                    email,
                                })
                            ),
                            ...supportTickets.map(
                                (ticket): AccountConversation => ({
                                    id: `support:${ticket.id}`,
                                    source: 'support',
                                    occurredAt: ticket.last_message_at,
                                    ticket,
                                })
                            ),
                            ...summaryResponse.results.map(
                                (summary): AccountConversation => ({
                                    id: `slack:${summary.id}`,
                                    source: 'slack',
                                    occurredAt: summary.period_end,
                                    summary,
                                })
                            ),
                        ].sort((left, right) => (right.occurredAt ?? '').localeCompare(left.occurredAt ?? ''))
                        return { conversations }
                    } catch (error) {
                        posthog.captureException(error as Error, {
                            scope: 'accountConversationsLogic.loadConversations',
                        })
                        return { conversations: null, loadFailed: true }
                    }
                },
            },
        ],
    })),
    reducers({
        searchTerm: ['', { setSearchTerm: (_, { searchTerm }) => searchTerm }],
        sources: [['email', 'support', 'slack'] as ConversationSource[], { setSources: (_, { sources }) => sources }],
        expandedConversationId: [
            null as string | null,
            {
                openConversation: (_, { conversationId }) => conversationId,
                closeConversation: (state, { conversationId }) => (state === conversationId ? null : state),
            },
        ],
    }),
    selectors({
        filteredConversations: [
            (selectors) => [selectors.conversationsResult, selectors.searchTerm, selectors.sources],
            (result, searchTerm, sources): AccountConversation[] => {
                const normalizedSearch = searchTerm.trim().toLowerCase()
                return (result.conversations ?? []).filter(
                    (conversation: AccountConversation) =>
                        sources.includes(conversation.source) &&
                        (!normalizedSearch || searchableText(conversation).toLowerCase().includes(normalizedSearch))
                )
            },
        ],
    }),
    afterMount(({ actions }) => actions.loadConversations()),
])
