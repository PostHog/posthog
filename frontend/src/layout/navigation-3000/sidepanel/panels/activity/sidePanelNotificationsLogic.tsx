import { actions, afterMount, beforeUnmount, connect, kea, listeners, path, reducers, selectors } from 'kea'
import { lazyLoaders } from 'kea-loaders'
import { router } from 'kea-router'
import posthog, { JsonRecord } from 'posthog-js'

import api from 'lib/api'
import { describerFor } from 'lib/components/ActivityLog/activityLogLogic'
import { HumanizedActivityLogItem, humanize } from 'lib/components/ActivityLog/humanizeActivity'
import { showCriticalNotificationToast } from 'lib/components/NotificationsMenu/notificationToasts'
import { FEATURE_FLAGS } from 'lib/constants'
import { dayjs } from 'lib/dayjs'
import { LemonDialog } from 'lib/lemon-ui/LemonDialog'
import { LemonMarkdown } from 'lib/lemon-ui/LemonMarkdown'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { retryWithBackoff, toParams } from 'lib/utils'
import { liveEventsHostOrigin } from 'lib/utils/apiHost'
import { organizationLogic } from 'scenes/organizationLogic'
import { projectLogic } from 'scenes/projectLogic'
import { teamLogic } from 'scenes/teamLogic'
import { urls } from 'scenes/urls'

import { connectToNotificationsSSE } from '~/layout/navigation-3000/sidepanel/panels/activity/notificationsSSE'
import { ChangesResponse } from '~/layout/navigation-3000/sidepanel/panels/activity/sidePanelActivityLogic'
import { InAppNotification, InsightShortId } from '~/types'

import { NotificationEventSourceTypeEnumApi } from 'products/notifications/frontend/generated/api.schemas'

import { sidePanelContextLogic } from '../../sidePanelContextLogic'
import { sidePanelStateLogic } from '../../sidePanelStateLogic'
import type { sidePanelNotificationsLogicType } from './sidePanelNotificationsLogicType'

const LEGACY_POLL_TIMEOUT = 5 * 60 * 1000
const SSE_RETRY_ATTEMPTS = 3
const SSE_RETRY_INITIAL_DELAY_MS = 30000
const SSE_RETRY_BACKOFF_MULTIPLIER = 4

const SOURCE_TYPE_TO_PATH: Record<NotificationEventSourceTypeEnumApi, (id: string) => string> = {
    replay: (id) => urls.replaySingle(id),
    notebook: (id) => urls.notebook(id),
    insight: (id) => urls.insightView(id as InsightShortId),
    feature_flag: (id) => urls.featureFlag(id),
    dashboard: (id) => urls.dashboard(id),
    survey: (id) => urls.survey(id),
    experiment: (id) => urls.experiment(id),
    error_tracking: (id) => urls.errorTrackingIssue(id),
}

export function buildNotificationSourcePath(notification: InAppNotification): string | null {
    if (notification.source_type && notification.source_id && notification.source_type in SOURCE_TYPE_TO_PATH) {
        return SOURCE_TYPE_TO_PATH[notification.source_type as NotificationEventSourceTypeEnumApi](
            notification.source_id
        )
    }
    return notification.source_url || null
}

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
            ['currentTeam', 'currentTeamId'],
            organizationLogic,
            ['currentOrganization'],
        ],
        actions: [sidePanelStateLogic, ['openSidePanel'], teamLogic, ['loadCurrentTeamSuccess']],
    })),
    actions({
        togglePolling: (pageIsVisible: boolean) => ({ pageIsVisible }),
        incrementErrorCount: true,
        clearErrorCount: true,
        markAllAsRead: true,
        loadImportantChanges: (onlyUnread = true) => ({ onlyUnread }),
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
        navigateToNotification: (notification: InAppNotification) => ({ notification }),
        loadMoreNotifications: true,
        initialLoadDone: true,
        startSSE: true,
        stopSSE: true,
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
                incrementErrorCount: (state) => {
                    const MAX_LEGACY_ERRORS = 5
                    return state >= MAX_LEGACY_ERRORS ? MAX_LEGACY_ERRORS : state + 1
                },
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
                            ? LEGACY_POLL_TIMEOUT * values.errorCounter
                            : LEGACY_POLL_TIMEOUT

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
            // Drop any pending focus-reconnect from a previous give-up; we're reconnecting now.
            cache.disposables.dispose('sseFocusReconnect')

            // TEMPORARY: lifecycle tracking for /notifications SSE connection.
            // Remove together with livestream_401_debug once root cause is known.
            posthog.capture('livestream_sse_startsse_called', {
                flag_enabled: values.realTimeNotificationsEnabled,
                has_token: !!values.currentTeam?.live_events_token,
                has_host: !!liveEventsHostOrigin(),
                had_prior_connection: !!cache.sseConnection,
            })

            if (!values.realTimeNotificationsEnabled) {
                posthog.capture('livestream_sse_startsse_skipped', { reason: 'flag_disabled' })
                return
            }

            const token = values.currentTeam?.live_events_token
            if (!token) {
                posthog.capture('livestream_sse_startsse_skipped', { reason: 'no_token' })
                return
            }

            const host = liveEventsHostOrigin()
            if (!host) {
                posthog.capture('livestream_sse_startsse_skipped', { reason: 'no_host' })
                return
            }

            const url = `${host}/notifications`

            cache.sseConnection?.abort()
            const abortController = new AbortController()
            cache.sseConnection = abortController
            cache.firstMessageLogged = false

            posthog.capture('livestream_sse_connecting', { url })

            void retryWithBackoff(
                () =>
                    connectToNotificationsSSE(
                        url,
                        token,
                        abortController.signal,
                        (notification) => {
                            if (!values.isInitialLoadComplete) {
                                return
                            }
                            actions.notificationReceived(notification)
                            if (notification.priority === 'critical') {
                                showCriticalNotificationToast(notification)
                            }
                        },
                        {
                            // TEMPORARY: livestream SSE lifecycle tracking.
                            onFirstMessage: () => {
                                if (!cache.firstMessageLogged) {
                                    cache.firstMessageLogged = true
                                    posthog.capture('livestream_sse_first_message', { url })
                                }
                            },
                            onError: (error) => {
                                posthog.capture('livestream_sse_error', {
                                    url,
                                    error_name: (error as Error | undefined)?.name,
                                    error_message: (error as Error | undefined)?.message,
                                })
                            },
                        }
                    ),
                {
                    maxAttempts: SSE_RETRY_ATTEMPTS,
                    initialDelayMs: SSE_RETRY_INITIAL_DELAY_MS,
                    backoffMultiplier: SSE_RETRY_BACKOFF_MULTIPLIER,
                    signal: abortController.signal,
                }
            ).catch((error) => {
                // retryWithBackoff rejects with AbortError on clean shutdown; only re-arm when it actually gave up.
                if (error instanceof DOMException && error.name === 'AbortError') {
                    return
                }
                // TEMPORARY: livestream SSE lifecycle tracking.
                posthog.capture('livestream_sse_max_errors', {
                    url,
                    max_attempts: SSE_RETRY_ATTEMPTS,
                })
                // Re-arm SSE the next time the user focuses the window. pauseOnPageHidden must be false
                // so the listener stays attached while the tab is backgrounded — that's exactly when we want it.
                cache.disposables.add(
                    () => {
                        const onFocus = (): void => {
                            posthog.capture('livestream_sse_refocus_reconnect', { url })
                            actions.startSSE()
                        }
                        window.addEventListener('focus', onFocus, { once: true })
                        return () => window.removeEventListener('focus', onFocus)
                    },
                    'sseFocusReconnect',
                    { pauseOnPageHidden: false }
                )
            })
        },
        stopSSE: () => {
            // TEMPORARY: livestream SSE lifecycle tracking.
            posthog.capture('livestream_sse_stopped', {
                had_connection: !!cache.sseConnection,
            })
            cache.disposables.dispose('sseFocusReconnect')
            cache.sseConnection?.abort()
            cache.sseConnection = null
        },
        navigateToNotification: ({ notification }) => {
            const path = values.sourcePathForNotification(notification)
            if (!path) {
                return
            }
            const isOtherProject = notification.team_id !== null && notification.team_id !== values.currentTeamId
            if (!isOtherProject) {
                if (!notification.read) {
                    actions.markAsRead(notification.id)
                }
                router.actions.push(path)
                return
            }
            const targetProjectName = values.projectNameForNotification(notification)
            LemonDialog.open({
                title: 'Leave current project?',
                description: `This notification is in ${targetProjectName ? `"${targetProjectName}"` : 'another project'}. Opening it will reload the page and you'll lose any unsaved work.`,
                primaryButton: {
                    children: 'Open',

                    onClick: async () => {
                        if (!notification.read) {
                            await actions.markAsRead(notification.id)
                        }
                        window.location.href = urls.project(notification.team_id!, path)
                    },
                },
                secondaryButton: {
                    children: 'Stay here',
                },
            })
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
        },
        loadCurrentTeamSuccess: () => {
            if (values.realTimeNotificationsEnabled && !cache.sseConnection) {
                actions.startSSE()
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
        projectNameForNotification: [
            (s) => [s.currentTeamId, s.currentOrganization],
            (currentTeamId, currentOrganization) => {
                return (notification: InAppNotification): string | null => {
                    if (notification.team_id === null || notification.team_id === currentTeamId) {
                        return null
                    }
                    return currentOrganization?.teams?.find((t) => t.id === notification.team_id)?.name ?? null
                }
            },
        ],
        sourcePathForNotification: [
            () => [],
            () =>
                (notification: InAppNotification): string | null =>
                    buildNotificationSourcePath(notification),
        ],
    }),
    afterMount(({ cache, actions, values }) => {
        if (values.realTimeNotificationsEnabled) {
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
                actions.initialLoadDone()
            })()

            if (values.currentTeam?.live_events_token) {
                actions.startSSE()
            }
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
