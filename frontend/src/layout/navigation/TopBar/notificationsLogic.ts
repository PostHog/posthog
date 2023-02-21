import { actions, events, kea, listeners, path, reducers, selectors } from 'kea'
import { loaders } from 'kea-loaders'
import api from 'lib/api'
import { teamLogic } from 'scenes/teamLogic'
import { ActivityLogItem, humanize, HumanizedActivityLogItem } from 'lib/components/ActivityLog/humanizeActivity'

import type { notificationsLogicType } from './notificationsLogicType'
import { describerFor } from 'lib/components/ActivityLog/activityLogLogic'

const POLL_TIMEOUT = 5 * 60 * 1000
const MARK_READ_TIMEOUT = 7500

export const notificationsLogic = kea<notificationsLogicType>([
    path(['layout', 'navigation', 'TopBar', 'notificationsLogic']),
    actions({
        toggleNotificationsPopover: true,
        togglePolling: (pageIsVisible: boolean) => ({ pageIsVisible }),
        setPollTimeout: (pollTimeout: number) => ({ pollTimeout }),
        setMarkReadTimeout: (markReadTimeout: number) => ({ markReadTimeout }),
        incrementErrorCount: true,
        clearErrorCount: true,
    }),
    loaders(({ actions, values }) => ({
        importantChanges: [
            [] as HumanizedActivityLogItem[],
            {
                loadImportantChanges: async (_, breakpoint) => {
                    await breakpoint(1)

                    clearTimeout(values.pollTimeout)

                    try {
                        const response = (await api.get(
                            `api/projects/${teamLogic.values.currentTeamId}/activity_log/important_changes`
                        )) as ActivityLogItem[]
                        // we can't rely on automatic success action here because we swallow errors so always succeed
                        actions.clearErrorCount()
                        return humanize(response, describerFor, true)
                    } catch (e) {
                        // swallow errors as this isn't user initiated
                        // increment a counter to backoff calling the API while errors persist
                        actions.incrementErrorCount()
                        return []
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
                if (values.importantChanges?.[0]) {
                    actions.setMarkReadTimeout(
                        window.setTimeout(async () => {
                            const bookmarkDate = values.importantChanges[0].created_at.toISOString()
                            await api.create(
                                `api/projects/${teamLogic.values.currentTeamId}/activity_log/bookmark_activity_notification`,
                                {
                                    bookmark: bookmarkDate,
                                }
                            )
                        }, MARK_READ_TIMEOUT)
                    )
                }
            }
        },
    })),
    selectors({
        unread: [(s) => [s.importantChanges], (importantChanges) => importantChanges.filter((ic) => ic.unread)],
        unreadCount: [(s) => [s.unread], (unread) => (unread || []).length],
        hasUnread: [(s) => [s.unreadCount], (unreadCount) => unreadCount > 0],
        hasImportantChanges: [(s) => [s.importantChanges], (importantChanges) => (importantChanges || []).length > 0],
    }),
    events(({ actions, values }) => ({
        afterMount: () => actions.loadImportantChanges(null),
        beforeUnmount: () => {
            clearTimeout(values.pollTimeout)
            clearTimeout(values.markReadTimeout)
        },
    })),
])
