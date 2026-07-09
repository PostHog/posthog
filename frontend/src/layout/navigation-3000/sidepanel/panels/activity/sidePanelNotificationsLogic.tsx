import { actions, afterMount, beforeUnmount, connect, kea, listeners, path, reducers, selectors } from 'kea'
import { lazyLoaders } from 'kea-loaders'
import { router } from 'kea-router'
import posthog, { JsonRecord } from 'posthog-js'

import api from 'lib/api'
import { describerFor, ensureActivityDescribersLoaded } from 'lib/components/ActivityLog/activityLogLogic'
import { HumanizedActivityLogItem, humanize } from 'lib/components/ActivityLog/humanizeActivity'
import { showCriticalNotificationToast } from 'lib/components/NotificationsMenu/notificationToasts'
import { FEATURE_FLAGS } from 'lib/constants'
import { dayjs } from 'lib/dayjs'
import { LemonDialog } from 'lib/lemon-ui/LemonDialog'
import { LemonMarkdown } from 'lib/lemon-ui/LemonMarkdown'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { liveEventsHostOrigin } from 'lib/utils/apiHost'
import { retryWithBackoff } from 'lib/utils/async'
import { toParams } from 'lib/utils/url'
import { organizationLogic } from 'scenes/organizationLogic'
import { projectLogic } from 'scenes/projectLogic'
import { teamLogic } from 'scenes/teamLogic'
import { urls } from 'scenes/urls'

import { connectToNotificationsSSE } from '~/layout/navigation-3000/sidepanel/panels/activity/notificationsSSE'
import { ChangesResponse } from '~/layout/navigation-3000/sidepanel/panels/activity/sidePanelActivityLogic'
import { InAppNotification, InsightShortId, ResourceEditedEvent } from '~/types'

import {
    notificationsArchiveAllCreate,
    notificationsArchiveBulkCreate,
    notificationsArchiveCreate,
    notificationsList,
    notificationsMarkAllReadCreate,
    notificationsMarkReadBulkCreate,
    notificationsMarkReadCreate,
    notificationsMarkUnreadBulkCreate,
    notificationsMarkUnreadCreate,
} from 'products/notifications/frontend/generated/api'
import {
    NotificationEventSourceTypeEnumApi,
    NotificationsListParams,
} from 'products/notifications/frontend/generated/api.schemas'
import { RESOURCE_EDITED_EVENT_TYPE, resourceEditedLogic } from 'products/notifications/frontend/resourceEditedLogic'

import { sidePanelContextLogic } from '../../sidePanelContextLogic'
import type { sidePanelNotificationsLogicType } from './sidePanelNotificationsLogicType'

const LEGACY_POLL_TIMEOUT = 5 * 60 * 1000
const SSE_RETRY_ATTEMPTS = 3
const SSE_RETRY_INITIAL_DELAY_MS = 30000
const SSE_RETRY_BACKOFF_MULTIPLIER = 4

// Notifications fetched per page for the in-app list (initial load + "Load more"). Backend max_limit is 100.
const NOTIFICATION_PAGE_SIZE = 30

// Maps each source type to a path builder from `source_id`, or `null` to fall through to the
// backend-provided `source_url` (customer_analytics carries a precise account deep-link a
// source_id→path mapping can't build). Kept as a full `Record` — not `Partial` — so adding a
// `NotificationEventSourceTypeEnumApi` value fails the build until it's handled here.
const SOURCE_TYPE_TO_PATH: Record<NotificationEventSourceTypeEnumApi, ((id: string) => string) | null> = {
    replay: (id) => urls.replaySingle(id),
    notebook: (id) => urls.notebook(id),
    insight: (id) => urls.insightView(id as InsightShortId),
    feature_flag: (id) => urls.featureFlag(id),
    dashboard: (id) => urls.dashboard(id),
    survey: (id) => urls.survey(id),
    experiment: (id) => urls.experiment(id),
    error_tracking: (id) => urls.errorTrackingIssue(id),
    customer_analytics: null,
}

export interface NotificationGroup {
    group_key: string
    representative: InAppNotification
    count: number
    first_seen: string
    last_seen: string
    children: InAppNotification[]
    has_unread: boolean
    has_archivable: boolean
    full_children_loaded: boolean
}

export function groupKey(n: InAppNotification): string {
    const localDay = dayjs(n.created_at).format('YYYY-MM-DD')
    return `${n.notification_type}|${n.target_type}:${n.target_id}|${n.resource_type ?? ''}:${
        n.resource_id ?? ''
    }|${localDay}`
}

export function buildGroups(notifications: InAppNotification[], loadedGroupKeys: Set<string>): NotificationGroup[] {
    const groups: NotificationGroup[] = []
    const byKey = new Map<string, NotificationGroup>()
    for (const n of notifications) {
        const key = groupKey(n)
        const existing = byKey.get(key)
        if (existing) {
            existing.children.push(n)
            existing.count = existing.children.length
            if (dayjs(n.created_at).isBefore(existing.first_seen)) {
                existing.first_seen = n.created_at
            }
            if (dayjs(n.created_at).isAfter(existing.last_seen)) {
                existing.last_seen = n.created_at
            }
            if (!n.read) {
                existing.has_unread = true
            }
            if (n.archivable) {
                existing.has_archivable = true
            }
            continue
        }
        byKey.set(key, {
            group_key: key,
            representative: n,
            count: 1,
            first_seen: n.created_at,
            last_seen: n.created_at,
            children: [n],
            has_unread: !n.read,
            has_archivable: n.archivable,
            full_children_loaded: loadedGroupKeys.has(key),
        })
        groups.push(byKey.get(key)!)
    }
    return groups
}

export function buildNotificationSourcePath(notification: InAppNotification): string | null {
    const toPath = notification.source_type
        ? SOURCE_TYPE_TO_PATH[notification.source_type as NotificationEventSourceTypeEnumApi]
        : undefined
    if (toPath && notification.source_id) {
        return toPath(notification.source_id)
    }
    return notification.source_url || null
}

// When the recap experience is enabled, send digest clicks to the recap page instead of the raw
// dashboard. The digest's source_url is `/project/{id}/web?...`; only the `/web` segment is rewritten.
export function withRecapSourceUrl(notification: InAppNotification): InAppNotification {
    if (!notification.source_url) {
        return notification
    }
    return { ...notification, source_url: notification.source_url.replace(/\/web(?=$|[?#])/, '/web/recap') }
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
        actions: [teamLogic, ['loadCurrentTeamSuccess'], resourceEditedLogic, ['resourceEdited']],
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
        archiveNotification: (id: string) => ({ id }),
        archiveGroup: (group: NotificationGroup) => ({ group }),
        archiveAll: true,
        removeNotifications: (ids: string[]) => ({ ids }),
        refreshInAppUnreadCount: true,
        setArchivedNotifications: (notifications: InAppNotification[], hasMore: boolean) => ({
            notifications,
            hasMore,
        }),
        appendArchivedNotifications: (notifications: InAppNotification[], hasMore: boolean) => ({
            notifications,
            hasMore,
        }),
        loadArchivedNotifications: true,
        loadMoreArchived: true,
        loadMoreArchivedSuccess: (count: number) => ({ count }),
        loadArchivedGroupChildren: (group: NotificationGroup) => ({ group }),
        navigateToNotification: (notification: InAppNotification) => ({ notification }),
        loadMoreNotifications: true,
        loadMoreNotificationsSuccess: (count: number) => ({ count }),
        loadGroupChildren: (group: NotificationGroup) => ({ group }),
        markGroupChildrenLoaded: (groupKey: string) => ({ groupKey }),
        setGroupLoading: (groupKey: string, loading: boolean) => ({ groupKey, loading }),
        toggleGroupExpanded: (groupKey: string) => ({ groupKey }),
        toggleGroupRead: (group: NotificationGroup) => ({ group }),
        setGroupChildrenRead: (groupKey: string, read: boolean) => ({ groupKey, read }),
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
                removeNotifications: (state, { ids }) => {
                    const toRemove = new Set(ids)
                    return state.filter((n) => !toRemove.has(n.id))
                },
                markAsRead: (state, { id }) =>
                    state.map((n) => (n.id === id ? { ...n, read: true, read_at: new Date().toISOString() } : n)),
                toggleRead: (state, { id }) =>
                    state.map((n) =>
                        n.id === id ? { ...n, read: !n.read, read_at: n.read ? null : new Date().toISOString() } : n
                    ),
                markAllAsRead: (state) =>
                    state.map((n) => (n.read ? n : { ...n, read: true, read_at: new Date().toISOString() })),
                setGroupChildrenRead: (state, { groupKey: key, read }) =>
                    state.map((n) =>
                        groupKey(n) === key ? { ...n, read, read_at: read ? new Date().toISOString() : null } : n
                    ),
            },
        ],
        // Tracks how many items the main list has consumed from the server, used as the
        // offset for `loadMoreNotifications`. Kept distinct from `inAppNotifications.length`
        // because expanding a group adds children via `appendInAppNotifications` and those
        // must not advance the main-list cursor (or `loadMoreNotifications` would skip a page).
        mainListOffset: [
            0,
            {
                setInAppNotifications: (_, { notifications }) => notifications.length,
                loadMoreNotificationsSuccess: (state, { count }) => state + count,
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
        // Archived notifications are a separate, lazily-loaded data source so the active list is
        // never polluted. They mirror the main-list reducers (offset cursor, has-more, loading).
        archivedNotifications: [
            [] as InAppNotification[],
            {
                setArchivedNotifications: (_, { notifications }) => notifications,
                appendArchivedNotifications: (state, { notifications }) => {
                    const existingIds = new Set(state.map((n) => n.id))
                    const newItems = notifications.filter((n) => !existingIds.has(n.id))
                    return [...state, ...newItems]
                },
            },
        ],
        archivedLoaded: [
            false,
            {
                setArchivedNotifications: () => true,
            },
        ],
        archivedListOffset: [
            0,
            {
                setArchivedNotifications: (_, { notifications }) => notifications.length,
                loadMoreArchivedSuccess: (state, { count }) => state + count,
            },
        ],
        hasMoreArchived: [
            false,
            {
                setArchivedNotifications: (_, { hasMore }) => hasMore,
                appendArchivedNotifications: (_, { hasMore }) => hasMore,
            },
        ],
        isLoadingMoreArchived: [
            false,
            {
                loadMoreArchived: () => true,
                appendArchivedNotifications: () => false,
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
        // Notifications the user explicitly toggled read/unread this session. They're exempt from
        // auto-mark-on-view, so a deliberate "keep this unread" isn't silently undone 3s later.
        // In-memory only, so a page reload clears it and auto-mark resumes for everything.
        manuallyToggledIds: [
            new Set<string>() as Set<string>,
            {
                toggleRead: (state, { id }) => {
                    const next = new Set(state)
                    next.add(id)
                    return next
                },
                markAllAsRead: () => new Set<string>(),
            },
        ],
        loadedGroupKeys: [
            new Set<string>() as Set<string>,
            {
                markGroupChildrenLoaded: (state, { groupKey: key }) => {
                    const next = new Set(state)
                    next.add(key)
                    return next
                },
            },
        ],
        expandedGroupKeys: [
            new Set<string>() as Set<string>,
            {
                toggleGroupExpanded: (state, { groupKey: key }) => {
                    const next = new Set(state)
                    if (next.has(key)) {
                        next.delete(key)
                    } else {
                        next.add(key)
                    }
                    return next
                },
            },
        ],
        loadingGroupKeys: [
            new Set<string>() as Set<string>,
            {
                setGroupLoading: (state, { groupKey: key, loading }) => {
                    const next = new Set(state)
                    if (loading) {
                        next.add(key)
                    } else {
                        next.delete(key)
                    }
                    return next
                },
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
                        const [response] = await Promise.all([
                            api.get<ChangesResponse>(
                                `api/projects/${values.currentProjectId}/my_notifications?` +
                                    toParams({ unread: onlyUnread })
                            ),
                            ensureActivityDescribersLoaded(),
                        ])

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
                        await notificationsMarkAllReadCreate((values.currentProjectId ?? '').toString())
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
    listeners(({ actions, values, cache }) => {
        const fetchGroupChildren = async (group: NotificationGroup, archived = false): Promise<void> => {
            if (group.full_children_loaded) {
                return
            }
            actions.setGroupLoading(group.group_key, true)
            const day = dayjs(group.last_seen).startOf('day')
            const params: NotificationsListParams = {
                notification_type: group.representative.notification_type,
                target_type: group.representative.target_type,
                target_id: group.representative.target_id,
                created_after: day.toISOString(),
                created_before: day.add(1, 'day').toISOString(),
                limit: 100,
            }
            if (archived) {
                params.archived = true
            }
            if (group.representative.resource_type) {
                params.resource_type = group.representative.resource_type
            }
            if (group.representative.resource_id) {
                params.resource_id = group.representative.resource_id
            }
            try {
                const resp = await notificationsList((values.currentProjectId ?? '').toString(), params)
                const results = resp.results as InAppNotification[]
                if (archived) {
                    actions.appendArchivedNotifications(results, values.hasMoreArchived)
                } else {
                    actions.appendInAppNotifications(results, values.hasMoreNotifications)
                }
                actions.markGroupChildrenLoaded(group.group_key)
            } catch {
                // Swallow
            } finally {
                actions.setGroupLoading(group.group_key, false)
            }
        }

        return {
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
                // The SSE connection is managed by a disposable named 'sseConnection' so the
                // kea-disposables plugin auto-aborts it when the tab is hidden and reopens it
                // on visibilitychange. This keeps an idle background tab from holding a
                // long-lived streaming Response — that was accumulating in Blink's
                // partition_alloc/buffer + blink_gc/<unspecified> on production tabs.
                // Reconnect from focus-on-give-up still uses a separate 'sseFocusReconnect'
                // disposable so users who stay on a foreground tab past max-attempts retry on
                // window refocus.
                //
                // Lifecycle telemetry now fires on every visibility cycle (the disposable's
                // setup/teardown run on resume/pause), so we tag each capture with a `reason`
                // so existing dashboards can still distinguish initial connects, team-driven
                // reloads, focus-reconnects, and pure visibility transitions.
                // `cache.nextStartReason` / `cache.nextStopReason` carry the caller's intent
                // into the factory + teardown; the disposable plugin's pause/resume cycle
                // doesn't go through this action so the cache values default to
                // 'visibility_resume' / 'visibility_pause'.
                const startReason = cache.nextStartReason ?? 'initial'
                cache.nextStartReason = null
                cache.nextStopReason = 'replaced'
                cache.disposables.dispose('sseFocusReconnect')
                cache.disposables.dispose('sseConnection')
                cache.nextStopReason = null
                cache.nextStartReason = startReason

                cache.disposables.add(
                    () => {
                        const reason = cache.nextStartReason ?? 'visibility_resume'
                        cache.nextStartReason = null
                        // TEMPORARY: lifecycle tracking for /notifications SSE connection.
                        // Remove together with livestream_401_debug once root cause is known.
                        posthog.capture('livestream_sse_startsse_called', {
                            reason,
                            flag_enabled: values.realTimeNotificationsEnabled,
                            has_token: !!values.currentTeam?.live_events_token,
                            has_host: !!liveEventsHostOrigin(),
                            had_prior_connection: !!cache.sseConnection,
                        })

                        if (!values.realTimeNotificationsEnabled) {
                            posthog.capture('livestream_sse_startsse_skipped', { reason: 'flag_disabled' })
                            return () => {}
                        }

                        const token = values.currentTeam?.live_events_token
                        if (!token) {
                            posthog.capture('livestream_sse_startsse_skipped', { reason: 'no_token' })
                            return () => {}
                        }

                        const host = liveEventsHostOrigin()
                        if (!host) {
                            posthog.capture('livestream_sse_startsse_skipped', { reason: 'no_host' })
                            return () => {}
                        }

                        const url = `${host}/notifications`

                        const abortController = new AbortController()
                        cache.sseConnection = abortController
                        cache.firstMessageLogged = false

                        posthog.capture('livestream_sse_connecting', { url, reason })

                        void retryWithBackoff(
                            () =>
                                connectToNotificationsSSE(
                                    url,
                                    token,
                                    abortController.signal,
                                    (notification) => {
                                        // Transient "edited elsewhere" events ride this stream but are
                                        // not inbox notifications — forward them to interested editors and
                                        // skip the unread-count / toast / list handling below.
                                        if (notification.notification_type === RESOURCE_EDITED_EVENT_TYPE) {
                                            actions.resourceEdited(notification as unknown as ResourceEditedEvent)
                                            return
                                        }
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
                            // retryWithBackoff rejects with AbortError on clean shutdown
                            // (including when the disposable is paused for visibilitychange);
                            // only re-arm when it actually gave up.
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
                                        cache.nextStartReason = 'focus_reconnect'
                                        actions.startSSE()
                                    }
                                    window.addEventListener('focus', onFocus, { once: true })
                                    return () => window.removeEventListener('focus', onFocus)
                                },
                                'sseFocusReconnect',
                                { pauseOnPageHidden: false }
                            )
                        })

                        return () => {
                            // TEMPORARY: livestream SSE lifecycle tracking. `reason` tags
                            // whether this teardown was an explicit stop, a replacement by
                            // a later startSSE call, or the disposable pausing for a
                            // hidden tab so dashboards can still distinguish them.
                            const stopReason = cache.nextStopReason ?? 'visibility_pause'
                            cache.nextStopReason = null
                            posthog.capture('livestream_sse_stopped', {
                                reason: stopReason,
                                had_connection: !!cache.sseConnection,
                            })
                            abortController.abort()
                            if (cache.sseConnection === abortController) {
                                cache.sseConnection = null
                            }
                        }
                    },
                    'sseConnection',
                    { pauseOnPageHidden: true }
                )
            },
            stopSSE: () => {
                cache.nextStopReason = 'explicit_stop'
                cache.disposables.dispose('sseFocusReconnect')
                cache.disposables.dispose('sseConnection')
                cache.nextStopReason = null
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
                    await notificationsMarkReadCreate((values.currentProjectId ?? '').toString(), id)
                } catch {
                    // Swallow
                }
            },
            toggleRead: async ({ id }) => {
                // `notification.read` here is the *target* state — the toggleRead reducer above
                // has already flipped it, so we call the endpoint matching the new state.
                const notification = values.inAppNotifications.find((n) => n.id === id)
                if (!notification) {
                    return
                }
                // Keep the unread count (gates the badge + "Mark all as read") in sync with the toggle
                actions.setInAppUnreadCount(Math.max(0, values.inAppUnreadCount + (notification.read ? -1 : 1)))
                const projectId = (values.currentProjectId ?? '').toString()
                try {
                    if (notification.read) {
                        await notificationsMarkReadCreate(projectId, id)
                    } else {
                        await notificationsMarkUnreadCreate(projectId, id)
                    }
                } catch {
                    // Swallow
                }
            },
            refreshInAppUnreadCount: async () => {
                try {
                    const countResp = await api.get<{ count: number }>(
                        `api/environments/${values.currentProjectId}/notifications/unread_count/`
                    )
                    actions.setInAppUnreadCount(countResp.count)
                } catch {
                    // Swallow
                }
            },
            archiveNotification: async ({ id }) => {
                const notification = values.inAppNotifications.find((n) => n.id === id)
                if (!notification || !notification.archivable) {
                    return
                }
                actions.removeNotifications([id])
                if (!notification.read) {
                    actions.setInAppUnreadCount(Math.max(0, values.inAppUnreadCount - 1))
                }
                try {
                    await notificationsArchiveCreate((values.currentProjectId ?? '').toString(), id)
                } catch {
                    // Swallow
                }
                // Reconcile against the server: the optimistic decrement above only covers the
                // loaded page, so resync the authoritative count.
                await actions.refreshInAppUnreadCount()
            },
            archiveGroup: async ({ group }) => {
                if (!group.full_children_loaded) {
                    await fetchGroupChildren(group)
                }
                const refreshed = values.groups.find((g) => g.group_key === group.group_key)
                if (!refreshed) {
                    return
                }
                const archivable = refreshed.children.filter((c) => c.archivable)
                const ids = archivable.map((c) => c.id)
                if (ids.length === 0) {
                    return
                }
                const unreadArchived = archivable.filter((c) => !c.read).length
                actions.removeNotifications(ids)
                if (unreadArchived > 0) {
                    actions.setInAppUnreadCount(Math.max(0, values.inAppUnreadCount - unreadArchived))
                }
                try {
                    await notificationsArchiveBulkCreate((values.currentProjectId ?? '').toString(), {
                        notification_ids: ids,
                    })
                } catch {
                    // Swallow
                }
                await actions.refreshInAppUnreadCount()
            },
            archiveAll: async () => {
                const archivable = values.inAppNotifications.filter((n) => n.archivable)
                const ids = archivable.map((n) => n.id)
                if (ids.length === 0) {
                    return
                }
                const unreadArchived = archivable.filter((n) => !n.read).length
                actions.removeNotifications(ids)
                if (unreadArchived > 0) {
                    actions.setInAppUnreadCount(Math.max(0, values.inAppUnreadCount - unreadArchived))
                }
                try {
                    await notificationsArchiveAllCreate((values.currentProjectId ?? '').toString())
                } catch {
                    // Swallow
                }
                await actions.refreshInAppUnreadCount()
            },
            loadArchivedNotifications: async () => {
                try {
                    const resp = await notificationsList((values.currentProjectId ?? '').toString(), {
                        limit: 20,
                        archived: true,
                    })
                    actions.setArchivedNotifications(resp.results as InAppNotification[], !!resp.next)
                } catch {
                    // Swallow
                }
            },
            loadMoreArchived: async () => {
                if (!values.hasMoreArchived) {
                    return
                }
                try {
                    const resp = await notificationsList((values.currentProjectId ?? '').toString(), {
                        limit: 20,
                        offset: values.archivedListOffset,
                        archived: true,
                    })
                    const results = resp.results as InAppNotification[]
                    actions.appendArchivedNotifications(results, !!resp.next)
                    actions.loadMoreArchivedSuccess(results.length)
                } catch {
                    // Swallow
                }
            },
            loadArchivedGroupChildren: async ({ group }) => {
                await fetchGroupChildren(group, true)
            },
            loadCurrentTeamSuccess: () => {
                if (values.realTimeNotificationsEnabled && !cache.sseConnection) {
                    cache.nextStartReason = 'team_reload'
                    actions.startSSE()
                }
            },
            loadMoreNotifications: async () => {
                if (!values.hasMoreNotifications) {
                    return
                }
                try {
                    const resp = await notificationsList((values.currentProjectId ?? '').toString(), {
                        limit: NOTIFICATION_PAGE_SIZE,
                        offset: values.mainListOffset,
                    })
                    const results = resp.results as InAppNotification[]
                    actions.appendInAppNotifications(results, !!resp.next)
                    actions.loadMoreNotificationsSuccess(results.length)
                } catch {
                    // Swallow
                }
            },
            loadGroupChildren: async ({ group }) => {
                await fetchGroupChildren(group)
            },
            toggleGroupRead: async ({ group }) => {
                if (!group.full_children_loaded) {
                    await fetchGroupChildren(group)
                }
                const refreshed = values.groups.find((g) => g.group_key === group.group_key)
                if (!refreshed) {
                    return
                }
                const ids = refreshed.children.map((c) => c.id)
                const targetRead = refreshed.has_unread
                const unreadDelta = targetRead
                    ? -refreshed.children.filter((c) => !c.read).length
                    : refreshed.children.filter((c) => c.read).length
                actions.setGroupChildrenRead(refreshed.group_key, targetRead)
                if (unreadDelta !== 0) {
                    actions.setInAppUnreadCount(Math.max(0, values.inAppUnreadCount + unreadDelta))
                }
                const projectId = (values.currentProjectId ?? '').toString()
                try {
                    if (targetRead) {
                        await notificationsMarkReadBulkCreate(projectId, { notification_ids: ids })
                    } else {
                        await notificationsMarkUnreadBulkCreate(projectId, { notification_ids: ids })
                    }
                } catch {
                    // Swallow; selector reflects optimistic state
                }
            },
        }
    }),
    selectors({
        realTimeNotificationsEnabled: [
            (s) => [s.featureFlags],
            (featureFlags): boolean => !!featureFlags[FEATURE_FLAGS.REAL_TIME_NOTIFICATIONS],
        ],
        archivingEnabled: [
            (s) => [s.featureFlags],
            (featureFlags): boolean => !!featureFlags[FEATURE_FLAGS.CLEARABLE_NOTIFICATIONS],
        ],
        legacyNotifications: [
            (s) => [s.importantChanges],
            (importantChanges): HumanizedActivityLogItem[] => {
                try {
                    let importantChangesHumanized = humanize(importantChanges?.results || [], describerFor, true)

                    // 'changelog-notification' is an externally managed flag, not a FEATURE_FLAGS key, so it's read directly.
                    const flagPayload = posthog.getFeatureFlagResult('changelog-notification', {
                        send_event: false,
                    })?.payload
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
        hasArchivableNotifications: [
            (s) => [s.inAppNotifications],
            (inAppNotifications): boolean => inAppNotifications.some((n) => n.archivable),
        ],
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
        // Unread among the rows actually loaded into the panel. The panel's "Mark all as read"
        // button and Unread tab key off this — not `inAppUnreadCount`, a separately-fetched server
        // total that's hand-patched at several call sites — so they can never drift from the
        // visible rows. `inAppUnreadCount` stays the source for the global bell badge.
        loadedUnreadCount: [
            (s) => [s.inAppNotifications],
            (inAppNotifications): number => inAppNotifications.filter((n) => !n.read).length,
        ],
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
            (s) => [s.featureFlags],
            (featureFlags) =>
                (notification: InAppNotification): string | null => {
                    // When the recap flag is on, the digest links to the recap page instead of the raw dashboard
                    const recapEnabled = !!featureFlags[FEATURE_FLAGS.WEB_ANALYTICS_RECAP]
                    const target =
                        recapEnabled && notification.notification_type === 'web_analytics_digest'
                            ? withRecapSourceUrl(notification)
                            : notification
                    return buildNotificationSourcePath(target)
                },
        ],
        groups: [
            (s) => [s.inAppNotifications, s.loadedGroupKeys],
            (notifications: InAppNotification[], loadedGroupKeys: Set<string>): NotificationGroup[] =>
                buildGroups(notifications, loadedGroupKeys),
        ],
        archivedGroups: [
            (s) => [s.archivedNotifications, s.loadedGroupKeys],
            (notifications: InAppNotification[], loadedGroupKeys: Set<string>): NotificationGroup[] =>
                buildGroups(notifications, loadedGroupKeys),
        ],
    }),
    afterMount(({ cache, actions, values }) => {
        if (values.realTimeNotificationsEnabled) {
            void (async () => {
                try {
                    const resp = await notificationsList((values.currentProjectId ?? '').toString(), {
                        limit: NOTIFICATION_PAGE_SIZE,
                    })
                    actions.setInAppNotifications(resp.results as InAppNotification[], !!resp.next)
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
