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

const SHOW_UNREAD_ONLY_KEY = 'notifications_show_unread_only'

export const notificationsLogic = kea<notificationsLogicType>([
    path(['lib', 'logic', 'notificationsLogic']),
    actions({
        loadNotifications: (resetPagination = false) => ({ resetPagination }),
        loadMoreNotifications: true,
        loadPreferences: true,
        markAsRead: (notificationId: string) => ({ notificationId }),
        toggleReadStatus: (notificationId: string) => ({ notificationId }),
        markAllAsRead: true,
        updatePreference: (resourceType: string, enabled: boolean) => ({ resourceType, enabled }),
        addNotification: (notification: Notification) => ({ notification }),
        setWebSocketConnected: (connected: boolean) => ({ connected }),
        setShowUnreadOnly: (showUnreadOnly: boolean) => ({ showUnreadOnly }),
        setHasMore: (hasMore: boolean) => ({ hasMore }),
    }),

    loaders(({ values, actions }) => ({
        notifications: {
            __default: [] as Notification[],
            loadNotifications: async ({ resetPagination }) => {
                const offset = resetPagination ? 0 : values.notifications.length
                const params: Record<string, any> = { limit: 20, offset }

                if (values.showUnreadOnly) {
                    params.unread = 'true'
                }

                const response = await api.notifications.list(params)
                const results = response.results || []

                // Check if there are more notifications
                actions.setHasMore(response.next !== null)

                if (resetPagination) {
                    return results
                }

                return [...values.notifications, ...results]
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
            toggleReadStatus: (state, { notificationId }) => {
                const notification = state.find((n) => n.id === notificationId)
                if (!notification) {
                    return state
                }

                return state.map((n) =>
                    n.id === notificationId ? { ...n, read_at: n.read_at ? null : new Date().toISOString() } : n
                )
            },
            markAllAsRead: (state) => state.map((n) => ({ ...n, read_at: new Date().toISOString() })),
        },
        webSocketConnected: [
            false,
            {
                setWebSocketConnected: (_, { connected }) => connected,
            },
        ],
        showUnreadOnly: [
            (() => {
                const stored = localStorage.getItem(SHOW_UNREAD_ONLY_KEY)
                return stored !== null ? stored === 'true' : true // Default to true
            })(),
            {
                setShowUnreadOnly: (_, { showUnreadOnly }) => {
                    localStorage.setItem(SHOW_UNREAD_ONLY_KEY, String(showUnreadOnly))
                    return showUnreadOnly
                },
            },
        ],
        hasMore: [
            false,
            {
                setHasMore: (_, { hasMore }) => hasMore,
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
        displayedNotifications: [
            (s) => [s.notifications],
            (notifications): Notification[] => {
                return notifications
            },
        ],
    }),

    listeners(({ actions, values }) => ({
        markAsRead: async ({ notificationId }) => {
            try {
                await api.notifications.update(notificationId, { is_read: true })
            } catch (error) {
                lemonToast.error('Failed to mark notification as read')
                console.error('Error marking notification as read:', error)
            }
        },
        toggleReadStatus: async ({ notificationId }) => {
            try {
                const notification = values.notifications.find((n) => n.id === notificationId)
                if (!notification) {
                    return
                }

                // The reducer already optimistically toggled the value, so we need to send the NEW value
                const newReadStatus = !!notification.read_at
                await api.notifications.update(notificationId, { is_read: newReadStatus })
            } catch (error) {
                lemonToast.error('Failed to toggle notification status')
                console.error('Error toggling notification status:', error)
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
        setShowUnreadOnly: () => {
            // Reload notifications with new filter
            actions.loadNotifications(true)
        },
        loadMoreNotifications: () => {
            actions.loadNotifications(false)
        },
    })),

    afterMount(({ actions }) => {
        actions.loadNotifications(true)
        actions.loadPreferences()
    }),
])
