import { actions, connect, kea, listeners, path, reducers, selectors } from 'kea'

import { CLOUD_HOSTNAMES } from 'lib/constants'
import { userLogic } from 'scenes/userLogic'

import { Region, UserType } from '~/types'

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
    })),
])
