import { actions, afterMount, beforeUnmount, connect, kea, listeners, path, reducers, selectors } from 'kea'
import { subscriptions } from 'kea-subscriptions'
import posthog from 'posthog-js'

import { lemonToast } from 'lib/lemon-ui/LemonToast/LemonToast'
import { userLogic } from 'scenes/userLogic'

import { sidePanelStateLogic } from '~/layout/navigation-3000/sidepanel/sidePanelStateLogic'

import type { ChatMessage, ConversationMessage, ConversationTicket, SidePanelViewState } from '../../types'
import type { sidePanelConversationsLogicType } from './sidePanelConversationsLogicType'

const TICKETS_POLL_INTERVAL = 30000 // 30 seconds
const MAX_POLLING_FAILURES = 3 // Stop polling after 3 consecutive failures

export const sidePanelConversationsLogic = kea<sidePanelConversationsLogicType>([
    path([
        'products',
        'conversations',
        'frontend',
        'components',
        'SidePanelConversations',
        'sidePanelConversationsLogic',
    ]),
    connect({
        values: [sidePanelStateLogic, ['sidePanelOpen']],
    }),
    actions({
        setView: (view: SidePanelViewState) => ({ view }),
        setTickets: (tickets: ConversationTicket[]) => ({ tickets }),
        setTicketsLoading: (loading: boolean) => ({ loading }),
        setCurrentTicket: (ticket: ConversationTicket | null) => ({ ticket }),
        setMessages: (messages: ConversationMessage[]) => ({ messages }),
        setMessagesLoading: (loading: boolean) => ({ loading }),
        setMessageSending: (sending: boolean) => ({ sending }),
        setHasMoreMessages: (hasMore: boolean) => ({ hasMore }),
        setConversationsReady: (ready: boolean) => ({ ready }),
        setConversationsInitialized: (initialized: boolean) => ({ initialized }),
        incrementPollingFailures: true,
        resetPollingFailures: true,
        loadTickets: true,
        selectTicket: (ticketId: string) => ({ ticketId }),
        loadMessages: (ticketId: string) => ({ ticketId }),
        sendMessage: (content: string, onSuccess?: () => void) => ({ content, onSuccess }),
        markAsRead: (ticketId: string) => ({ ticketId }),
        goBack: true,
        startNewConversation: true,
        initConversations: true,
        startPolling: true,
        stopPolling: true,
    }),
    reducers({
        view: [
            'list' as SidePanelViewState,
            {
                setView: (_, { view }) => view,
                goBack: () => 'list',
                startNewConversation: () => 'new',
            },
        ],
        tickets: [
            [] as ConversationTicket[],
            {
                setTickets: (_, { tickets }) => tickets,
            },
        ],
        ticketsLoading: [
            false,
            {
                setTicketsLoading: (_, { loading }) => loading,
                loadTickets: () => true,
            },
        ],
        currentTicket: [
            null as ConversationTicket | null,
            {
                setCurrentTicket: (_, { ticket }) => ticket,
                goBack: () => null,
            },
        ],
        messages: [
            [] as ConversationMessage[],
            {
                setMessages: (_, { messages }) => messages,
                goBack: () => [],
            },
        ],
        messagesLoading: [
            false,
            {
                setMessagesLoading: (_, { loading }) => loading,
                loadMessages: () => true,
            },
        ],
        messageSending: [
            false,
            {
                setMessageSending: (_, { sending }) => sending,
            },
        ],
        hasMoreMessages: [
            false,
            {
                setHasMoreMessages: (_, { hasMore }) => hasMore,
            },
        ],
        conversationsReady: [
            false,
            {
                setConversationsReady: (_, { ready }) => ready,
            },
        ],
        conversationsInitialized: [
            false,
            {
                setConversationsInitialized: (_, { initialized }) => initialized,
            },
        ],
        pollingFailures: [
            0,
            {
                incrementPollingFailures: (state) => state + 1,
                resetPollingFailures: () => 0,
            },
        ],
    }),
    selectors({
        userName: [() => [userLogic.selectors.user], (user) => user?.first_name || user?.email || 'You'],
        userEmail: [() => [userLogic.selectors.user], (user) => user?.email || ''],
        chatMessages: [
            (s) => [s.messages, s.userName],
            (messages: ConversationMessage[], userName: string): ChatMessage[] =>
                messages.map((message) => ({
                    id: message.id,
                    content: message.content,
                    authorType: message.author_type,
                    authorName: message.author_name || (message.author_type === 'customer' ? userName : 'Support'),
                    createdAt: message.created_at,
                })),
        ],
    }),
    listeners(({ actions, values, cache }) => ({
        loadTickets: async () => {
            try {
                const response = await posthog.conversations.getTickets({ limit: 50 })
                if (response) {
                    actions.setTickets(response.results as ConversationTicket[])
                    actions.resetPollingFailures()
                }
            } catch (e) {
                console.error('Failed to load tickets:', e)
                lemonToast.error('Failed to load tickets. Please try again.')
                actions.incrementPollingFailures()
            } finally {
                actions.setTicketsLoading(false)
            }
        },
        selectTicket: async ({ ticketId }) => {
            const ticket = values.tickets.find((t) => t.id === ticketId)
            if (ticket) {
                actions.setCurrentTicket(ticket)
                actions.setView('chat')
                actions.loadMessages(ticketId)
                actions.markAsRead(ticketId)
                // Immediately update local state to clear unread count
                if (ticket.unread_count && ticket.unread_count > 0) {
                    actions.setTickets(values.tickets.map((t) => (t.id === ticketId ? { ...t, unread_count: 0 } : t)))
                }
            }
        },
        loadMessages: async ({ ticketId }) => {
            try {
                const response = await posthog.conversations.getMessages(ticketId)
                if (response) {
                    actions.setMessages(response.messages as ConversationMessage[])
                    actions.setHasMoreMessages(response.has_more)
                    actions.resetPollingFailures()
                }
            } catch (e) {
                console.error('Failed to load messages:', e)
                lemonToast.error('Failed to load messages. Please try again.')
                actions.incrementPollingFailures()
            } finally {
                actions.setMessagesLoading(false)
            }
        },
        sendMessage: async ({ content, onSuccess }) => {
            actions.setMessageSending(true)
            try {
                // If we're in "new" view, force creation of a new ticket
                const forceNewTicket = values.view === 'new'

                const response = await posthog.conversations.sendMessage(
                    content,
                    {
                        name: values.userName,
                        email: values.userEmail,
                    },
                    forceNewTicket
                )
                if (response) {
                    // If we just created a new ticket, set it as current and switch to chat view
                    if (values.view === 'new') {
                        actions.setCurrentTicket({
                            id: response.ticket_id,
                            status: response.ticket_status,
                            message_count: 1,
                            created_at: response.created_at,
                            unread_count: 0,
                        })
                        actions.setView('chat')
                        // Reload tickets in background to update the list
                        actions.loadTickets()
                    }
                    // Reload messages to show the new one
                    actions.loadMessages(response.ticket_id)
                    lemonToast.success('Message sent!')
                    // Call success callback to clear input
                    onSuccess?.()
                }
            } catch (e) {
                console.error('Failed to send message:', e)
                lemonToast.error('Failed to send message. Please try again.')
                // Don't call onSuccess - keep the message in the input
            } finally {
                actions.setMessageSending(false)
            }
        },
        markAsRead: async ({ ticketId }) => {
            try {
                await posthog.conversations.markAsRead(ticketId)
            } catch (e) {
                console.error('Failed to mark as read:', e)
            }
        },
        initConversations: () => {
            if (posthog.conversations.isAvailable()) {
                actions.setConversationsReady(true)
                actions.setConversationsInitialized(true)
                actions.loadTickets()
            } else {
                // Not available yet, mark as initialized but not ready
                // Will retry when side panel opens
                actions.setConversationsInitialized(true)
            }
        },
        startPolling: () => {
            if (cache.pollingInterval) {
                return // Already polling
            }
            cache.pollingInterval = setInterval(() => {
                if (
                    values.sidePanelOpen &&
                    values.conversationsReady &&
                    values.tickets.length > 0 &&
                    values.pollingFailures < MAX_POLLING_FAILURES
                ) {
                    if (!values.ticketsLoading) {
                        actions.loadTickets()
                    }
                    if (values.view === 'chat' && values.currentTicket && !values.messagesLoading) {
                        actions.loadMessages(values.currentTicket.id)
                    }
                }
            }, TICKETS_POLL_INTERVAL)
        },
        stopPolling: () => {
            if (cache.pollingInterval) {
                clearInterval(cache.pollingInterval)
                cache.pollingInterval = null
            }
        },
    })),
    subscriptions(({ actions, values }) => ({
        sidePanelOpen: (open: boolean) => {
            if (open) {
                // Check availability on-demand when panel opens
                if (!values.conversationsReady && posthog.conversations.isAvailable()) {
                    actions.setConversationsReady(true)
                    actions.loadTickets()
                }
                actions.startPolling()
            } else {
                actions.stopPolling()
            }
        },
    })),
    afterMount(({ actions }) => {
        actions.initConversations()
    }),
    beforeUnmount(({ actions }) => {
        actions.stopPolling()
    }),
])
