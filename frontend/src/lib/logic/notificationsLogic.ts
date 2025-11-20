import { actions, afterMount, kea, listeners, path, reducers, selectors } from 'kea'
import { loaders } from 'kea-loaders'

import { lemonToast } from '@posthog/lemon-ui'

import api from 'lib/api'

import type { notificationsLogicType } from './notificationsLogicType'

export interface Notification {
    id: string
    resource_type: string
    resource_id: string | null
    title: string
    message: string
    context: Record<string, any>
    priority: 'low' | 'normal' | 'high' | 'urgent'
    read_at: string | null
    created_at: string
}

export interface NotificationPreference {
    id: string
    resource_type: string
    enabled: boolean
    created_at: string
    updated_at: string
}

export const notificationsLogic = kea<notificationsLogicType>([
    path(['lib', 'logic', 'notificationsLogic']),
    actions({
        loadNotifications: true,
        loadPreferences: true,
        markAsRead: (notificationId: string) => ({ notificationId }),
        markAllAsRead: true,
        updatePreference: (resourceType: string, enabled: boolean) => ({ resourceType, enabled }),
        addNotification: (notification: Notification) => ({ notification }),
        setWebSocketConnected: (connected: boolean) => ({ connected }),
    }),

    loaders(() => ({
        notifications: {
            __default: [] as Notification[],
            loadNotifications: async () => {
                const response = await api.notifications.list()
                return response.results || []
            },
        },
        preferences: {
            __default: [] as NotificationPreference[],
            loadPreferences: async () => {
                const response = await api.notificationPreferences.list()
                return response.results || []
            },
        },
    })),

    reducers({
        notifications: {
            addNotification: (state, { notification }) => [notification, ...state],
            markAsRead: (state, { notificationId }) =>
                state.map((n) => (n.id === notificationId ? { ...n, read_at: new Date().toISOString() } : n)),
            markAllAsRead: (state) => state.map((n) => ({ ...n, read_at: new Date().toISOString() })),
        },
        webSocketConnected: [
            false,
            {
                setWebSocketConnected: (_, { connected }) => connected,
            },
        ],
    }),

    selectors({
        unreadNotifications: [
            (s) => [s.notifications],
            (notifications): Notification[] => notifications.filter((n) => !n.read_at),
        ],
        unreadCount: [(s) => [s.unreadNotifications], (unreadNotifications): number => unreadNotifications.length],
        preferencesByResourceType: [
            (s) => [s.preferences],
            (preferences): Record<string, boolean> => {
                return preferences.reduce(
                    (acc, pref) => {
                        acc[pref.resource_type] = pref.enabled
                        return acc
                    },
                    {} as Record<string, boolean>
                )
            },
        ],
    }),

    listeners(({ actions }) => ({
        markAsRead: async ({ notificationId }) => {
            try {
                await api.notifications.markRead(notificationId)
            } catch (error) {
                lemonToast.error('Failed to mark notification as read')
                console.error('Error marking notification as read:', error)
            }
        },
        markAllAsRead: async () => {
            try {
                await api.notifications.markAllRead()
            } catch (error) {
                lemonToast.error('Failed to mark all notifications as read')
                console.error('Error marking all notifications as read:', error)
            }
        },
        updatePreference: async ({ resourceType, enabled }) => {
            try {
                await api.notificationPreferences.update({ resource_type: resourceType, enabled })
                actions.loadPreferences()
                lemonToast.success(`${enabled ? 'Enabled' : 'Disabled'} ${resourceType} notifications`)
            } catch (error) {
                lemonToast.error('Failed to update notification preference')
                console.error('Error updating preference:', error)
            }
        },
    })),

    afterMount(({ actions }) => {
        actions.loadNotifications()
        actions.loadPreferences()
    }),
])
