import { actions, afterMount, connect, kea, listeners, path, reducers, selectors } from 'kea'
import { loaders } from 'kea-loaders'
import { subscriptions } from 'kea-subscriptions'

import api from 'lib/api'
import { teamLogic } from 'scenes/teamLogic'

import { sidePanelNotificationsLogic } from '~/layout/navigation-3000/sidepanel/panels/activity/sidePanelNotificationsLogic'

import { browserNotificationLogic } from './browserNotificationLogic'
import { supportTicketsSceneLogic } from './scenes/tickets/supportTicketsSceneLogic'
import type { supportTicketCounterLogicType } from './supportTicketCounterLogicType'

const CONVERSATIONS_UNREAD_CHANGED = 'conversations_unread_changed'

export interface UnreadCountResponse {
    count: number
}

export const supportTicketCounterLogic = kea<supportTicketCounterLogicType>([
    path(['products', 'conversations', 'frontend', 'supportTicketCounterLogic']),
    connect(() => ({
        values: [teamLogic, ['currentTeam'], browserNotificationLogic, ['canShowNotifications']],
        actions: [
            browserNotificationLogic,
            ['showNotification'],
            sidePanelNotificationsLogic,
            ['silentPushReceived', 'startSSE'],
        ],
    })),
    actions({
        resetCount: true,
        refreshCount: true,
        loadUnreadCount: true,
        incrementUnreadCount: true,
    }),
    loaders(({ values }) => ({
        unreadCount: [
            0,
            {
                loadUnreadCount: async (_, breakpoint) => {
                    if (!values.isSupportEnabled) {
                        return 0
                    }

                    await breakpoint(1)

                    try {
                        const response = await api.conversationsTickets.unreadCount()
                        return response.count
                    } catch {
                        return values.unreadCount
                    }
                },
                resetCount: () => 0,
            },
        ],
    })),
    reducers({
        unreadCount: {
            incrementUnreadCount: (state: number) => state + 1,
        },
    }),
    selectors({
        isSupportEnabled: [(s) => [s.currentTeam], (currentTeam): boolean => !!currentTeam?.conversations_enabled],
    }),
    listeners(({ actions, values }) => ({
        silentPushReceived: ({ payload }) => {
            if (
                payload.notification_type === CONVERSATIONS_UNREAD_CHANGED &&
                payload.team_id === values.currentTeam?.id
            ) {
                actions.incrementUnreadCount()
            }
        },
        startSSE: () => {
            actions.loadUnreadCount()
        },
        refreshCount: () => {
            actions.loadUnreadCount()
        },
    })),
    subscriptions(({ actions, values }) => ({
        currentTeam: (currentTeam, oldTeam) => {
            if (oldTeam === undefined) {
                return
            }

            actions.resetCount()

            if (currentTeam?.conversations_enabled) {
                actions.loadUnreadCount()
            }
        },
        unreadCount: (unreadCount: number, oldUnreadCount: number | undefined) => {
            if (oldUnreadCount === undefined) {
                return
            }
            if (unreadCount !== oldUnreadCount) {
                supportTicketsSceneLogic.findMounted()?.actions.loadTickets()
            }
            if (unreadCount > oldUnreadCount && values.canShowNotifications) {
                actions.showNotification(unreadCount)
            }
        },
    })),
    afterMount(({ actions, values }) => {
        if (values.isSupportEnabled) {
            actions.loadUnreadCount()
        }
    }),
])
