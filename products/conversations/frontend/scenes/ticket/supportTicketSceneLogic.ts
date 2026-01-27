import { actions, afterMount, beforeUnmount, kea, key, listeners, path, props, reducers, selectors } from 'kea'
import { loaders } from 'kea-loaders'

import { lemonToast } from '@posthog/lemon-ui'

import api from '~/lib/api'
import { PERSON_DISPLAY_NAME_COLUMN_NAME } from '~/lib/constants'
import { defaultDataTableColumns } from '~/queries/nodes/DataTable/utils'
import { DataTableNode, NodeKind } from '~/queries/schema/schema-general'
import type { CommentType, PersonType } from '~/types'
import { PropertyFilterType, PropertyOperator } from '~/types'

import type { TicketAssignee } from '../../components/Assignee'
import type { ChatMessage, Ticket, TicketPriority, TicketStatus } from '../../types'
import type { supportTicketSceneLogicType } from './supportTicketSceneLogicType'

const MESSAGE_POLL_INTERVAL = 5000 // 5 seconds

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

export const supportTicketSceneLogic = kea<supportTicketSceneLogicType>([
    path(['products', 'conversations', 'frontend', 'scenes', 'ticket', 'supportTicketSceneLogic']),
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

        sendMessage: (content: string, onSuccess?: () => void) => ({ content, onSuccess }),
        setMessageSending: (sending: boolean) => ({ sending }),

        setStatus: (status: TicketStatus) => ({ status }),
        setPriority: (priority: TicketPriority) => ({ priority }),
        setAssignee: (assignee: TicketAssignee) => ({ assignee }),

        // Session context actions
        loadPerson: true,
        loadPreviousTickets: true,
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
        previousTickets: [
            [] as Ticket[],
            {
                loadPreviousTickets: async (): Promise<Ticket[]> => {
                    const person = values.person
                    const currentTicketId = props.id

                    if (!person?.distinct_ids || person.distinct_ids.length === 0) {
                        return []
                    }

                    try {
                        // Load all tickets for any of this person's distinct_ids (in parallel)
                        const responses = await Promise.all(
                            person.distinct_ids.map((distinctId: string) =>
                                api.conversationsTickets.list({ distinct_id: distinctId })
                            )
                        )
                        const allTickets = responses.flatMap((r) => r.results || [])

                        // Deduplicate by ID and exclude current ticket
                        const uniqueTickets = Array.from(
                            new Map(allTickets.map((ticket) => [ticket.id, ticket])).values()
                        ).filter((ticket) => ticket.id !== currentTicketId)

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
    })),
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
        assignee: [
            null as TicketAssignee,
            {
                setAssignee: (_, { assignee }) => assignee,
                setTicket: (_, { ticket }) => ticket?.assignee || null,
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
            (s) => [s.messages, s.ticket],
            (messages: CommentType[], ticket: Ticket | null): ChatMessage[] =>
                messages.map((message) => {
                    const authorType = message.item_context?.author_type || 'customer'
                    let displayName = 'Customer'
                    if (message.created_by) {
                        displayName =
                            [message.created_by.first_name, message.created_by.last_name].filter(Boolean).join(' ') ||
                            message.created_by.email ||
                            'Support'
                    } else if (authorType === 'customer' && ticket?.anonymous_traits) {
                        displayName = ticket.anonymous_traits.name || ticket.anonymous_traits.email || 'Customer'
                    }

                    return {
                        id: message.id,
                        content: message.content || '',
                        authorType: authorType === 'support' ? 'human' : authorType,
                        authorName: displayName,
                        createdBy: message.created_by,
                        createdAt: message.created_at,
                    }
                }),
        ],
        eventsQuery: [
            (s) => [s.person, s.ticket],
            (person: PersonType | null, ticket: Ticket | null): DataTableNode | null => {
                if (!person?.id) {
                    return null
                }
                return createEventsQuery(person.id, ticket?.session_id, ticket?.created_at)
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

                // Load session context data
                actions.loadPerson()

                // Clear any existing interval
                if (cache.pollingInterval) {
                    clearInterval(cache.pollingInterval)
                }

                // Start new polling interval
                cache.pollingInterval = setInterval(() => {
                    actions.loadMessages()
                }, MESSAGE_POLL_INTERVAL)
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
        updateTicket: async () => {
            if (props.id === 'new') {
                return
            }
            try {
                const data: Partial<{
                    status: string
                    priority: string
                    assignee: TicketAssignee
                }> = {}

                if (values.status) {
                    data.status = values.status
                }
                if (values.priority) {
                    data.priority = values.priority
                }
                data.assignee = values.assignee

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
        sendMessage: async ({ content, onSuccess }) => {
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
                onSuccess?.()
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
