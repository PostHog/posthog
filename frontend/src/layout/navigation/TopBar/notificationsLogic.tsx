import { actions, connect, events, kea, listeners, path, reducers, selectors } from 'kea'
import { loaders } from 'kea-loaders'
import api from 'lib/api'
import { teamLogic } from 'scenes/teamLogic'
import { ActivityLogItem, humanize, HumanizedActivityLogItem } from 'lib/components/ActivityLog/humanizeActivity'

import type { notificationsLogicType } from './notificationsLogicType'
import { describerFor } from 'lib/components/ActivityLog/activityLogLogic'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { dayjs } from 'lib/dayjs'
import ReactMarkdown from 'react-markdown'
import posthog from 'posthog-js'

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
    connect({ values: [featureFlagLogic, ['payloadForKey']] }),
    actions({
        toggleNotificationsPopover: true,
        togglePolling: (pageIsVisible: boolean) => ({ pageIsVisible }),
        setPollTimeout: (pollTimeout: number) => ({ pollTimeout }),
        setMarkReadTimeout: (markReadTimeout: number) => ({ markReadTimeout }),
        incrementErrorCount: true,
        clearErrorCount: true,
        markAllAsRead: true,
    }),
    loaders(({ actions, values }) => ({
        importantChanges: [
            null as ChangesResponse | null,
            {
                markAllAsRead: () => {
                    return values.importantChanges.map((ic) => ({ ...ic, unread: false }))
                },
                loadImportantChanges: async (_, breakpoint) => {
                    await breakpoint(1)

                    clearTimeout(values.pollTimeout)

                    try {
                        const response = (await api.get(
                            `api/projects/${teamLogic.values.currentTeamId}/activity_log/important_changes`
                        )) as ChangesResponse
                        // we can't rely on automatic success action here because we swallow errors so always succeed
                        actions.clearErrorCount()
                        return response
                    } catch (e) {
                        // swallow errors as this isn't user initiated
                        // increment a counter to backoff calling the API while errors persist
                        actions.incrementErrorCount()
                        return { results: [], last_read: '' }
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
                    actions.setMarkReadTimeout(
                        window.setTimeout(async () => {
                            const bookmarkDate = values.notifications[0].created_at.toISOString()
                            await api.create(
                                `api/projects/${teamLogic.values.currentTeamId}/activity_log/bookmark_activity_notification`,
                                {
                                    bookmark: bookmarkDate,
                                }
                            )
                            actions.markAllAsRead()
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
                const importantChangesHumanized = humanize(importantChanges?.results || [], describerFor, true)

                let changelogNotification: ChangelogFlagPayload | null = null
                const flagPayload = posthog.getFeatureFlagPayload('changelog-notification')
                if (!!flagPayload) {
                    changelogNotification = {
                        markdown: flagPayload['markdown'],
                        notificationDate: dayjs(flagPayload['notificationDate']),
                    } as ChangelogFlagPayload
                }

                if (changelogNotification) {
                    const lastRead = importantChanges?.last_read ? dayjs(importantChanges.last_read) : null
                    const changeLogIsUnread = !!lastRead && lastRead < changelogNotification.notificationDate

                    const changelogNotificationHumanized: HumanizedActivityLogItem = {
                        email: 'joe@posthog.com',
                        name: 'Joe',
                        isSystem: true,
                        description: (
                            <>
                                <ReactMarkdown linkTarget="_blank">{changelogNotification.markdown}</ReactMarkdown>
                            </>
                        ),
                        created_at: changelogNotification.notificationDate,
                        unread: changeLogIsUnread,
                    }
                    return [changelogNotificationHumanized, ...importantChangesHumanized]
                }

                return humanize(importantChanges?.results || [], describerFor, true)
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
