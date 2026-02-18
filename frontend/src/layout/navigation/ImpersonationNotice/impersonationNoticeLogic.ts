import { actions, afterMount, connect, kea, listeners, path, reducers, selectors } from 'kea'
import { loaders } from 'kea-loaders'

import { userLogic } from 'scenes/userLogic'

import api from '~/lib/api'
import { CommentType, UserType } from '~/types'

import type { impersonationNoticeLogicType } from './impersonationNoticeLogicType'

export interface ImpersonationTicket {
    id: string
    ticket_number: number
    team_id: number
}

export interface TicketMessage {
    id: string
    content: string
    authorType: 'customer' | 'support' | 'human'
    authorName: string
    createdAt: string
    isPrivate: boolean
}

export const impersonationNoticeLogic = kea<impersonationNoticeLogicType>([
    path(['layout', 'navigation', 'ImpersonationNotice', 'impersonationNoticeLogic']),

    connect(() => ({
        values: [userLogic, ['user', 'isImpersonationUpgradeInProgress']],
        actions: [userLogic, ['upgradeImpersonation', 'upgradeImpersonationSuccess']],
    })),

    actions({
        minimize: true,
        maximize: true,
        openUpgradeModal: true,
        closeUpgradeModal: true,
        setPageVisible: (visible: boolean) => ({ visible }),
        clearPageHiddenAt: true,
        toggleTicketExpanded: true,
    }),

    loaders(({ values }) => ({
        impersonationTicket: [
            null as ImpersonationTicket | null,
            {
                loadImpersonationTicket: async () => {
                    if (!values.isImpersonated) {
                        return null
                    }
                    try {
                        return await api.get('admin/impersonation/ticket/')
                    } catch {
                        return null
                    }
                },
            },
        ],
        ticketMessages: [
            [] as TicketMessage[],
            {
                loadTicketMessages: async () => {
                    const ticket = values.impersonationTicket
                    if (!ticket) {
                        return []
                    }
                    try {
                        const response = await api.comments.list({
                            scope: 'conversations_ticket',
                            item_id: ticket.id,
                        })
                        // Transform comments to TicketMessage format and reverse for oldest first
                        return (response.results || []).reverse().map((comment: CommentType) => {
                            const authorType = comment.item_context?.author_type || 'customer'
                            let displayName = 'Customer'
                            if (comment.created_by) {
                                displayName =
                                    [comment.created_by.first_name, comment.created_by.last_name]
                                        .filter(Boolean)
                                        .join(' ') ||
                                    comment.created_by.email ||
                                    'Support'
                            }
                            return {
                                id: comment.id,
                                content: comment.content || '',
                                authorType: authorType === 'support' ? 'human' : authorType,
                                authorName: displayName,
                                createdAt: comment.created_at,
                                isPrivate: comment.item_context?.is_private || false,
                            }
                        })
                    } catch {
                        return []
                    }
                },
            },
        ],
    })),

    reducers({
        isMinimized: [
            false,
            {
                minimize: () => true,
                maximize: () => false,
            },
        ],
        isUpgradeModalOpen: [
            false,
            {
                openUpgradeModal: () => true,
                closeUpgradeModal: () => false,
            },
        ],
        pageHiddenAt: [
            null as number | null,
            {
                // Store timestamp when page becomes hidden - used to work out if we
                // should auto expand when page regains focus
                setPageVisible: (state, { visible }) => (visible ? state : Date.now()),
                clearPageHiddenAt: () => null,
            },
        ],
        isTicketExpanded: [
            false,
            {
                toggleTicketExpanded: (state) => !state,
            },
        ],
    }),

    selectors({
        isReadOnly: [(s) => [s.user], (user: UserType | null): boolean => user?.is_impersonated_read_only ?? true],
        isImpersonated: [(s) => [s.user], (user: UserType | null): boolean => user?.is_impersonated ?? false],
    }),

    listeners(({ actions, values }) => ({
        upgradeImpersonationSuccess: () => {
            if (values.isUpgradeModalOpen && !values.isReadOnly) {
                actions.closeUpgradeModal()
            }
        },
        setPageVisible: ({ visible }) => {
            if (!visible) {
                return
            }
            const { pageHiddenAt } = values
            actions.clearPageHiddenAt()
            // Auto-maximize when window regains focus to ensure staff
            // users are reminded they are impersonating a customer
            // Only trigger if away for more than 30 seconds though to
            // avoid being annoying if quickly switching between windows
            if (values.isMinimized && pageHiddenAt) {
                const secondsAway = (Date.now() - pageHiddenAt) / 1000
                if (secondsAway > 30) {
                    actions.maximize()
                }
            }
        },
        loadImpersonationTicketSuccess: () => {
            // Load messages once we have the ticket
            if (values.impersonationTicket) {
                actions.loadTicketMessages()
            }
        },
        toggleTicketExpanded: () => {
            // Load messages when expanding if we haven't already
            if (values.isTicketExpanded && values.ticketMessages.length === 0 && values.impersonationTicket) {
                actions.loadTicketMessages()
            }
        },
    })),

    afterMount(({ actions, values }) => {
        if (values.isImpersonated) {
            actions.loadImpersonationTicket()
        }
    }),
])
