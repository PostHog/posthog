import { actions, events, kea, listeners, path, reducers, selectors } from 'kea'
import { loaders } from 'kea-loaders'
import api from 'lib/api'
import { teamLogic } from 'scenes/teamLogic'
import { ActivityLogItem, humanize, HumanizedActivityLogItem } from 'lib/components/ActivityLog/humanizeActivity'

import type { notificationsLogicType } from './notificationsLogicType'
import { describerFor } from 'lib/components/ActivityLog/activityLogLogic'
import { dayjs } from 'lib/dayjs'
import posthog from 'posthog-js'
import { LemonMarkdown } from 'lib/lemon-ui/LemonMarkdown'

const POLL_TIMEOUT = 5 * 60 * 1000
const MARK_READ_TIMEOUT = 2500

export interface ChangelogFlagPayload {
    notificationDate: dayjs.Dayjs
    markdown: string
}

export interface ChangesResponse {
    results: ActivityLogItem[]
    last_read: string
}

export const notificationsLogic = kea<notificationsLogicType>([
    path(['layout', 'navigation', 'TopBar', 'notificationsLogic']),
    actions({
        toggleNotificationsPopover: true,
        togglePolling: (pageIsVisible: boolean) => ({ pageIsVisible }),
        setPollTimeout: (pollTimeout: number) => ({ pollTimeout }),
        setMarkReadTimeout: (markReadTimeout: number) => ({ markReadTimeout }),
        incrementErrorCount: true,
        clearErrorCount: true,
        markAllAsRead: (bookmarkDate: string) => ({ bookmarkDate }),
    }),
    loaders(({ actions, values }) => ({
        importantChanges: [
            null as ChangesResponse | null,
            {
                markAllAsRead: ({ bookmarkDate }) => {
                    const current = values.importantChanges
                    if (!current) {
                        return null
                    }

                    return {
                        last_read: bookmarkDate,
                        results: current.results.map((ic) => ({ ...ic, unread: false })),
                    }
                },
                loadImportantChanges: async (_, breakpoint) => {
                    await breakpoint(1)

                    clearTimeout(values.pollTimeout)

                    try {
                        const response = await api.get<ChangesResponse>(
                            `api/projects/${teamLogic.values.currentTeamId}/activity_log/important_changes`
                        )
                        // we can't rely on automatic success action here because we swallow errors so always succeed
                        actions.clearErrorCount()
                        return response
                    } catch (e) {
                        // swallow errors as this isn't user initiated
                        // increment a counter to backoff calling the API while errors persist
                        actions.incrementErrorCount()
                        return null
                    } finally {
                        const pollTimeoutMilliseconds = values.errorCounter
                            ? POLL_TIMEOUT * values.errorCounter
                            : POLL_TIMEOUT
                        const timeout = window.setTimeout(actions.loadImportantChanges, pollTimeoutMilliseconds)
                        actions.setPollTimeout(timeout)
                    }
                },
            },
        ],
    })),
    reducers({
        errorCounter: [
            0,
            {
                incrementErrorCount: (state) => (state >= 5 ? 5 : state + 1),
                clearErrorCount: () => 0,
            },
        ],
        isNotificationPopoverOpen: [
            false,
            {
                toggleNotificationsPopover: (state) => !state,
            },
        ],
        isPolling: [true, { togglePolling: (_, { pageIsVisible }) => pageIsVisible }],
        pollTimeout: [
            0,
            {
                setPollTimeout: (_, payload) => payload.pollTimeout,
            },
        ],
        markReadTimeout: [
            0,
            {
                setMarkReadTimeout: (_, payload) => payload.markReadTimeout,
            },
        ],
    }),
    listeners(({ values, actions }) => ({
        toggleNotificationsPopover: () => {
            if (!values.isNotificationPopoverOpen) {
                clearTimeout(values.markReadTimeout)
            } else {
                if (values.notifications?.[0]) {
                    const bookmarkDate = values.notifications.reduce((a, b) =>
                        a.created_at.isAfter(b.created_at) ? a : b
                    ).created_at
                    actions.setMarkReadTimeout(
                        window.setTimeout(() => {
                            void api
                                .create(
                                    `api/projects/${teamLogic.values.currentTeamId}/activity_log/bookmark_activity_notification`,
                                    {
                                        bookmark: bookmarkDate.toISOString(),
                                    }
                                )
                                .then(() => {
                                    actions.markAllAsRead(bookmarkDate.toISOString())
                                })
                        }, MARK_READ_TIMEOUT)
                    )
                }
            }
        },
    })),
    selectors({
        notifications: [
            (s) => [s.importantChanges],
            (importantChanges): HumanizedActivityLogItem[] => {
                try {
                    const importantChangesHumanized = humanize(importantChanges?.results || [], describerFor, true)

                    let changelogNotification: ChangelogFlagPayload | null = null
                    const flagPayload = posthog.getFeatureFlagPayload('changelog-notification')
                    if (flagPayload) {
                        changelogNotification = {
                            markdown: flagPayload['markdown'],
                            notificationDate: dayjs(flagPayload['notificationDate']),
                        } as ChangelogFlagPayload
                    }

                    if (changelogNotification) {
                        const lastRead = importantChanges?.last_read ? dayjs(importantChanges.last_read) : null
                        const changeLogIsUnread =
                            !!lastRead &&
                            (lastRead.isBefore(changelogNotification.notificationDate) ||
                                lastRead == changelogNotification.notificationDate)

                        const changelogNotificationHumanized: HumanizedActivityLogItem = {
                            email: 'joe@posthog.com',
                            name: 'Joe',
                            isSystem: true,
                            description: <LemonMarkdown>{changelogNotification.markdown}</LemonMarkdown>,
                            created_at: changelogNotification.notificationDate,
                            unread: changeLogIsUnread,
                        }
                        const notifications = [changelogNotificationHumanized, ...importantChangesHumanized]
                        notifications.sort((a, b) => {
                            if (a.created_at.isBefore(b.created_at)) {
                                return 1
                            } else if (a.created_at.isAfter(b.created_at)) {
                                return -1
                            } else {
                                return 0
                            }
                        })
                        return notifications
                    }

                    return humanize(importantChanges?.results || [], describerFor, true)
                } catch (e) {
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
    events(({ actions, values }) => ({
        afterMount: () => actions.loadImportantChanges(null),
        beforeUnmount: () => {
            clearTimeout(values.pollTimeout)
            clearTimeout(values.markReadTimeout)
        },
    })),
])
