import { actions, afterMount, beforeUnmount, kea, key, listeners, path, props, reducers } from 'kea'
import { loaders } from 'kea-loaders'

import { lemonToast } from '@posthog/lemon-ui'

import api from '~/lib/api'
import type { CommentType } from '~/types'

import type { TicketPriority, TicketStatus } from '../../types'
// NOTE: Run `pnpm typegen` to generate this type after making changes to the logic
import type { conversationsTicketSceneLogicType } from './conversationsTicketSceneLogicType'

const MESSAGE_POLL_INTERVAL = 5000 // 5 seconds

export const conversationsTicketSceneLogic = kea<conversationsTicketSceneLogicType>([
    path(['products', 'conversations', 'frontend', 'scenes', 'ticket', 'conversationsTicketSceneLogic']),
    props({ id: 'new' as string | number }),
    key((props) => props.id),
    actions({
        loadTicket: true,
        loadMessages: true,
        loadOlderMessages: true,
        setStatus: (status: TicketStatus) => ({ status }),
        setPriority: (priority: TicketPriority) => ({ priority }),
        setAssignedTo: (assignedTo: number | string) => ({ assignedTo }),
        sendMessage: (content: string) => ({ content }),
        updateTicket: true,
        setPollingInterval: (interval: number) => ({ interval }),
    }),
    loaders(({ props, values }) => ({
        ticket: {
            loadTicket: async () => {
                if (props.id === 'new') {
                    return null
                }
                return await api.conversationsTickets.get(props.id.toString())
            },
            updateTicket: async () => {
                if (props.id === 'new') {
                    return null
                }
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
                // Always include assigned_to, convert 'All users' to null
                data.assigned_to =
                    values.assignedTo === 'All users' || !values.assignedTo
                        ? null
                        : typeof values.assignedTo === 'string'
                          ? parseInt(values.assignedTo, 10)
                          : values.assignedTo

                return await api.conversationsTickets.update(props.id.toString(), data)
            },
        },
        messages: [
            [] as CommentType[],
            {
                loadMessages: async (_, breakpoint) => {
                    if (props.id === 'new') {
                        return []
                    }

                    await breakpoint(100)
                    const response = await api.comments.list({
                        scope: 'conversations_ticket',
                        item_id: props.id.toString(),
                    })
                    breakpoint()
                    // Reverse to show oldest first (bottom = newest)
                    return (response.results || []).reverse()
                },
            },
        ],
        messageSending: [
            false,
            {
                sendMessage: async ({ content }) => {
                    if (props.id === 'new') {
                        return false
                    }

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
                    return false
                },
            },
        ],
    })),
    reducers({
        status: [
            null as TicketStatus | null,
            {
                setStatus: (_, { status }) => status,
                loadTicketSuccess: (_, { ticket }) => ticket?.status || null,
                updateTicketSuccess: (_, { ticket }) => ticket?.status || null,
            },
        ],
        priority: [
            null as TicketPriority | null,
            {
                setPriority: (_, { priority }) => priority,
                loadTicketSuccess: (_, { ticket }) => ticket?.priority || null,
                updateTicketSuccess: (_, { ticket }) => ticket?.priority || null,
            },
        ],
        assignedTo: [
            null as number | string | null,
            {
                setAssignedTo: (_, { assignedTo }) => assignedTo,
                loadTicketSuccess: (_, { ticket }) => ticket?.assigned_to || null,
                updateTicketSuccess: (_, { ticket }) => ticket?.assigned_to || null,
            },
        ],
        pollingInterval: [
            null as NodeJS.Timeout | null,
            {
                // Managed via listeners, not actions
            },
        ],
        messages: {
            loadOlderMessagesSuccess: (state, { olderMessages }) => [...olderMessages, ...state],
        },
        hasMoreMessages: [
            true,
            {
                loadMessagesSuccess: (_, { messages }) => messages.length >= 100,
                loadOlderMessagesSuccess: (_, { hasMore }) => hasMore,
            },
        ],
        olderMessagesLoading: [
            false,
            {
                loadOlderMessages: () => true,
                loadOlderMessagesSuccess: () => false,
                loadOlderMessagesFailure: () => false,
            },
        ],
    }),
    listeners(({ actions, values, props }) => ({
        loadOlderMessages: async () => {
            const currentMessages = values.messages
            if (props.id === 'new' || currentMessages.length === 0 || !values.hasMoreMessages) {
                actions.loadOlderMessagesSuccess({ olderMessages: [], hasMore: false })
                return
            }

            try {
                // Get the oldest message to use as cursor
                const oldestMessage = currentMessages[0]
                const response = await api.comments.list({
                    scope: 'conversations_ticket',
                    item_id: props.id.toString(),
                })

                const allMessages = response.results || []
                // Find messages older than our oldest message
                const olderMessages = allMessages
                    .filter((msg) => new Date(msg.created_at) < new Date(oldestMessage.created_at))
                    .reverse()

                actions.loadOlderMessagesSuccess({
                    olderMessages,
                    hasMore: olderMessages.length > 0,
                })
            } catch (error) {
                actions.loadOlderMessagesFailure({ error })
            }
        },
        sendMessageSuccess: () => {
            lemonToast.success('Message sent')
            // Small delay to ensure DB write is complete before reloading
            setTimeout(() => {
                actions.loadMessages()
            }, 300)
        },
        sendMessageFailure: () => {
            lemonToast.error('Failed to send message')
        },
        updateTicketSuccess: () => {
            lemonToast.success('Ticket updated')
        },
        updateTicketFailure: () => {
            lemonToast.error('Failed to update ticket')
        },
        loadTicketSuccess: () => {
            // Start polling for messages when ticket loads successfully
            actions.loadMessages()

            // Clear any existing interval
            if (values.pollingInterval) {
                clearInterval(values.pollingInterval)
            }

            // Start new polling interval
            values.pollingInterval = setInterval(() => {
                actions.loadMessages()
            }, MESSAGE_POLL_INTERVAL)
        },
    })),
    afterMount(({ actions, props }) => {
        if (props.id !== 'new') {
            actions.loadTicket()
        }
    }),
    beforeUnmount(({ values }) => {
        // Clear polling interval on unmount
        if (values.pollingInterval) {
            clearInterval(values.pollingInterval)
            values.pollingInterval = null
        }
    }),
])
