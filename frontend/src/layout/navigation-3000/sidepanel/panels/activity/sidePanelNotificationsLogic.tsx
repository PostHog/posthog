import { actions, afterMount, beforeUnmount, connect, kea, listeners, path, reducers, selectors } from 'kea'
import { lazyLoaders } from 'kea-loaders'
import posthog, { JsonRecord } from 'posthog-js'

import { IconBug, IconCheckCircle, IconComment, IconNotification, IconPlug, IconWarning } from '@posthog/icons'
import { lemonToast } from '@posthog/lemon-ui'

import api from 'lib/api'
import { describerFor } from 'lib/components/ActivityLog/activityLogLogic'
import { HumanizedActivityLogItem, humanize } from 'lib/components/ActivityLog/humanizeActivity'
import { notificationsMenuLogic } from 'lib/components/NotificationsMenu/notificationsMenuLogic'
import { FEATURE_FLAGS } from 'lib/constants'
import { dayjs } from 'lib/dayjs'
import { LemonMarkdown } from 'lib/lemon-ui/LemonMarkdown'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { toParams } from 'lib/utils'
import { liveEventsHostOrigin } from 'lib/utils/apiHost'
import { projectLogic } from 'scenes/projectLogic'
import { teamLogic } from 'scenes/teamLogic'

import { ChangesResponse } from '~/layout/navigation-3000/sidepanel/panels/activity/sidePanelActivityLogic'
import { InAppNotification } from '~/types'

import { sidePanelStateLogic } from '../../sidePanelStateLogic'
import { sidePanelContextLogic } from '../sidePanelContextLogic'
import type { sidePanelNotificationsLogicType } from './sidePanelNotificationsLogicType'

const POLL_TIMEOUT = 5 * 60 * 1000
const UNREAD_POLL_TIMEOUT = 30 * 1000

export interface ChangelogFlagPayload {
    notificationDate: dayjs.Dayjs
    markdown: string
    name?: string
    email?: string
}

export const sidePanelNotificationsLogic = kea<sidePanelNotificationsLogicType>([
    path(['layout', 'navigation-3000', 'sidepanel', 'panels', 'activity', 'sidePanelNotificationsLogic']),
    connect(() => ({
        values: [
            sidePanelContextLogic,
            ['sceneSidePanelContext'],
            projectLogic,
            ['currentProjectId'],
            featureFlagLogic,
            ['featureFlags'],
            teamLogic,
            ['currentTeam'],
        ],
        actions: [sidePanelStateLogic, ['openSidePanel']],
    })),
    actions({
        togglePolling: (pageIsVisible: boolean) => ({ pageIsVisible }),
        incrementErrorCount: true,
        clearErrorCount: true,
        markAllAsRead: true,
        loadImportantChanges: (onlyUnread = true) => ({ onlyUnread }),
        // Real-time notification actions
        setInAppNotifications: (notifications: InAppNotification[], hasMore: boolean) => ({
            notifications,
            hasMore,
        }),
        appendInAppNotifications: (notifications: InAppNotification[], hasMore: boolean) => ({
            notifications,
            hasMore,
        }),
        setInAppUnreadCount: (count: number) => ({ count }),
        notificationReceived: (notification: InAppNotification) => ({ notification }),
        markAsRead: (id: string) => ({ id }),
        toggleRead: (id: string) => ({ id }),
        loadMoreNotifications: true,
        initialLoadDone: true,
        startSSE: true,
        stopSSE: true,
        fallbackToPoll: true,
    }),
    reducers({
        isInitialLoadComplete: [
            false,
            {
                initialLoadDone: () => true,
            },
        ],
        errorCounter: [
            0,
            {
                incrementErrorCount: (state) => (state >= 5 ? 5 : state + 1),
                clearErrorCount: () => 0,
            },
        ],
        inAppNotifications: [
            [] as InAppNotification[],
            {
                setInAppNotifications: (_, { notifications }) => notifications,
                appendInAppNotifications: (state, { notifications }) => {
                    const existingIds = new Set(state.map((n) => n.id))
                    const newItems = notifications.filter((n) => !existingIds.has(n.id))
                    return [...state, ...newItems]
                },
                notificationReceived: (state, { notification }) => [notification, ...state],
                markAsRead: (state, { id }) =>
                    state.map((n) => (n.id === id ? { ...n, read: true, read_at: new Date().toISOString() } : n)),
                toggleRead: (state, { id }) =>
                    state.map((n) =>
                        n.id === id ? { ...n, read: !n.read, read_at: n.read ? null : new Date().toISOString() } : n
                    ),
                markAllAsRead: (state) =>
                    state.map((n) => (n.read ? n : { ...n, read: true, read_at: new Date().toISOString() })),
            },
        ],
        loadedFromApiCount: [
            0,
            {
                setInAppNotifications: (_, { notifications }) => notifications.length,
                appendInAppNotifications: (state, { notifications }) => state + notifications.length,
            },
        ],
        hasMoreNotifications: [
            false,
            {
                setInAppNotifications: (_, { hasMore }) => hasMore,
                appendInAppNotifications: (_, { hasMore }) => hasMore,
            },
        ],
        isLoadingMore: [
            false,
            {
                loadMoreNotifications: () => true,
                appendInAppNotifications: () => false,
            },
        ],
        inAppUnreadCount: [
            0,
            {
                setInAppUnreadCount: (_, { count }) => count,
                notificationReceived: (state, { notification }) => (notification.read ? state : state + 1),
                markAsRead: (state) => Math.max(0, state - 1),
                toggleRead: (state) => state,
                markAllAsRead: () => 0,
            },
        ],
    }),
    lazyLoaders(({ actions, values, cache }) => ({
        importantChanges: [
            null as ChangesResponse | null,
            {
                loadImportantChanges: async ({ onlyUnread }, breakpoint) => {
                    await breakpoint(1)

                    try {
                        const response = await api.get<ChangesResponse>(
                            `api/projects/${values.currentProjectId}/my_notifications?` +
                                toParams({ unread: onlyUnread })
                        )

                        actions.clearErrorCount()
                        return response
                    } catch {
                        actions.incrementErrorCount()
                        return null
                    } finally {
                        const pollTimeoutMilliseconds = values.errorCounter
                            ? POLL_TIMEOUT * values.errorCounter
                            : POLL_TIMEOUT

                        cache.disposables.add(() => {
                            const timerId = window.setTimeout(actions.loadImportantChanges, pollTimeoutMilliseconds)
                            return () => clearTimeout(timerId)
                        }, 'pollTimeout')
                    }
                },
                markAllAsRead: async () => {
                    if (values.realTimeNotificationsEnabled) {
                        await api.create(`api/environments/${values.currentProjectId}/notifications/mark_all_read/`, {})
                        return values.importantChanges
                    }

                    const current = values.importantChanges
                    if (!current) {
                        return null
                    }

                    const legacyNotifications = values.legacyNotifications
                    const hasUnread = legacyNotifications.some((ic) => ic.unread)

                    if (!hasUnread || legacyNotifications.length === 0) {
                        return current
                    }

                    const latestNotification = legacyNotifications.reduce((a, b) =>
                        a.created_at.isAfter(b.created_at) ? a : b
                    )

                    await api.create(`api/projects/${values.currentProjectId}/my_notifications/bookmark`, {
                        bookmark: latestNotification.created_at.toISOString(),
                    })

                    return {
                        last_read: latestNotification.created_at.toISOString(),
                        next: current.next,
                        results: current.results.map((ic) => ({ ...ic, unread: false })),
                    }
                },
            },
        ],
    })),
    listeners(({ actions, values, cache }) => ({
        togglePolling: ({ pageIsVisible }) => {
            if (values.realTimeNotificationsEnabled) {
                return
            }
            if (pageIsVisible) {
                actions.loadImportantChanges()
            } else {
                cache.disposables.dispose('pollTimeout')
            }
        },
        startSSE: () => {
            const token = values.currentTeam?.live_events_token
            if (!token) {
                actions.fallbackToPoll()
                return
            }

            const host = liveEventsHostOrigin()
            if (!host) {
                actions.fallbackToPoll()
                return
            }

            const url = `${host}/notifications`

            cache.sseConnection?.abort()
            const abortController = new AbortController()
            cache.sseConnection = abortController

            void api.stream(url, {
                headers: {
                    Authorization: `Bearer ${token}`,
                },
                signal: abortController.signal,
                onMessage: (event) => {
                    if (!values.isInitialLoadComplete) {
                        return
                    }
                    try {
                        const notification = JSON.parse(event.data) as InAppNotification
                        actions.notificationReceived(notification)
                        if (notification.priority === 'urgent') {
                            const iconMap: Record<string, JSX.Element> = {
                                comment_mention: <IconComment className="size-5 text-primary shrink-0" />,
                                alert_firing: <IconWarning className="size-5 text-warning shrink-0" />,
                                approval_requested: <IconCheckCircle className="size-5 text-success shrink-0" />,
                                approval_resolved: <IconCheckCircle className="size-5 text-success shrink-0" />,
                                pipeline_failure: <IconPlug className="size-5 text-danger shrink-0" />,
                                issue_assigned: <IconBug className="size-5 text-primary shrink-0" />,
                            }
                            const icon = iconMap[notification.notification_type] ?? (
                                <IconNotification className="size-5 text-secondary shrink-0" />
                            )
                            lemonToast.info(
                                <div className="flex items-start gap-2">
                                    {icon}
                                    <div className="min-w-0">
                                        <div className="font-semibold text-xs">{notification.title}</div>
                                        {notification.body && (
                                            <div className="text-xs text-secondary mt-0.5 line-clamp-1">
                                                {notification.body}
                                            </div>
                                        )}
                                    </div>
                                </div>,
                                {
                                    icon: false,
                                    autoClose: false,
                                    toastId: `notification-${notification.id}`,
                                    button: {
                                        label: 'Open notifications',
                                        action: () => notificationsMenuLogic.actions.openToUnread(),
                                    },
                                }
                            )
                        }
                    } catch {
                        // Ignore heartbeat or malformed messages
                    }
                },
                onError: () => {
                    actions.fallbackToPoll()
                },
            })
        },
        stopSSE: () => {
            cache.sseConnection?.abort()
            cache.sseConnection = null
            if (cache.pollTimer) {
                clearInterval(cache.pollTimer)
                cache.pollTimer = null
            }
        },
        fallbackToPoll: () => {
            cache.sseConnection?.abort()
            cache.sseConnection = null

            if (cache.pollTimer) {
                clearInterval(cache.pollTimer)
            }

            const poll = async (): Promise<void> => {
                try {
                    const resp = await api.get<{ count: number }>(
                        `api/environments/${values.currentProjectId}/notifications/unread_count/`
                    )
                    actions.setInAppUnreadCount(resp.count)
                } catch {
                    // Swallow
                }
            }

            void poll()
            cache.pollTimer = setInterval(() => void poll(), UNREAD_POLL_TIMEOUT)
        },
        notificationReceived: async () => {
            // Refresh unread count from server on each new notification
            try {
                const resp = await api.get<{ count: number }>(
                    `api/environments/${values.currentProjectId}/notifications/unread_count/`
                )
                actions.setInAppUnreadCount(resp.count)
            } catch {
                // Swallow
            }
        },
        markAsRead: async ({ id }) => {
            try {
                await api.create(`api/environments/${values.currentProjectId}/notifications/${id}/mark_read/`, {})
            } catch {
                // Swallow
            }
        },
        toggleRead: async ({ id }) => {
            const notification = values.inAppNotifications.find((n) => n.id === id)
            if (!notification) {
                return
            }
            const endpoint = notification.read ? 'mark_read' : 'mark_unread'
            try {
                await api.create(`api/environments/${values.currentProjectId}/notifications/${id}/${endpoint}/`, {})
            } catch {
                // Swallow
            }
            try {
                const resp = await api.get<{ count: number }>(
                    `api/environments/${values.currentProjectId}/notifications/unread_count/`
                )
                actions.setInAppUnreadCount(resp.count)
            } catch {
                // Swallow
            }
        },
        loadMoreNotifications: async () => {
            if (!values.hasMoreNotifications) {
                return
            }
            try {
                const resp = await api.get<{
                    results: InAppNotification[]
                    next: string | null
                }>(
                    `api/environments/${values.currentProjectId}/notifications/?limit=20&offset=${values.loadedFromApiCount}`
                )
                actions.appendInAppNotifications(resp.results, !!resp.next)
            } catch {
                // Swallow
            }
        },
    })),
    selectors({
        realTimeNotificationsEnabled: [
            (s) => [s.featureFlags],
            (featureFlags): boolean => !!featureFlags[FEATURE_FLAGS.REAL_TIME_NOTIFICATIONS],
        ],
        legacyNotifications: [
            (s) => [s.importantChanges],
            (importantChanges): HumanizedActivityLogItem[] => {
                try {
                    let importantChangesHumanized = humanize(importantChanges?.results || [], describerFor, true)

                    const flagPayload = posthog.getFeatureFlagPayload('changelog-notification')
                    const changelogNotifications = flagPayload
                        ? (flagPayload as JsonRecord[]).map(
                              (notification) =>
                                  ({
                                      markdown: notification.markdown,
                                      notificationDate: dayjs(notification.notificationDate as string),
                                      email: notification.email,
                                      name: notification.name,
                                  }) as ChangelogFlagPayload
                          )
                        : null

                    if (changelogNotifications) {
                        const lastRead = importantChanges?.last_read ? dayjs(importantChanges.last_read) : null

                        importantChangesHumanized = [
                            ...importantChangesHumanized,
                            ...changelogNotifications.map(
                                (changelogNotification) =>
                                    ({
                                        email: changelogNotification.email || 'joe@posthog.com',
                                        name: changelogNotification.name || 'Joe',
                                        isSystem: true,
                                        description: <LemonMarkdown>{changelogNotification.markdown}</LemonMarkdown>,
                                        created_at: changelogNotification.notificationDate,
                                        unread: lastRead?.isSameOrBefore(changelogNotification.notificationDate),
                                    }) as HumanizedActivityLogItem
                            ),
                        ]

                        importantChangesHumanized.sort((a: HumanizedActivityLogItem, b: HumanizedActivityLogItem) => {
                            if (a.created_at.isBefore(b.created_at)) {
                                return 1
                            } else if (a.created_at.isAfter(b.created_at)) {
                                return -1
                            }

                            return 0
                        })
                    }

                    return importantChangesHumanized
                } catch {
                    return []
                }
            },
        ],
        notifications: [
            (s) => [s.realTimeNotificationsEnabled, s.legacyNotifications, s.inAppNotifications],
            (
                realTimeEnabled,
                legacyNotifications,
                inAppNotifications
            ): HumanizedActivityLogItem[] | InAppNotification[] => {
                return realTimeEnabled ? inAppNotifications : legacyNotifications
            },
        ],
        hasNotifications: [(s) => [s.notifications], (notifications) => !!notifications.length],
        unreadCount: [
            (s) => [s.realTimeNotificationsEnabled, s.legacyNotifications, s.inAppUnreadCount],
            (realTimeEnabled, legacyNotifications, inAppUnreadCount): number => {
                if (realTimeEnabled) {
                    return inAppUnreadCount
                }
                return legacyNotifications.filter((ic) => ic.unread).length
            },
        ],
        hasUnread: [(s) => [s.unreadCount], (unreadCount) => unreadCount > 0],
    }),
    afterMount(({ cache, actions, values }) => {
        if (values.realTimeNotificationsEnabled) {
            // Start SSE first so it's connected, but messages are ignored until initial load completes
            actions.startSSE()

            // Load initial notifications from the REST API — this is the authoritative source
            void (async () => {
                try {
                    const resp = await api.get<{
                        results: InAppNotification[]
                        next: string | null
                    }>(`api/environments/${values.currentProjectId}/notifications/?limit=20`)
                    actions.setInAppNotifications(resp.results, !!resp.next)
                } catch {
                    // Swallow
                }
                try {
                    const countResp = await api.get<{ count: number }>(
                        `api/environments/${values.currentProjectId}/notifications/unread_count/`
                    )
                    actions.setInAppUnreadCount(countResp.count)
                } catch {
                    // Swallow
                }
                // Now SSE messages will be processed as truly new notifications
                actions.initialLoadDone()
            })()
        } else {
            cache.disposables.add(() => {
                const onVisibilityChange = (): void => {
                    actions.togglePolling(document.visibilityState === 'visible')
                }
                document.addEventListener('visibilitychange', onVisibilityChange)
                return () => document.removeEventListener('visibilitychange', onVisibilityChange)
            }, 'visibilityListener')
        }
    }),
    beforeUnmount(({ actions }) => {
        actions.stopSSE()
    }),
])
