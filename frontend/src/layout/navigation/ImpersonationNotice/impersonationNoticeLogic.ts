import { actions, connect, kea, listeners, path, reducers, selectors } from 'kea'
import { urlToAction } from 'kea-router'

import { lemonToast } from '@posthog/lemon-ui'

import { CLOUD_HOSTNAMES } from 'lib/constants'
import { userLogic } from 'scenes/userLogic'

import { Region, UserType } from '~/types'

import { adminLoginAs } from './adminLoginAs'
import type { impersonationNoticeLogicType } from './impersonationNoticeLogicType'

export interface ExpiredSessionInfo {
    email: string
    userId: number
}

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

export const impersonationNoticeLogic = kea<impersonationNoticeLogicType>([
    path(['layout', 'navigation', 'ImpersonationNotice', 'impersonationNoticeLogic']),

    connect(() => ({
        values: [userLogic, ['user', 'isImpersonationUpgradeInProgress']],
        actions: [userLogic, ['upgradeImpersonation', 'upgradeImpersonationSuccess', 'loadUser', 'loadUserSuccess']],
    })),

    actions({
        minimize: true,
        maximize: true,
        openUpgradeModal: true,
        closeUpgradeModal: true,
        setPageVisible: (visible: boolean) => ({ visible }),
        clearPageHiddenAt: true,
        setTicketContext: (context: ImpersonationTicketContext | null) => ({ context }),
        setSessionExpired: (info: ExpiredSessionInfo | null) => ({ info }),
        reImpersonate: (reason: string, readOnly: boolean) => ({ reason, readOnly }),
        reImpersonateFailure: (error: string) => ({ error }),
    }),

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
        expiredSessionInfo: [
            null as ExpiredSessionInfo | null,
            {
                setSessionExpired: (_, { info }) => info,
            },
        ],
        isReImpersonating: [
            false,
            {
                reImpersonate: () => true,
                reImpersonateFailure: () => false,
                setSessionExpired: () => false,
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
        isSessionExpired: [(s) => [s.expiredSessionInfo], (info: ExpiredSessionInfo | null): boolean => info !== null],
    }),

    listeners(({ actions, values }) => ({
        upgradeImpersonationSuccess: () => {
            if (values.isUpgradeModalOpen && !values.isReadOnly) {
                actions.closeUpgradeModal()
            }
        },
        reImpersonate: async ({ reason, readOnly }) => {
            const { expiredSessionInfo } = values
            if (!expiredSessionInfo) {
                return
            }

            try {
                await adminLoginAs({ userId: expiredSessionInfo.userId, reason, readOnly })
                actions.loadUser()
            } catch (e) {
                const errorMessage = e instanceof Error ? e.message : 'Failed to re-impersonate'
                lemonToast.error(errorMessage)
                actions.reImpersonateFailure(errorMessage)
            }
        },
        loadUserSuccess: ({ user }) => {
            if (!values.expiredSessionInfo) {
                return
            }
            if (user?.is_impersonated) {
                actions.setSessionExpired(null)
                lemonToast.success('Impersonation session renewed')
            }
        },
        setPageVisible: ({ visible }) => {
            if (!visible) {
                return
            }
            if (values.expiredSessionInfo) {
                actions.loadUser()
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

    urlToAction(({ actions, values }) => ({
        '*': (_params, _searchParams, _hashParams, { pathname }) => {
            if (values.ticketContext && !pathname.startsWith('/support/tickets/')) {
                actions.setTicketContext(null)
            }
        },
    })),
])
