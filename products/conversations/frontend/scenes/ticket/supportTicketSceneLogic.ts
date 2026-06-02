import { JSONContent } from '@tiptap/core'
import { actions, afterMount, beforeUnmount, connect, kea, key, listeners, path, props, reducers, selectors } from 'kea'
import { loaders } from 'kea-loaders'
import { beforeUnload, router } from 'kea-router'

import { lemonToast } from '@posthog/lemon-ui'

import { dayjs } from 'lib/dayjs'
import { urls } from 'scenes/urls'

import { impersonationNoticeLogic } from '~/layout/navigation/ImpersonationNotice/impersonationNoticeLogic'
import api from '~/lib/api'
import { PERSON_DISPLAY_NAME_COLUMN_NAME } from '~/lib/constants'
import { CLOUD_HOSTNAMES } from '~/lib/constants'
import { defaultDataTableColumns } from '~/queries/nodes/DataTable/utils'
import { DataTableNode, NodeKind } from '~/queries/schema/schema-general'
import type { CommentType, PersonType } from '~/types'
import { PropertyFilterType, PropertyOperator, Region } from '~/types'

import type { TicketAssignee } from '../../components/Assignee'
import { supportTicketCounterLogic } from '../../supportTicketCounterLogic'
import type { ChatMessage, Ticket, TicketPriority, TicketStatus } from '../../types'
import { supportTicketsSceneLogic } from '../tickets/supportTicketsSceneLogic'
import type { supportTicketSceneLogicType } from './supportTicketSceneLogicType'

const MESSAGE_POLL_INTERVAL = 5000 // 5 seconds

function regionFromUrl(url?: string): Region | undefined {
    if (url) {
        try {
            const hostname = new URL(url).hostname
            for (const [region, domain] of Object.entries(CLOUD_HOSTNAMES)) {
                if (hostname === domain || hostname.endsWith(`.${domain}`)) {
                    return region as Region
                }
            }
        } catch {
            // ignore malformed URLs
        }
    }
    return undefined
}

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
    connect(() => ({
        actions: [supportTicketsSceneLogic, ['loadTickets']],
    })),
    actions({
        loadTicket: true,
        setTicket: (ticket: Ticket | null) => ({ ticket }),
        setTicketLoading: (loading: boolean) => ({ loading }),
        incrementUnreadCustomerCount: true,
        updateTicket: true,

        loadMessages: true,
        setMessages: (messages: CommentType[]) => ({ messages }),
        setMessagesLoading: (loading: boolean) => ({ loading }),

        loadOlderMessages: true,
        setOlderMessages: (olderMessages: CommentType[]) => ({ olderMessages }),
        setOlderMessagesLoading: (loading: boolean) => ({ loading }),
        setHasMoreMessages: (hasMore: boolean) => ({ hasMore }),

        sendMessage: (
            content: string,
            richContent: Record<string, unknown> | null,
            isPrivate: boolean,
            onSuccess?: () => void
        ) => ({
            content,
            richContent,
            isPrivate,
            onSuccess,
        }),
        setMessageSending: (sending: boolean) => ({ sending }),

        setStatus: (status: TicketStatus) => ({ status }),
        setPriority: (priority: TicketPriority) => ({ priority }),
        setAssignee: (assignee: TicketAssignee) => ({ assignee }),
        setTags: (tags: string[]) => ({ tags }),
        setSnoozedUntil: (snoozedUntil: string | null) => ({ snoozedUntil }),

        // Session context actions
        loadPerson: true,
        loadPreviousTickets: true,

        // Draft message state (persists across tab switches)
        setDraftContent: (content: JSONContent | null) => ({ content }),
        setDraftIsPrivate: (isPrivate: boolean) => ({ isPrivate }),

        // AI suggestion
        suggestReply: true,
        setSuggesting: (suggesting: boolean) => ({ suggesting }),
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
                        const response = await api.conversationsTickets.list({
                            distinct_ids: person.distinct_ids.join(','),
                        })
                        const allTickets = response.results || []

                        // Exclude current ticket
                        const uniqueTickets = allTickets.filter(
                            (ticket) => ticket.ticket_number !== parseInt(currentTicketId.toString())
                        )

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
                incrementUnreadCustomerCount: (state) =>
                    state ? { ...state, unread_customer_count: state.unread_customer_count + 1 } : state,
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
        tags: [
            [] as string[],
            {
                setTags: (_, { tags }) => tags,
                setTicket: (_, { ticket }) => ticket?.tags || [],
            },
        ],
        snoozedUntil: [
            null as string | null,
            {
                setSnoozedUntil: (_, { snoozedUntil }) => snoozedUntil,
                setTicket: (_, { ticket }) => ticket?.snoozed_until || null,
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
        draftContent: [
            null as JSONContent | null,
            {
                setDraftContent: (_, { content }) => content,
            },
        ],
        draftIsPrivate: [
            false,
            {
                setDraftIsPrivate: (_, { isPrivate }) => isPrivate,
            },
        ],
        suggesting: [
            false,
            {
                suggestReply: () => true,
                setSuggesting: (_, { suggesting }) => suggesting,
            },
        ],
    }),
    selectors({
        hasUnsavedChanges: [
            (s) => [s.status, s.priority, s.assignee, s.tags, s.snoozedUntil, s.ticket],
            (status, priority, assignee, tags, snoozedUntil, ticket): boolean => {
                if (!ticket) {
                    return false
                }
                return (
                    status !== ticket.status ||
                    priority !== ticket.priority ||
                    JSON.stringify(assignee) !== JSON.stringify(ticket.assignee) ||
                    JSON.stringify([...tags].sort()) !== JSON.stringify([...(ticket.tags || [])].sort()) ||
                    (snoozedUntil ? dayjs(snoozedUntil).unix() : null) !==
                        (ticket.snoozed_until ? dayjs(ticket.snoozed_until).unix() : null)
                )
            },
        ],
        hasPendingWork: [(s) => [s.hasUnsavedChanges], (hasUnsavedChanges): boolean => hasUnsavedChanges],
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
                    let displayName = 'Anonymous user'
                    if (message.created_by) {
                        displayName =
                            [message.created_by.first_name, message.created_by.last_name].filter(Boolean).join(' ') ||
                            message.created_by.email ||
                            'Support'
                    } else if (authorType === 'AI') {
                        displayName = 'PostHog Assistant'
                    } else if (authorType === 'customer') {
                        const slackAuthorName = message.item_context?.slack_author_name
                        const emailAuthorName = message.item_context?.email_from_name
                        if (slackAuthorName) {
                            displayName = slackAuthorName
                        } else if (emailAuthorName) {
                            displayName = emailAuthorName
                        } else {
                            displayName =
                                ticket?.person?.properties?.name ||
                                ticket?.person?.properties?.email ||
                                ticket?.anonymous_traits?.name ||
                                ticket?.anonymous_traits?.email ||
                                'Anonymous user'
                        }
                    }

                    return {
                        id: message.id,
                        content: message.content || '',
                        richContent: message.rich_content,
                        authorType: authorType === 'support' ? 'human' : authorType,
                        authorName: displayName,
                        createdBy: message.created_by,
                        createdAt: message.created_at,
                        isPrivate: message.item_context?.is_private || false,
                    }
                }),
        ],
        eventsQuery: [
            (s) => [s.ticket],
            (ticket: Ticket | null): DataTableNode | null => {
                // Use person from ticket (no extra API call needed)
                if (!ticket?.person?.id) {
                    return null
                }
                return createEventsQuery(ticket.person.id, ticket.session_id, ticket.created_at)
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

                // If accessed via UUID, redirect to ticket_number URL for cleaner URLs
                const isUuid = props.id.toString().includes('-')
                if (isUuid && ticket.ticket_number) {
                    router.actions.replace(urls.supportTicketDetail(ticket.ticket_number))
                    return
                }

                actions.setTicket(ticket)
                actions.loadMessages()

                impersonationNoticeLogic.findMounted()?.actions.setTicketContext({
                    ticketId: ticket.id,
                    email: ticket.anonymous_traits?.email || '',
                    region: regionFromUrl(ticket.session_context?.current_url),
                })

                // Load session context data
                actions.loadPerson()

                // Refresh the unread count since viewing a ticket marks it as read
                supportTicketCounterLogic.findMounted()?.actions.refreshCount()

                // Start message polling using disposables pattern
                cache.disposables.dispose('messagePolling')
                cache.disposables.add(() => {
                    const intervalId = setInterval(() => {
                        actions.loadMessages()
                    }, MESSAGE_POLL_INTERVAL)
                    return () => clearInterval(intervalId)
                }, 'messagePolling')
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
                    tags: string[]
                    snoozed_until: string | null
                }> = {}

                if (values.status && values.status !== values.ticket?.status) {
                    data.status = values.status
                }
                if (values.priority && values.priority !== values.ticket?.priority) {
                    data.priority = values.priority
                }
                data.assignee = values.assignee
                data.tags = values.tags
                data.snoozed_until = values.snoozedUntil

                const ticket = await api.conversationsTickets.update(props.id.toString(), data)
                actions.setTicket(ticket)
                lemonToast.success('Ticket updated')
                actions.loadTickets()
            } catch {
                lemonToast.error('Failed to update ticket')
            }
        },
        loadMessages: async () => {
            if (props.id === 'new' || !values.ticket?.id) {
                actions.setMessages([])
                return
            }
            try {
                const response = await api.comments.list({
                    scope: 'conversations_ticket',
                    item_id: values.ticket.id,
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
            if (props.id === 'new' || !values.ticket?.id || currentMessages.length === 0 || !values.hasMoreMessages) {
                actions.setOlderMessagesLoading(false)
                actions.setHasMoreMessages(false)
                return
            }

            try {
                const oldestMessage = currentMessages[0]
                const response = await api.comments.list({
                    scope: 'conversations_ticket',
                    item_id: values.ticket.id,
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
        suggestReply: async () => {
            try {
                await api.conversationsTickets.suggestReply(props.id.toString())
                actions.loadMessages()
            } catch (error: any) {
                // Parse error response for specific error messages
                const errorData = error?.data || {}
                const errorDetail = errorData.detail || 'Failed to generate AI suggestion'
                const errorType = errorData.error_type

                // Show more specific error messages based on error type
                if (errorType === 'timeout') {
                    lemonToast.error('AI service timed out. Please try again.')
                } else if (errorType === 'rate_limit') {
                    lemonToast.error('Too many requests. Please wait a moment and try again.')
                } else if (errorType === 'validation_error') {
                    lemonToast.error('AI returned an invalid response. Please try again.')
                } else {
                    lemonToast.error(errorDetail)
                }
            } finally {
                actions.setSuggesting(false)
            }
        },
        sendMessage: async ({ content, richContent, isPrivate, onSuccess }) => {
            if (props.id === 'new' || !values.ticket?.id) {
                actions.setMessageSending(false)
                return
            }
            try {
                await api.comments.create(
                    {
                        content,
                        rich_content: richContent,
                        scope: 'conversations_ticket',
                        item_id: values.ticket.id,
                        item_context: {
                            author_type: 'support',
                            is_private: isPrivate,
                        },
                    },
                    {}
                )
                lemonToast.success(isPrivate ? 'Private message sent' : 'Message sent')
                actions.setMessageSending(false)
                onSuccess?.()
                if (!isPrivate) {
                    actions.incrementUnreadCustomerCount()
                }
                setTimeout(() => {
                    actions.loadMessages()
                }, 300)
                actions.loadTickets()
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
        cache.disposables.disposeAll()
        impersonationNoticeLogic.findMounted()?.actions.setTicketContext(null)
    }),
    beforeUnload(({ values }) => ({
        enabled: () => values.hasPendingWork,
        message: 'You have unsaved changes. Are you sure you want to leave?',
    })),
])
