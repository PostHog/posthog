import { actions, afterMount, kea, listeners, path, reducers, selectors } from 'kea'
import posthog from 'posthog-js'

import { lemonToast } from 'lib/lemon-ui/LemonToast/LemonToast'
import { userLogic } from 'scenes/userLogic'

import type { sidePanelConversationsLogicType } from './sidePanelConversationsLogicType'

export interface ConversationTicket {
    id: string
    status: 'new' | 'open' | 'pending' | 'on_hold' | 'resolved'
    last_message?: string
    last_message_at?: string
    message_count: number
    created_at: string
    unread_count?: number
}

export interface ConversationMessage {
    id: string
    content: string
    author_type: 'customer' | 'AI' | 'human'
    author_name?: string
    created_at: string
    is_private: boolean
}

type ViewState = 'list' | 'chat' | 'new'

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
        setView: (view: ViewState) => ({ view }),
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
        sendMessage: (content: string) => ({ content }),
        markAsRead: (ticketId: string) => ({ ticketId }),
        goBack: true,
        startNewConversation: true,
    }),
    reducers({
        view: [
            'list' as ViewState,
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
        sendMessage: async ({ content }) => {
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
                }
            } catch (e) {
                console.error('Failed to send message:', e)
                lemonToast.error('Failed to send message. Please try again.')
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
    afterMount(({ actions }) => {
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
    }),
])
