import { actions, afterMount, beforeUnmount, kea, listeners, path, reducers, selectors } from 'kea'
import posthog from 'posthog-js'

import { lemonToast } from 'lib/lemon-ui/LemonToast/LemonToast'
import { userLogic } from 'scenes/userLogic'

import { sidePanelStateLogic } from '~/layout/navigation-3000/sidepanel/sidePanelStateLogic'

import type { ChatMessage, ConversationMessage, ConversationTicket, SidePanelViewState } from '../../types'
import type { sidePanelConversationsLogicType } from './sidePanelConversationsLogicType'

const TICKETS_POLL_INTERVAL = 30000 // 30 seconds

export const sidePanelConversationsLogic = kea<sidePanelConversationsLogicType>([
    path([
        'products',
        'conversations',
        'frontend',
        'components',
        'SidePanelConversations',
        'sidePanelConversationsLogic',
    ]),
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
        loadTickets: true,
        selectTicket: (ticketId: string) => ({ ticketId }),
        loadMessages: (ticketId: string) => ({ ticketId }),
        sendMessage: (content: string, onSuccess?: () => void) => ({ content, onSuccess }),
        markAsRead: (ticketId: string) => ({ ticketId }),
        goBack: true,
        startNewConversation: true,
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
    listeners(({ actions, values }) => ({
        loadTickets: async () => {
            try {
                const response = await posthog.conversations.getTickets({ limit: 50 })
                if (response) {
                    actions.setTickets(response.results as ConversationTicket[])
                }
            } catch (e) {
                console.error('Failed to load tickets:', e)
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
                }
            } catch (e) {
                console.error('Failed to load messages:', e)
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
    })),
    afterMount(({ actions, values, cache }) => {
        // Check if conversations are ready and load tickets
        const initConversations = async (): Promise<void> => {
            try {
                // Check if conversations are enabled (via remote config)
                if (posthog.conversations.isAvailable()) {
                    actions.setConversationsReady(true)
                    actions.loadTickets()
                } else {
                    // Wait a bit for remote config to load, then try again
                    await new Promise((resolve) => setTimeout(resolve, 1000))
                    if (posthog.conversations.isAvailable()) {
                        actions.setConversationsReady(true)
                        actions.loadTickets()
                    } else {
                        console.warn('Conversations not enabled for this team')
                    }
                }
            } catch (e) {
                console.error('Failed to initialize conversations:', e)
            }
        }
        void initConversations()

        // Start polling interval - checks conditions inside
        cache.pollingInterval = setInterval(() => {
            const { sidePanelOpen } = sidePanelStateLogic.values
            if (sidePanelOpen && values.conversationsReady && values.tickets.length > 0) {
                actions.loadTickets()
                // Also reload messages if viewing a chat
                if (values.view === 'chat' && values.currentTicket) {
                    actions.loadMessages(values.currentTicket.id)
                }
            }
        }, TICKETS_POLL_INTERVAL)
    }),
    beforeUnmount(({ cache }) => {
        if (cache.pollingInterval) {
            clearInterval(cache.pollingInterval)
        }
    }),
])
