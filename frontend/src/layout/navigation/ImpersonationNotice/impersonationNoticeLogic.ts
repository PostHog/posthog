import { actions, connect, kea, listeners, path, reducers, selectors } from 'kea'
import { urlToAction } from 'kea-router'

import { lemonToast } from '@posthog/lemon-ui'

import api from 'lib/api'
import { CLOUD_HOSTNAMES } from 'lib/constants'
import { dayjs } from 'lib/dayjs'
import { userLogic } from 'scenes/userLogic'

import { Region, UserType } from '~/types'

import { adminLoginAs } from './adminLoginAs'
import type { impersonationNoticeLogicType } from './impersonationNoticeLogicType'

export interface ExpiredSessionInfo {
    email: string
    userId: number
    // Captured when the countdown fired so we can later confirm a fresh
    // /api/users/@me/ response represents an actual renewal, not the same
    // already-expired session echoing back.
    isImpersonatedUntil: string | null
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
            const { expiredSessionInfo } = values
            if (!expiredSessionInfo) {
                return
            }
            if (!user?.is_impersonated || !user.is_impersonated_until) {
                return
            }
            // Only dismiss if the fresh `is_impersonated_until` is strictly after the
            // one we saw when the countdown fired — otherwise the server is echoing
            // back the same stale session that already expired.
            const newUntil = dayjs(user.is_impersonated_until)
            const renewed = expiredSessionInfo.isImpersonatedUntil
                ? newUntil.isAfter(expiredSessionInfo.isImpersonatedUntil)
                : newUntil.isAfter(dayjs())
            if (renewed) {
                actions.setSessionExpired(null)
                lemonToast.success('Impersonation session renewed')
            }
        },
        setPageVisible: async ({ visible }) => {
            if (!visible) {
                return
            }
            if (values.expiredSessionInfo) {
                // Probe /api/users/@me/ directly rather than dispatching loadUser:
                // loadUser's failure path sets user=null, which would unmount the
                // app and the overlay along with it. On success we hand the fetched
                // user to loadUserSuccess ourselves so userLogic stays in sync.
                try {
                    const freshUser = await api.get<UserType>('api/users/@me/')
                    if (freshUser?.is_impersonated) {
                        actions.loadUserSuccess(freshUser)
                    }
                } catch {
                    // 401 or network error — overlay stays; user will pick an action.
                }
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
