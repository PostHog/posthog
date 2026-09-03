import { MakeLogicType, actions, afterMount, connect, kea, key, listeners, path, props, reducers, selectors } from 'kea'
import { loaders } from 'kea-loaders'
import posthog from 'posthog-js'

import { ApiError } from 'lib/api-error'
import { teamLogic } from 'scenes/teamLogic'

import {
    accountsEmailThreadsList,
    accountsSummariesList,
    accountsSupportTicketMessagesList,
    accountsSupportTicketsList,
} from 'products/customer_analytics/frontend/generated/api'
import type {
    AccountChannelSummaryApi,
    AccountEmailThreadApi,
    PaginatedAccountSupportTicketMessageListApi,
    SupportTicketApi,
} from 'products/customer_analytics/frontend/generated/api.schemas'

export type ConversationSource = 'email' | 'support' | 'slack'

export type AccountConversation =
    | { id: string; source: 'email'; occurredAt: string | null; email: AccountEmailThreadApi }
    | { id: string; source: 'support'; occurredAt: string | null; ticket: SupportTicketApi }
    | { id: string; source: 'slack'; occurredAt: string; summary: AccountChannelSummaryApi }

interface AccountConversationsResult {
    conversations: AccountConversation[] | null
    emailCount: number
    failedSources: ConversationSource[]
    loadFailed?: boolean
    summaryCount: number
}

export const NOT_LOADED: AccountConversationsResult = {
    conversations: null,
    emailCount: 0,
    failedSources: [],
    summaryCount: 0,
}
const LIST_LIMIT = 50

export interface AccountConversationsLogicProps {
    accountId: string
}

interface accountConversationsLogicValues {
    conversationsResult: AccountConversationsResult
    conversationsResultLoading: boolean
    currentTeamId: number | null
    expandedConversationId: string | null
    expandedSummaryMessageIds: Record<string, boolean>
    filteredConversations: AccountConversation[]
    olderConversationCount: number
    searchTerm: string
    sources: ConversationSource[]
    supportTicketMessageErrors: Record<string, boolean>
    supportTicketMessages: Record<string, PaginatedAccountSupportTicketMessageListApi>
    supportTicketMessagesLoading: Record<string, boolean>
}

interface accountConversationsLogicActions {
    closeConversation: (conversationId: string) => { conversationId: string }
    loadConversations: () => void
    loadConversationsFailure: (error: string, errorObject?: unknown) => { error: string; errorObject?: unknown }
    loadConversationsSuccess: (
        conversationsResult: AccountConversationsResult,
        payload?: unknown
    ) => { conversationsResult: AccountConversationsResult; payload?: unknown }
    loadMoreConversations: () => void
    loadMoreConversationsFailure: (error: string, errorObject?: unknown) => { error: string; errorObject?: unknown }
    loadMoreConversationsSuccess: (
        conversationsResult: AccountConversationsResult,
        payload?: unknown
    ) => { conversationsResult: AccountConversationsResult; payload?: unknown }
    loadSupportTicketMessages: (ticketId: string) => { ticketId: string }
    loadSupportTicketMessagesFailure: (ticketId: string) => { ticketId: string }
    loadSupportTicketMessagesSuccess: (
        ticketId: string,
        messages: PaginatedAccountSupportTicketMessageListApi
    ) => { ticketId: string; messages: PaginatedAccountSupportTicketMessageListApi }
    openConversation: (conversationId: string) => { conversationId: string }
    setSearchTerm: (searchTerm: string) => { searchTerm: string }
    setSources: (sources: ConversationSource[]) => { sources: ConversationSource[] }
    toggleSummaryMessages: (summaryId: string) => { summaryId: string }
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

function createEmailConversations(emails: readonly AccountEmailThreadApi[]): AccountConversation[] {
    return emails.map(
        (email): AccountConversation => ({
            id: `email:${email.id}`,
            source: 'email',
            occurredAt: email.last_message?.sent_at ?? email.last_message_at,
            email,
        })
    )
}

function createSupportConversations(tickets: readonly SupportTicketApi[]): AccountConversation[] {
    return tickets.map(
        (ticket): AccountConversation => ({
            id: `support:${ticket.id}`,
            source: 'support',
            occurredAt: ticket.last_message?.sent_at ?? ticket.last_message_at,
            ticket,
        })
    )
}

function createSlackConversations(summaries: readonly AccountChannelSummaryApi[]): AccountConversation[] {
    return summaries.map(
        (summary): AccountConversation => ({
            id: `slack:${summary.id}`,
            source: 'slack',
            occurredAt: summary.generated_at,
            summary,
        })
    )
}

function sortConversations(conversations: AccountConversation[]): AccountConversation[] {
    return conversations.sort((left, right) => (right.occurredAt ?? '').localeCompare(left.occurredAt ?? ''))
}

function captureSourceFailure(source: ConversationSource, error: unknown): void {
    if (error instanceof ApiError && error.status === 403) {
        return
    }
    posthog.captureException(error instanceof Error ? error : new Error(`Failed to load ${source} conversations`), {
        scope: 'accountConversationsLogic.loadConversations',
        source,
    })
}

function searchableText(conversation: AccountConversation): string {
    if (conversation.source === 'email') {
        return `${conversation.email.subject} ${conversation.email.preview} ${conversation.email.participants
            .map((participant) => `${participant.display_name} ${participant.email}`)
            .join(' ')}`
    }
    if (conversation.source === 'support') {
        return `${conversation.ticket.ticket_number} ${conversation.ticket.last_message_text ?? ''} ${conversation.ticket.started_by}`
    }
    return `${conversation.summary.period_start} ${conversation.summary.period_end} ${conversation.summary.content} ${conversation.summary.messages.map(({ author }) => author).join(' ')}`
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
        loadSupportTicketMessages: (ticketId: string) => ({ ticketId }),
        loadSupportTicketMessagesSuccess: (
            ticketId: string,
            messages: PaginatedAccountSupportTicketMessageListApi
        ) => ({ ticketId, messages }),
        loadSupportTicketMessagesFailure: (ticketId: string) => ({ ticketId }),
        toggleSummaryMessages: (summaryId: string) => ({ summaryId }),
    }),
    loaders(({ props, values }) => ({
        conversationsResult: [
            NOT_LOADED,
            {
                loadConversations: async (): Promise<AccountConversationsResult> => {
                    const [emailResult, supportResult, summaryResult] = await Promise.allSettled([
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
                    const results = [
                        ['email', emailResult],
                        ['support', supportResult],
                        ['slack', summaryResult],
                    ] as const
                    const failedSources = results
                        .filter(([, result]) => result.status === 'rejected')
                        .map(([source]) => source)
                    for (const [source, result] of results) {
                        if (result.status === 'rejected') {
                            captureSourceFailure(source, result.reason)
                        }
                    }
                    if (failedSources.length === results.length) {
                        return {
                            conversations: null,
                            emailCount: 0,
                            failedSources,
                            loadFailed: true,
                            summaryCount: 0,
                        }
                    }
                    const conversations = sortConversations([
                        ...(emailResult.status === 'fulfilled'
                            ? createEmailConversations(emailResult.value.results)
                            : []),
                        ...(supportResult.status === 'fulfilled'
                            ? createSupportConversations(supportResult.value)
                            : []),
                        ...(summaryResult.status === 'fulfilled'
                            ? createSlackConversations(summaryResult.value.results)
                            : []),
                    ])
                    return {
                        conversations,
                        emailCount: emailResult.status === 'fulfilled' ? emailResult.value.count : 0,
                        failedSources,
                        summaryCount: summaryResult.status === 'fulfilled' ? summaryResult.value.count : 0,
                    }
                },
                loadMoreConversations: async (): Promise<AccountConversationsResult> => {
                    const currentResult = values.conversationsResult
                    if (!currentResult.conversations) {
                        return currentResult
                    }
                    const loadedEmailCount = currentResult.conversations.filter(
                        ({ source }) => source === 'email'
                    ).length
                    const loadedSummaryCount = currentResult.conversations.filter(
                        ({ source }) => source === 'slack'
                    ).length
                    const [emailResult, summaryResult] = await Promise.allSettled([
                        loadedEmailCount < currentResult.emailCount
                            ? accountsEmailThreadsList(String(values.currentTeamId), props.accountId, {
                                  limit: LIST_LIMIT,
                                  offset: loadedEmailCount,
                              })
                            : Promise.resolve(null),
                        loadedSummaryCount < currentResult.summaryCount
                            ? accountsSummariesList(String(values.currentTeamId), props.accountId, {
                                  limit: LIST_LIMIT,
                                  offset: loadedSummaryCount,
                              })
                            : Promise.resolve(null),
                    ])
                    const conversations = [...currentResult.conversations]
                    const failedSources = new Set(currentResult.failedSources)
                    let emailCount = currentResult.emailCount
                    let summaryCount = currentResult.summaryCount
                    if (emailResult.status === 'fulfilled' && emailResult.value) {
                        conversations.push(...createEmailConversations(emailResult.value.results))
                        emailCount = emailResult.value.count
                        failedSources.delete('email')
                    } else if (emailResult.status === 'rejected') {
                        failedSources.add('email')
                        captureSourceFailure('email', emailResult.reason)
                    }
                    if (summaryResult.status === 'fulfilled' && summaryResult.value) {
                        conversations.push(...createSlackConversations(summaryResult.value.results))
                        summaryCount = summaryResult.value.count
                        failedSources.delete('slack')
                    } else if (summaryResult.status === 'rejected') {
                        failedSources.add('slack')
                        captureSourceFailure('slack', summaryResult.reason)
                    }
                    return {
                        conversations: sortConversations([
                            ...new Map(conversations.map((item) => [item.id, item])).values(),
                        ]),
                        emailCount,
                        failedSources: [...failedSources],
                        summaryCount,
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
        expandedSummaryMessageIds: [
            {} as Record<string, boolean>,
            {
                toggleSummaryMessages: (state, { summaryId }) => ({
                    ...state,
                    [summaryId]: !state[summaryId],
                }),
            },
        ],
        supportTicketMessages: [
            {} as Record<string, PaginatedAccountSupportTicketMessageListApi>,
            {
                loadSupportTicketMessagesSuccess: (state, { ticketId, messages }) => ({
                    ...state,
                    [ticketId]: messages,
                }),
            },
        ],
        supportTicketMessagesLoading: [
            {} as Record<string, boolean>,
            {
                loadSupportTicketMessages: (state, { ticketId }) => ({ ...state, [ticketId]: true }),
                loadSupportTicketMessagesSuccess: (state, { ticketId }) => ({ ...state, [ticketId]: false }),
                loadSupportTicketMessagesFailure: (state, { ticketId }) => ({ ...state, [ticketId]: false }),
            },
        ],
        supportTicketMessageErrors: [
            {} as Record<string, boolean>,
            {
                loadSupportTicketMessages: (state, { ticketId }) => ({ ...state, [ticketId]: false }),
                loadSupportTicketMessagesSuccess: (state, { ticketId }) => ({ ...state, [ticketId]: false }),
                loadSupportTicketMessagesFailure: (state, { ticketId }) => ({ ...state, [ticketId]: true }),
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
        olderConversationCount: [
            (selectors) => [selectors.conversationsResult],
            (result: AccountConversationsResult): number => {
                const conversations: AccountConversation[] = result.conversations ?? []
                const loadedEmailCount = conversations.filter(({ source }) => source === 'email').length
                const loadedSummaryCount = conversations.filter(({ source }) => source === 'slack').length
                return (
                    Math.max(0, result.emailCount - loadedEmailCount) +
                    Math.max(0, result.summaryCount - loadedSummaryCount)
                )
            },
        ],
    }),
    listeners(({ actions, props, values }) => ({
        openConversation: ({ conversationId }) => {
            if (!conversationId.startsWith('support:')) {
                return
            }
            const ticketId = conversationId.slice('support:'.length)
            if (!values.supportTicketMessages[ticketId] && !values.supportTicketMessagesLoading[ticketId]) {
                actions.loadSupportTicketMessages(ticketId)
            }
        },
        loadSupportTicketMessages: async ({ ticketId }) => {
            try {
                const messages = await accountsSupportTicketMessagesList(
                    String(values.currentTeamId),
                    props.accountId,
                    ticketId,
                    { limit: 200, offset: 0 }
                )
                actions.loadSupportTicketMessagesSuccess(ticketId, messages)
            } catch (error) {
                posthog.captureException(error as Error, {
                    scope: 'accountConversationsLogic.loadSupportTicketMessages',
                })
                actions.loadSupportTicketMessagesFailure(ticketId)
            }
        },
    })),
    afterMount(({ actions }) => actions.loadConversations()),
])
