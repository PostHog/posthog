import { actions, afterMount, beforeUnmount, connect, kea, listeners, path, reducers, selectors } from 'kea'
import { lazyLoaders } from 'kea-loaders'
import posthog, { JsonRecord } from 'posthog-js'

import api from 'lib/api'
import { describerFor } from 'lib/components/ActivityLog/activityLogLogic'
import { HumanizedActivityLogItem, humanize } from 'lib/components/ActivityLog/humanizeActivity'
import { dayjs } from 'lib/dayjs'
import { LemonMarkdown } from 'lib/lemon-ui/LemonMarkdown'
import { toParams } from 'lib/utils'
import { projectLogic } from 'scenes/projectLogic'

import { ChangesResponse } from '~/layout/navigation-3000/sidepanel/panels/activity/sidePanelActivityLogic'

import { sidePanelStateLogic } from '../../sidePanelStateLogic'
import { sidePanelContextLogic } from '../sidePanelContextLogic'
import type { sidePanelNotificationsLogicType } from './sidePanelNotificationsLogicType'

const POLL_TIMEOUT = 5 * 60 * 1000

export interface ChangelogFlagPayload {
    notificationDate: dayjs.Dayjs

    // Images can be embedded directly in the markdown using ![alt text](url) syntax.
    // LemonMarkdown will render them.
    // For optimal display, ensure images are reasonably sized (e.g., width < 800px)
    // and optimized for web (e.g., < 500KB).
    // We suggest you upload it to a CDN to reduce load times/server load.
    // If you're a PostHog employee, check https://posthog.com/handbook/engineering/posthog-com/assets out
    markdown: string

    // Optional fields used if you want to override this to a specific person rather than Joe
    name?: string
    email?: string
}

export const sidePanelNotificationsLogic = kea<sidePanelNotificationsLogicType>([
    path(['layout', 'navigation-3000', 'sidepanel', 'panels', 'activity', 'sidePanelNotificationsLogic']),
    connect(() => ({
        values: [sidePanelContextLogic, ['sceneSidePanelContext'], projectLogic, ['currentProjectId']],
        actions: [sidePanelStateLogic, ['openSidePanel']],
    })),
    actions({
        togglePolling: (pageIsVisible: boolean) => ({ pageIsVisible }),
        incrementErrorCount: true,
        clearErrorCount: true,
        markAllAsRead: true,
        loadImportantChanges: (onlyUnread = true) => ({ onlyUnread }),
    }),
    reducers({
        errorCounter: [
            0,
            {
                incrementErrorCount: (state) => (state >= 5 ? 5 : state + 1),
                clearErrorCount: () => 0,
            },
        ],
    }),
    lazyLoaders(({ actions, values, cache }) => ({
        importantChanges: [
            null as ChangesResponse | null,
            {
                loadImportantChanges: async ({ onlyUnread }, breakpoint) => {
                    await breakpoint(1)

                    clearTimeout(cache.pollTimeout)

                    try {
                        const response = await api.get<ChangesResponse>(
                            `api/projects/${values.currentProjectId}/my_notifications?` +
                                toParams({ unread: onlyUnread })
                        )

                        // we can't rely on automatic success action here because we swallow errors so always succeed
                        actions.clearErrorCount()
                        return response
                    } catch {
                        // swallow errors as this isn't user initiated
                        // increment a counter to backoff calling the API while errors persist
                        actions.incrementErrorCount()
                        return null
                    } finally {
                        const pollTimeoutMilliseconds = values.errorCounter
                            ? POLL_TIMEOUT * values.errorCounter
                            : POLL_TIMEOUT

                        cache.pollTimeout = window.setTimeout(actions.loadImportantChanges, pollTimeoutMilliseconds)
                    }
                },
                markAllAsRead: async () => {
                    const current = values.importantChanges
                    if (!current) {
                        return null
                    }

                    const latestNotification = values.notifications.reduce((a, b) =>
                        a.created_at.isAfter(b.created_at) ? a : b
                    )

                    const hasUnread = values.notifications.some((ic) => ic.unread)

                    if (!hasUnread) {
                        return current
                    }

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
    listeners(({ actions, cache }) => ({
        togglePolling: ({ pageIsVisible }) => {
            if (pageIsVisible) {
                actions.loadImportantChanges()
            } else {
                clearTimeout(cache.pollTimeout)
            }
        },
    })),
    selectors({
        notifications: [
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

                        // Sorting this inside the `if` case because there's no need to sort the changelog notifications
                        // if there are no changelog notifications, since they come from the backend sorted already.
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
                    // swallow errors as this isn't user initiated
                    return []
                }
            },
        ],

        hasNotifications: [(s) => [s.notifications], (notifications) => !!notifications.length],
        unread: [
            (s) => [s.notifications],
            (notifications: HumanizedActivityLogItem[]) => notifications.filter((ic) => ic.unread),
        ],
        unreadCount: [(s) => [s.unread], (unread) => (unread || []).length],
        hasUnread: [(s) => [s.unreadCount], (unreadCount) => unreadCount > 0],
    }),
    afterMount(({ cache, actions }) => {
        cache.onVisibilityChange = () => {
            actions.togglePolling(document.visibilityState === 'visible')
        }
        document.addEventListener('visibilitychange', cache.onVisibilityChange)
    }),
    beforeUnmount(({ cache }) => {
        clearTimeout(cache.pollTimeout)
        document.removeEventListener('visibilitychange', cache.onVisibilityChange)
    }),
])
