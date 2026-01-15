import { actions, connect, kea, listeners, path, reducers, selectors } from 'kea'
import { subscriptions } from 'kea-subscriptions'
import posthog from 'posthog-js'

import { lemonToast } from 'lib/lemon-ui/LemonToast/LemonToast'

import { sidePanelStateLogic } from '~/layout/navigation-3000/sidepanel/sidePanelStateLogic'

import type { ChatMessage, ConversationMessage, ConversationTicket, SidePanelViewState } from '../../types'
import type { sidepanelTicketsLogicType } from './sidepanelTicketsLogicType'

export const sidepanelTicketsLogic = kea<sidepanelTicketsLogicType>([
    path(['products', 'conversations', 'frontend', 'components', 'SidePanel', 'sidepanelTicketsLogic']),
    connect({
        values: [sidePanelStateLogic, ['sidePanelOpen']],
    }),
    actions({
        loadTickets: true,
        setTickets: (tickets: ConversationTicket[]) => ({ tickets }),
        loadMessages: (ticketId: string) => ({ ticketId }),
        setMessages: (messages: ChatMessage[]) => ({ messages }),
        setHasMoreMessages: (hasMore: boolean) => ({ hasMore }),
        setTicketsLoading: (loading: boolean) => ({ loading }),
        setMessagesLoading: (loading: boolean) => ({ loading }),
        markAsRead: (ticketId: string) => ({ ticketId }),
        setMessageSending: (sending: boolean) => ({ sending }),
        setView: (view: SidePanelViewState) => ({ view }),
        setCurrentTicket: (ticket: ConversationTicket) => ({ ticket }),
        sendMessage: (content: string, onSuccess: () => void) => ({ content, onSuccess }),
    }),
    reducers({
        view: [
            'list' as SidePanelViewState,
            {
                setView: (_, { view }) => view,
            },
        ],
        tickets: [
            [] as ConversationTicket[],
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
            null as ConversationTicket | null,
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
    }),
    selectors({}),
    listeners(({ actions, values }) => ({
        loadTickets: async () => {
            if (!posthog.conversations) {
                return
            }
            actions.setTicketsLoading(true)
            try {
                const response = await posthog.conversations.getTickets({ limit: 50 })
                if (response) {
                    actions.setTickets(response.results as ConversationTicket[])
                }
            } catch (e) {
                console.error('Failed to load tickets:', e)
                lemonToast.error('Failed to load tickets. Please try again.')
            } finally {
                actions.setTicketsLoading(false)
            }
        },
        loadMessages: async ({ ticketId }) => {
            if (!ticketId || !posthog.conversations) {
                return
            }
            actions.setMessagesLoading(true)
            try {
                const response = await posthog.conversations.getMessages(ticketId)
                if (response) {
                    const transformedMessages: ChatMessage[] = (response.messages as ConversationMessage[]).map(
                        (msg) => ({
                            id: msg.id,
                            content: msg.content,
                            authorType: msg.author_type,
                            authorName: msg.author_name || '',
                            createdAt: msg.created_at,
                        })
                    )
                    actions.setMessages(transformedMessages)
                    actions.setHasMoreMessages(response.has_more)
                }
            } catch (e) {
                console.error('Failed to load messages:', e)
                lemonToast.error('Failed to load messages. Please try again.')
            } finally {
                actions.setMessagesLoading(false)
            }
        },
        sendMessage: async ({ content, onSuccess }) => {
            if (!content.trim() || values.messageSending || !posthog.conversations) {
                return
            }
            actions.setMessageSending(true)
            try {
                // If we're in "new" view, force creation of a new ticket
                const forceNewTicket = values.view === 'new'

                const response = await posthog.conversations.sendMessage(content, {}, forceNewTicket)
                if (response) {
                    // If we just created a new ticket, set it as current and switch to chat view
                    if (values.view === 'new') {
                        actions.setCurrentTicket({
                            id: response.ticket_id,
                            status: response.ticket_status,
                            message_count: 1,
                            created_at: response.created_at,
                            unread_count: 0,
                            last_message: content,
                            last_message_at: response.created_at,
                        })
                        actions.setView('ticket')
                    }
                    actions.loadTickets()
                    actions.loadMessages(response.ticket_id)
                    lemonToast.success('Message sent!')
                    onSuccess()
                }
            } catch (e) {
                console.error('Failed to send message:', e)
                lemonToast.error('Failed to send message. Please try again.')
            } finally {
                actions.setMessageSending(false)
            }
        },
        markAsRead: async ({ ticketId }) => {
            if (!ticketId || !posthog.conversations) {
                return
            }
            try {
                await posthog.conversations.markAsRead(ticketId)
            } catch (e) {
                console.error('Failed to mark as read:', e)
            }
        },
        setCurrentTicket: ({ ticket }: { ticket: ConversationTicket }) => {
            actions.setView('ticket')
            actions.loadMessages(ticket.id)
            actions.markAsRead(ticket.id)
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
