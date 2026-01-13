import { actions, afterMount, beforeUnmount, kea, key, listeners, path, props, reducers, selectors } from 'kea'

import { lemonToast } from '@posthog/lemon-ui'

import api from '~/lib/api'
import type { CommentType } from '~/types'

import type { ChatMessage, Ticket, TicketPriority, TicketStatus } from '../../types'
import type { conversationsTicketSceneLogicType } from './conversationsTicketSceneLogicType'

const MESSAGE_POLL_INTERVAL = 5000 // 5 seconds

export const conversationsTicketSceneLogic = kea<conversationsTicketSceneLogicType>([
    path(['products', 'conversations', 'frontend', 'scenes', 'ticket', 'conversationsTicketSceneLogic']),
    props({ id: 'new' as string | number }),
    key((props) => props.id),
    actions({
        loadTicket: true,
        setTicket: (ticket: Ticket | null) => ({ ticket }),
        setTicketLoading: (loading: boolean) => ({ loading }),
        updateTicket: true,

        loadMessages: true,
        setMessages: (messages: CommentType[]) => ({ messages }),
        setMessagesLoading: (loading: boolean) => ({ loading }),

        loadOlderMessages: true,
        setOlderMessages: (olderMessages: CommentType[]) => ({ olderMessages }),
        setOlderMessagesLoading: (loading: boolean) => ({ loading }),
        setHasMoreMessages: (hasMore: boolean) => ({ hasMore }),

        sendMessage: (content: string) => ({ content }),
        setMessageSending: (sending: boolean) => ({ sending }),

        setStatus: (status: TicketStatus) => ({ status }),
        setPriority: (priority: TicketPriority) => ({ priority }),
        setAssignedTo: (assignedTo: number | string) => ({ assignedTo }),
    }),
    reducers({
        ticket: [
            null as Ticket | null,
            {
                setTicket: (_, { ticket }) => ticket,
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
        assignedTo: [
            null as number | string | null,
            {
                setAssignedTo: (_, { assignedTo }) => assignedTo,
                setTicket: (_, { ticket }) => ticket?.assigned_to || null,
            },
        ],
        messages: [
            [] as CommentType[],
            {
                setMessages: (_, { messages }) => messages,
                setOlderMessages: (state, { olderMessages }) => [...olderMessages, ...state],
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
    }),
    selectors({
        chatMessages: [
            (s) => [s.messages, s.ticket],
            (messages: CommentType[], ticket: Ticket | null): ChatMessage[] =>
                messages.map((message) => {
                    const authorType = message.item_context?.author_type || 'customer'
                    let displayName = 'Customer'
                    if (message.created_by) {
                        displayName =
                            [message.created_by.first_name, message.created_by.last_name].filter(Boolean).join(' ') ||
                            message.created_by.email
                    } else if (authorType === 'customer' && ticket?.anonymous_traits) {
                        displayName = ticket.anonymous_traits.name || ticket.anonymous_traits.email || 'Customer'
                    }

                    return {
                        id: message.id,
                        content: message.content || '',
                        authorType: authorType === 'support' ? 'human' : authorType,
                        authorName: displayName,
                        createdAt: message.created_at,
                    }
                }),
        ],
    }),
    listeners(({ actions, values, props, cache }) => ({
        loadTicket: async () => {
            if (props.id === 'new') {
                actions.setTicket(null)
                return
            }
            try {
                const ticket = await api.conversationsTickets.get(props.id.toString())
                actions.setTicket(ticket)
                actions.loadMessages()

                // Clear any existing interval
                if (cache.pollingInterval) {
                    clearInterval(cache.pollingInterval)
                }

                // Start new polling interval
                cache.pollingInterval = setInterval(() => {
                    actions.loadMessages()
                }, MESSAGE_POLL_INTERVAL)
            } catch {
                lemonToast.error('Failed to load ticket')
                actions.setTicketLoading(false)
            }
        },
        updateTicket: async () => {
            if (props.id === 'new') {
                return
            }
            try {
                const data: Partial<{
                    status: string
                    priority: string
                    assigned_to: number | null
                }> = {}

                if (values.status) {
                    data.status = values.status
                }
                if (values.priority) {
                    data.priority = values.priority
                }
                data.assigned_to =
                    values.assignedTo === 'All users' || !values.assignedTo
                        ? null
                        : typeof values.assignedTo === 'string'
                          ? parseInt(values.assignedTo, 10)
                          : values.assignedTo

                const ticket = await api.conversationsTickets.update(props.id.toString(), data)
                actions.setTicket(ticket)
                lemonToast.success('Ticket updated')
            } catch {
                lemonToast.error('Failed to update ticket')
            }
        },
        loadMessages: async () => {
            if (props.id === 'new') {
                actions.setMessages([])
                return
            }
            try {
                const response = await api.comments.list({
                    scope: 'conversations_ticket',
                    item_id: props.id.toString(),
                })
                // Reverse to show oldest first (bottom = newest)
                actions.setMessages((response.results || []).reverse())
            } catch {
                lemonToast.error('Failed to load messages')
                actions.setMessagesLoading(false)
            }
        },
        loadOlderMessages: async () => {
            const currentMessages = values.messages
            if (props.id === 'new' || currentMessages.length === 0 || !values.hasMoreMessages) {
                actions.setOlderMessagesLoading(false)
                actions.setHasMoreMessages(false)
                return
            }

            try {
                const oldestMessage = currentMessages[0]
                const response = await api.comments.list({
                    scope: 'conversations_ticket',
                    item_id: props.id.toString(),
                })

                const allMessages = response.results || []
                const olderMessages = allMessages
                    .filter((msg) => new Date(msg.created_at) < new Date(oldestMessage.created_at))
                    .reverse()

                actions.setOlderMessages(olderMessages)
                actions.setHasMoreMessages(olderMessages.length > 0)
            } catch {
                lemonToast.error('Failed to load older messages')
                actions.setOlderMessagesLoading(false)
            }
        },
        sendMessage: async ({ content }) => {
            if (props.id === 'new') {
                actions.setMessageSending(false)
                return
            }
            try {
                await api.comments.create(
                    {
                        content,
                        scope: 'conversations_ticket',
                        item_id: props.id.toString(),
                        item_context: {
                            author_type: 'support',
                            is_private: false,
                        },
                    },
                    {}
                )
                lemonToast.success('Message sent')
                actions.setMessageSending(false)
                setTimeout(() => {
                    actions.loadMessages()
                }, 300)
            } catch {
                lemonToast.error('Failed to send message')
                actions.setMessageSending(false)
            }
        },
    })),
    afterMount(({ actions, props }) => {
        if (props.id !== 'new') {
            actions.loadTicket()
        }
    }),
    beforeUnmount(({ cache }) => {
        if (cache.pollingInterval) {
            clearInterval(cache.pollingInterval)
        }
    }),
])
