import { actions, afterMount, connect, kea, listeners, path, reducers, selectors } from 'kea'
import { router } from 'kea-router'
import { subscriptions } from 'kea-subscriptions'

import { getCurrentTeamIdOrNone } from 'lib/utils/getAppContext'
import { teamLogic } from 'scenes/teamLogic'
import { urls } from 'scenes/urls'

import type { browserNotificationLogicType } from './browserNotificationLogicType'
import type { NotificationPermission } from './types'

const STORAGE_KEY_PREFIX = 'posthog-support-notifications'
const NOTIFICATION_TAG = 'posthog-support-ticket'
const NOTIFICATION_ICON = '/static/posthog-icon.svg'
const NOTIFICATION_AUTO_CLOSE_MS = 5000

const getStorageKey = (): string => {
    const teamId = getCurrentTeamIdOrNone() ?? teamLogic.findMounted()?.values.currentTeamId ?? 'null'
    return `${STORAGE_KEY_PREFIX}-${teamId}`
}

const isNotificationSupported = (): boolean => {
    return typeof window !== 'undefined' && 'Notification' in window
}

const getStoredPreference = (): boolean => {
    if (typeof localStorage === 'undefined') {
        return false
    }
    const stored = localStorage.getItem(getStorageKey())
    return stored === 'true'
}

const setStoredPreference = (enabled: boolean): void => {
    if (typeof localStorage === 'undefined') {
        return
    }
    if (enabled) {
        localStorage.setItem(getStorageKey(), 'true')
    } else {
        localStorage.removeItem(getStorageKey())
    }
}

export const browserNotificationLogic = kea<browserNotificationLogicType>([
    path(['products', 'conversations', 'frontend', 'browserNotificationLogic']),
    connect(() => ({
        values: [teamLogic, ['currentTeam']],
    })),
    actions({
        requestPermission: true,
        setPermission: (permission: NotificationPermission) => ({ permission }),
        setEnabled: (enabled: boolean) => ({ enabled }),
        showNotification: (count: number) => ({ count }),
    }),
    reducers({
        permission: [
            (isNotificationSupported() ? Notification.permission : 'denied') as NotificationPermission,
            {
                setPermission: (_, { permission }) => permission,
            },
        ],
        enabled: [
            false,
            {
                setEnabled: (_, { enabled }) => enabled,
            },
        ],
    }),
    listeners(({ actions }) => ({
        requestPermission: async () => {
            if (!isNotificationSupported()) {
                return
            }

            try {
                const result = await Notification.requestPermission()
                actions.setPermission(result as NotificationPermission)

                // Auto-enable if permission granted
                if (result === 'granted') {
                    actions.setEnabled(true)
                }
            } catch {
                // Permission request failed - likely user dismissed
                actions.setPermission(Notification.permission as NotificationPermission)
            }
        },
        setEnabled: ({ enabled }) => {
            setStoredPreference(enabled)
        },
        showNotification: ({ count }) => {
            // Defense in depth - caller should check canShowNotifications but verify here too
            if (!isNotificationSupported() || Notification.permission !== 'granted') {
                return
            }

            const title = count === 1 ? 'New support message' : `${count} unread support messages`
            const body = 'Click to view your support tickets'

            const notification = new Notification(title, {
                body,
                icon: NOTIFICATION_ICON,
                tag: NOTIFICATION_TAG, // Replaces previous notification with same tag
                requireInteraction: false,
            })

            notification.onclick = () => {
                // Focus the window/tab
                window.focus()
                // Navigate to tickets
                router.actions.push(urls.supportTickets())
                // Close the notification
                notification.close()
            }

            // Auto-close after timeout
            setTimeout(() => {
                notification.close()
            }, NOTIFICATION_AUTO_CLOSE_MS)
        },
    })),
    selectors({
        isSupported: [() => [], () => isNotificationSupported()],
        canShowNotifications: [
            (s) => [s.isSupported, s.permission, s.enabled, s.currentTeam],
            (isSupported, permission, enabled, currentTeam): boolean =>
                isSupported && permission === 'granted' && enabled && !!currentTeam?.conversations_enabled,
        ],
        isPermissionDenied: [
            (s) => [s.isSupported, s.permission],
            (isSupported, permission): boolean => isSupported && permission === 'denied',
        ],
    }),
    subscriptions(({ actions }) => ({
        // Reset enabled preference when team changes (keep in sync with new team's localStorage)
        currentTeam: (currentTeam, oldTeam) => {
            // Skip initial mount
            if (oldTeam === undefined) {
                return
            }
            // Team changed - load preference for new team
            if (currentTeam?.id !== oldTeam?.id) {
                actions.setEnabled(getStoredPreference())
            }
        },
    })),
    afterMount(({ actions }) => {
        // Load initial permission state
        if (isNotificationSupported()) {
            actions.setPermission(Notification.permission as NotificationPermission)
        }
        // Load stored preference
        actions.setEnabled(getStoredPreference())
    }),
])
