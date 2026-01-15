import { actions, connect, kea, listeners, path, reducers, selectors } from 'kea'
import { subscriptions } from 'kea-subscriptions'
import posthog from 'posthog-js'

import { lemonToast } from 'lib/lemon-ui/LemonToast/LemonToast'

import { sidePanelStateLogic } from '~/layout/navigation-3000/sidepanel/sidePanelStateLogic'

import type { ChatMessage, SidePanelViewState, Ticket } from '../../types'
import type { sidepanelTicketsLogicType } from './sidepanelTicketsLogicType'

export const sidepanelTicketsLogic = kea<sidepanelTicketsLogicType>([
    path(['products', 'conversations', 'frontend', 'components', 'SidePanel', 'sidepanelTicketsLogic']),
    connect({
        values: [sidePanelStateLogic, ['sidePanelOpen']],
    }),
    actions({
        loadTickets: true,
        setTickets: (tickets: Ticket[]) => ({ tickets }),
        loadMessages: (ticketId: string) => ({ ticketId }),
        setMessages: (messages: ChatMessage[]) => ({ messages }),
        setHasMoreMessages: (hasMore: boolean) => ({ hasMore }),
        setTicketsLoading: (loading: boolean) => ({ loading }),
        setMessagesLoading: (loading: boolean) => ({ loading }),
        markAsRead: (ticketId: string) => ({ ticketId }),
        setMessageSending: (sending: boolean) => ({ sending }),
        setView: (view: SidePanelViewState) => ({ view }),
        setCurrentTicket: (ticket: Ticket) => ({ ticket }),
    }),
    reducers({
        view: [
            'list' as SidePanelViewState,
            {
                setView: (_, { view }) => view,
            },
        ],
        tickets: [
            [] as Ticket[],
            {
                setTickets: (_, { tickets }) => tickets,
            },
        ],
        messages: [
            [] as ChatMessage[],
            {
                setMessages: (_, { messages }) => messages,
            },
        ],
        hasMoreMessages: [
            false,
            {
                setHasMoreMessages: (_, { hasMore }) => hasMore,
            },
        ],
        ticketsLoading: [
            false,
            {
                setTicketsLoading: (_, { loading }) => loading,
            },
        ],
        currentTicket: [
            null as Ticket | null,
            {
                setCurrentTicket: (_, { ticket }) => ticket,
            },
        ],
        messagesLoading: [
            false,
            {
                setMessagesLoading: (_, { loading }) => loading,
            },
        ],
        messageSending: [
            false,
            {
                setMessageSending: (_, { sending }) => sending,
            },
        ],
        message: [
            '' as string,
            {
                setMessage: (_, { message }) => message,
            },
        ],
    }),
    selectors({}),
    listeners(({ actions, values }) => ({
        loadTickets: async () => {
            actions.setTicketsLoading(true)
            try {
                const response = await posthog.conversations.getTickets({ limit: 50 })
                if (response) {
                    actions.setTickets(response.results as Ticket[])
                }
            } catch (e) {
                console.error('Failed to load tickets:', e)
                lemonToast.error('Failed to load tickets. Please try again.')
                actions.incrementPollingFailures()
            } finally {
                actions.setTicketsLoading(false)
            }
        },
        loadMessages: async ({ ticketId }) => {
            actions.setMessagesLoading(true)
            try {
                const response = await posthog.conversations.getMessages(ticketId)
                if (response) {
                    actions.setMessages(response.messages as ChatMessage[])
                    actions.setHasMoreMessages(response.has_more)
                }
            } catch (e) {
                console.error('Failed to load messages:', e)
                lemonToast.error('Failed to load messages. Please try again.')
            } finally {
                actions.setMessagesLoading(false)
            }
        },
        sendMessage: async () => {
            if (!values.message) {
                return
            }
            actions.setMessageSending(true)
            try {
                // If we're in "new" view, force creation of a new ticket
                const forceNewTicket = values.view === 'new'

                const response = await posthog.conversations.sendMessage(values.message, {}, forceNewTicket)
                if (response) {
                    // If we just created a new ticket, set it as current and switch to chat view
                    if (values.view === 'new') {
                        actions.setCurrentTicket({
                            id: response.ticket_id,
                            status: response.ticket_status,
                            message_count: 1,
                            created_at: response.created_at,
                            unread_customer_count: 0,
                            last_message_text: response.last_message_text,
                            last_message_at: response.last_message_at,
                        })
                        actions.setView('ticket')
                    }
                    actions.loadTickets()
                    actions.loadMessages(response.ticket_id)
                    lemonToast.success('Message sent!')
                    actions.setMessage('') // Clear the message input
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
    subscriptions(({ actions }) => ({
        sidePanelOpen: (open: boolean) => {
            if (open) {
                actions.loadTickets()
            }
        },
    })),
])
