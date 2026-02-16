import { actions, afterMount, beforeUnmount, connect, kea, listeners, path, reducers, selectors } from 'kea'
import { subscriptions } from 'kea-subscriptions'
import posthog from 'posthog-js'

import { FEATURE_FLAGS } from 'lib/constants'
import { lemonToast } from 'lib/lemon-ui/LemonToast/LemonToast'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'

import { sidePanelStateLogic } from '~/layout/navigation-3000/sidepanel/sidePanelStateLogic'

import type { ChatMessage, ConversationMessage, ConversationTicket, SidePanelViewState } from '../../types'
import type { sidepanelTicketsLogicType } from './sidepanelTicketsLogicType'

const POLL_INTERVAL = 60 * 1000 // 60 seconds

export const sidepanelTicketsLogic = kea<sidepanelTicketsLogicType>([
    path(['products', 'conversations', 'frontend', 'components', 'SidePanel', 'sidepanelTicketsLogic']),
    connect(() => ({
        values: [sidePanelStateLogic, ['sidePanelOpen'], featureFlagLogic, ['featureFlags']],
    })),
    actions({
        loadTickets: true,
        startPolling: true,
        stopPolling: true,
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
    selectors({
        isEnabled: [
            (s) => [s.featureFlags],
            (featureFlags): boolean => !!featureFlags[FEATURE_FLAGS.PRODUCT_SUPPORT_SIDE_PANEL],
        ],
        totalUnreadCount: [(s) => [s.tickets], (tickets) => tickets.reduce((sum, t) => sum + (t.unread_count ?? 0), 0)],
    }),
    listeners(({ actions, values, cache }) => ({
        loadTickets: async () => {
            if (!values.isEnabled || !posthog.conversations) {
                return
            }
            actions.setTicketsLoading(true)
            try {
                const response = await posthog.conversations.getTickets({ limit: 50 })
                if (response) {
                    actions.setTickets(response.results as ConversationTicket[])
                    // Start polling only if user has tickets
                    if (response.results.length > 0) {
                        actions.startPolling()
                    }
                }
            } catch (e) {
                console.error('Failed to load tickets:', e)
                lemonToast.error('Failed to load tickets. Please try again.')
            } finally {
                actions.setTicketsLoading(false)
            }
        },
        startPolling: () => {
            // Only poll if feature is enabled and page is visible
            if (!values.isEnabled || document.visibilityState !== 'visible') {
                return
            }
            // Clear any existing poll timer
            if (cache.pollTimer) {
                clearTimeout(cache.pollTimer)
            }
            cache.pollTimer = window.setTimeout(() => {
                actions.loadTickets()
            }, POLL_INTERVAL)
        },
        stopPolling: () => {
            if (cache.pollTimer) {
                clearTimeout(cache.pollTimer)
                cache.pollTimer = null
            }
        },
        loadMessages: async ({ ticketId }) => {
            if (!values.isEnabled || !ticketId || !posthog.conversations) {
                return
            }
            actions.setMessagesLoading(true)
            try {
                const allMessages: ConversationMessage[] = []
                let after: string | undefined
                let hasMore = true

                // Fetch all pages of messages using `after` timestamp pagination
                while (hasMore) {
                    const response = await (posthog.conversations.getMessages as any)(ticketId, after)
                    // Check if we're still viewing the same ticket (avoid race condition when switching quickly)
                    if (!response || values.currentTicket?.id !== ticketId) {
                        return
                    }
                    const messages = response.messages as ConversationMessage[]
                    allMessages.push(...messages)
                    hasMore = response.has_more && messages.length > 0
                    // Use the last message's created_at as the `after` cursor for next page
                    if (hasMore && messages.length > 0) {
                        after = messages[messages.length - 1].created_at
                    }
                }

                // Transform and set all messages
                const transformedMessages: ChatMessage[] = allMessages.map((msg) => ({
                    id: msg.id,
                    content: msg.content,
                    authorType: msg.author_type,
                    authorName: msg.author_name || '',
                    createdAt: msg.created_at,
                }))
                actions.setMessages(transformedMessages)
                actions.setHasMoreMessages(false)
            } catch (e) {
                console.error('Failed to load messages:', e)
                lemonToast.error('Failed to load messages. Please try again.')
            } finally {
                actions.setMessagesLoading(false)
            }
        },
        sendMessage: async ({ content, onSuccess }) => {
            if (!values.isEnabled || !content.trim() || values.messageSending || !posthog.conversations) {
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
            if (!values.isEnabled || !ticketId || !posthog.conversations) {
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
            actions.setMessages([]) // Clear messages immediately to avoid showing stale data
            actions.loadMessages(ticket.id)
            actions.markAsRead(ticket.id)
        },
    })),
    subscriptions(({ actions, values }) => ({
        sidePanelOpen: (open: boolean) => {
            if (values.isEnabled && open) {
                actions.loadTickets()
            }
        },
    })),
    afterMount(({ actions, values, cache }) => {
        // Only load if feature is enabled
        if (values.isEnabled) {
            actions.loadTickets()
        }

        // Set up visibility change listener (only if feature is enabled)
        if (values.isEnabled) {
            cache.onVisibilityChange = (): void => {
                if (document.visibilityState === 'visible') {
                    actions.loadTickets()
                } else {
                    actions.stopPolling()
                }
            }
            document.addEventListener('visibilitychange', cache.onVisibilityChange)
        }
    }),
    beforeUnmount(({ actions, cache }) => {
        actions.stopPolling()
        if (cache.onVisibilityChange) {
            document.removeEventListener('visibilitychange', cache.onVisibilityChange)
        }
    }),
])
