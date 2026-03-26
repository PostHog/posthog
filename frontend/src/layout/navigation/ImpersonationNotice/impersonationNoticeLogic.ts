import { actions, afterMount, connect, kea, listeners, path, reducers, selectors } from 'kea'
import { loaders } from 'kea-loaders'

import { lemonToast } from '@posthog/lemon-ui'

import { CLOUD_HOSTNAMES } from 'lib/constants'
import { userLogic } from 'scenes/userLogic'

import api from '~/lib/api'
import { CommentType, Region, UserType } from '~/types'

import type { impersonationNoticeLogicType } from './impersonationNoticeLogicType'

export interface ImpersonationTicketContext {
    ticketId: string
    email: string
    region?: Region
}

function adminLoginUrlForTicket(context: ImpersonationTicketContext): string | null {
    if (!context.region) {
        return null
    }
    const domain = CLOUD_HOSTNAMES[context.region]
    return `https://${domain}/admin/posthog/user/?q=${encodeURIComponent(context.email)}`
}

export interface ImpersonationTicket {
    id: string
    ticket_number: number
    team_id: number
    messages: CommentType[]
}

export interface TicketMessage {
    id: string
    content: string
    authorType: 'customer' | 'support' | 'human'
    authorName: string
    createdAt: string
    isPrivate: boolean
}

function commentToTicketMessage(comment: CommentType): TicketMessage {
    const authorType = comment.item_context?.author_type || 'customer'
    let displayName = 'Customer'
    if (comment.created_by) {
        displayName =
            [comment.created_by.first_name, comment.created_by.last_name].filter(Boolean).join(' ') ||
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
        setTicketContext: (context: ImpersonationTicketContext | null) => ({ context }),
        initiateImpersonation: true,
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
        ticketContext: [
            null as ImpersonationTicketContext | null,
            {
                setTicketContext: (_, { context }) => context,
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
        adminLoginUrl: [
            (s) => [s.ticketContext],
            (ticketContext: ImpersonationTicketContext | null): string | null => {
                if (!ticketContext?.email) {
                    return null
                }
                return adminLoginUrlForTicket(ticketContext)
            },
        ],
        ticketMessages: [
            (s) => [s.impersonationTicket],
            (ticket: ImpersonationTicket | null): TicketMessage[] =>
                (ticket?.messages || []).map(commentToTicketMessage),
        ],
        ticketMessagesLoading: [(s) => [s.impersonationTicketLoading], (loading: boolean): boolean => loading],
    }),

    listeners(({ actions, values }) => ({
        initiateImpersonation: async () => {
            const context = values.ticketContext
            if (!context) {
                return
            }

            try {
                const response = await api.create('admin/impersonation/from-ticket/', {
                    ticket_id: context.ticketId,
                })
                if (response.redirect_url) {
                    lemonToast.info(`This ticket is from ${response.redirect_region}. Opening in a new tab...`)
                    window.open(response.redirect_url, '_blank')
                    return
                }
                window.location.replace('/')
            } catch (error: any) {
                const detail = error?.data?.error || 'Failed to impersonate user'
                lemonToast.error(detail)
            }
        },
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
    })),

    afterMount(({ actions, values }) => {
        if (values.isImpersonated) {
            actions.loadImpersonationTicket()
        }
    }),
])
