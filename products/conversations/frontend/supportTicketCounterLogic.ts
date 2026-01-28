import { actions, afterMount, beforeUnmount, connect, kea, listeners, path, reducers, selectors } from 'kea'
import { loaders } from 'kea-loaders'
import { subscriptions } from 'kea-subscriptions'

import api from 'lib/api'
import { teamLogic } from 'scenes/teamLogic'

import { supportTicketsSceneLogic } from './scenes/tickets/supportTicketsSceneLogic'
import type { supportTicketCounterLogicType } from './supportTicketCounterLogicType'

const POLL_INTERVAL = 15 * 1000 // 15 seconds - backend is cached so frequent polling is cheap

export interface UnreadCountResponse {
    count: number
}

export const supportTicketCounterLogic = kea<supportTicketCounterLogicType>([
    path(['products', 'conversations', 'frontend', 'supportTicketCounterLogic']),
    connect({
        values: [teamLogic, ['currentTeam']],
    }),
    actions({
        togglePolling: (pageIsVisible: boolean) => ({ pageIsVisible }),
        incrementErrorCount: true,
        clearErrorCount: true,
        resetCount: true, // Reset count when team changes or user logs out
        refreshCount: true, // Public action for other logics to trigger immediate refresh
        loadUnreadCount: true, // Explicit parameterless action (loader will use this)
    }),
    reducers({
        errorCounter: [
            0,
            {
                incrementErrorCount: (state) => (state >= 5 ? 5 : state + 1),
                clearErrorCount: () => 0,
                resetCount: () => 0, // Reset error counter on team change
            },
        ],
    }),
    loaders(({ actions, values, cache }) => ({
        unreadCount: [
            0,
            {
                loadUnreadCount: async (_, breakpoint) => {
                    // Don't poll if support is not enabled
                    if (!values.isSupportEnabled) {
                        return 0
                    }

                    await breakpoint(1)

                    // Track error state locally to avoid race condition with async action dispatch
                    let hadError = false
                    const currentErrorCount = values.errorCounter

                    try {
                        const response = await api.conversationsTickets.unreadCount()
                        actions.clearErrorCount()
                        return response.count
                    } catch {
                        // Swallow errors - increment counter for backoff
                        hadError = true
                        actions.incrementErrorCount()
                        return values.unreadCount // Keep previous value on error
                    } finally {
                        // Schedule next poll
                        if (values.isSupportEnabled) {
                            // Calculate backoff using local state to avoid race condition
                            const effectiveErrorCount = hadError ? Math.min(currentErrorCount + 1, 5) : 0
                            const pollInterval = effectiveErrorCount
                                ? POLL_INTERVAL * (effectiveErrorCount + 1) // Backoff on errors
                                : POLL_INTERVAL

                            cache.disposables.add(() => {
                                const timerId = window.setTimeout(actions.loadUnreadCount, pollInterval)
                                return () => clearTimeout(timerId)
                            }, 'pollTimeout')
                        }
                    }
                },
                resetCount: () => 0, // Immediately set count to 0 on team change/logout
            },
        ],
    })),
    selectors({
        isSupportEnabled: [(s) => [s.currentTeam], (currentTeam): boolean => !!currentTeam?.conversations_enabled],
        hasUnread: [(s) => [s.unreadCount], (unreadCount) => unreadCount > 0],
    }),
    listeners(({ actions, values, cache }) => ({
        togglePolling: ({ pageIsVisible }) => {
            if (pageIsVisible && values.isSupportEnabled) {
                actions.loadUnreadCount()
            } else {
                cache.disposables.dispose('pollTimeout')
            }
        },
        refreshCount: () => {
            // Public action for other logics to trigger immediate refresh (e.g., after viewing a ticket)
            cache.disposables.dispose('pollTimeout')
            actions.loadUnreadCount()
        },
        resetCount: () => {
            // Stop polling when count is reset (team change/logout)
            // Note: pollTimeout is already disposed in subscriptions
        },
    })),
    subscriptions(({ actions, cache }) => ({
        // React to team changes - reset and re-fetch for new team
        currentTeam: (currentTeam, oldTeam) => {
            // Skip initial mount (oldTeam is undefined)
            if (oldTeam === undefined) {
                return
            }

            // Team changed or user logged out
            cache.disposables.dispose('pollTimeout')
            actions.resetCount()

            // If new team has support enabled, start polling
            if (currentTeam?.conversations_enabled) {
                actions.loadUnreadCount()
            }
        },
        // Notify tickets scene when unread count changes
        unreadCount: (unreadCount, oldUnreadCount) => {
            // Skip initial subscription
            if (oldUnreadCount === undefined) {
                return
            }
            // Refresh tickets list if scene is mounted
            if (unreadCount !== oldUnreadCount) {
                supportTicketsSceneLogic.findMounted()?.actions.loadTickets()
            }
        },
    })),
    afterMount(({ actions, values, cache }) => {
        // Set up visibility change listener
        cache.disposables.add(() => {
            const onVisibilityChange = (): void => {
                actions.togglePolling(document.visibilityState === 'visible')
            }
            document.addEventListener('visibilitychange', onVisibilityChange)
            return () => document.removeEventListener('visibilitychange', onVisibilityChange)
        }, 'visibilityListener')

        // Start polling if support is enabled
        if (values.isSupportEnabled) {
            actions.loadUnreadCount()
        }
    }),
    beforeUnmount(({ cache }) => {
        // Clean up all disposables (timers, event listeners)
        cache.disposables.disposeAll()
    }),
])
