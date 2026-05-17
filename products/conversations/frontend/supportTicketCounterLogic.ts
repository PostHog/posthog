import { actions, afterMount, connect, kea, listeners, path, reducers, selectors } from 'kea'
import { loaders } from 'kea-loaders'
import { subscriptions } from 'kea-subscriptions'

import api from 'lib/api'
import { teamLogic } from 'scenes/teamLogic'

import { browserNotificationLogic } from './browserNotificationLogic'
import { supportTicketsSceneLogic } from './scenes/tickets/supportTicketsSceneLogic'
import type { supportTicketCounterLogicType } from './supportTicketCounterLogicType'

const POLL_INTERVAL = 5 * 1000 // 5 seconds - backend is cached so frequent polling is cheap

export interface UnreadCountResponse {
    count: number
}

export const supportTicketCounterLogic = kea<supportTicketCounterLogicType>([
    path(['products', 'conversations', 'frontend', 'supportTicketCounterLogic']),
    connect(() => ({
        values: [teamLogic, ['currentTeam'], browserNotificationLogic, ['canShowNotifications']],
        actions: [browserNotificationLogic, ['showNotification']],
    })),
    actions({
        incrementErrorCount: true,
        clearErrorCount: true,
        resetCount: true, // Reset count when team changes or user logs out
        refreshCount: true, // Public action for other logics to trigger immediate refresh
        loadUnreadCount: true, // Explicit parameterless action (loader will use this)
        schedulePoll: true, // Re-schedule the next poll via disposables
    }),
    reducers({
        errorCounter: [
            0,
            {
                incrementErrorCount: (state) => (state >= 5 ? 5 : state + 1),
                clearErrorCount: () => 0,
                resetCount: () => 0,
            },
        ],
    }),
    loaders(({ actions, values }) => ({
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
                        actions.clearErrorCount()
                        return response.count
                    } catch {
                        // Swallow errors - increment counter for backoff
                        actions.incrementErrorCount()
                        return values.unreadCount // Keep previous value on error
                    }
                },
                resetCount: () => 0, // Immediately set count to 0 on team change/logout
            },
        ],
    })),
    selectors({
        isSupportEnabled: [(s) => [s.currentTeam], (currentTeam): boolean => !!currentTeam?.conversations_enabled],
    }),
    listeners(({ actions, values, cache }) => ({
        // Re-schedule after each load completes (success or failure). The
        // disposables plugin will auto-pause this disposable when the tab is
        // hidden and resume it when visible — no explicit visibilitychange
        // listener needed.
        loadUnreadCountSuccess: () => actions.schedulePoll(),
        loadUnreadCountFailure: () => actions.schedulePoll(),
        schedulePoll: () => {
            if (!values.isSupportEnabled) {
                return
            }
            const interval = values.errorCounter
                ? POLL_INTERVAL * (values.errorCounter + 1) // Backoff on errors
                : POLL_INTERVAL
            cache.disposables.add(() => {
                const id = window.setTimeout(actions.loadUnreadCount, interval)
                return () => clearTimeout(id)
            }, 'pollTimeout')
        },
        refreshCount: () => {
            // Public action for other logics to trigger immediate refresh
            cache.disposables.dispose('pollTimeout')
            actions.loadUnreadCount()
        },
    })),
    subscriptions(({ actions, values, cache }) => ({
        // React to team changes - reset and re-fetch for new team
        currentTeam: (currentTeam, oldTeam) => {
            // Skip initial mount (oldTeam is undefined)
            if (oldTeam === undefined) {
                return
            }

            cache.disposables.dispose('pollTimeout')
            actions.resetCount()

            if (currentTeam?.conversations_enabled) {
                actions.loadUnreadCount()
            }
        },
        // Notify tickets scene when unread count changes
        unreadCount: (unreadCount, oldUnreadCount) => {
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
