import { actions, events, kea, listeners, path, reducers, selectors } from 'kea'
import { loaders } from 'kea-loaders'
import api from 'lib/api'
import { teamLogic } from 'scenes/teamLogic'
import { ActivityLogItem, humanize, HumanizedActivityLogItem } from 'lib/components/ActivityLog/humanizeActivity'

import type { notificationsLogicType } from './notificationsLogicType'

const POLL_TIMEOUT = 5000
const MARK_READ_TIMEOUT = 15000

export const notificationsLogic = kea<notificationsLogicType>([
    path(['layout', 'navigation', 'TopBar', 'notificationsLogic']),
    actions({
        toggleNotificationsPopover: true,
        togglePolling: (pageIsVisible: boolean) => ({ pageIsVisible }),
        setPollTimeout: (pollTimeout: number) => ({ pollTimeout }),
        setMarkReadTimeout: (markReadTimeout: number) => ({ markReadTimeout }),
    }),
    loaders(({ actions, values }) => ({
        importantChanges: [
            [] as HumanizedActivityLogItem[],
            {
                loadImportantChanges: async (_, breakpoint) => {
                    await breakpoint(1)

                    clearTimeout(values.pollTimeout)

                    const response = (await api.get(
                        `api/projects/${teamLogic.values.currentTeamId}/activity_log/important_changes`
                    )) as ActivityLogItem[]
                    const humanizedNotifications = humanize(response, true)

                    const timeout = window.setTimeout(actions.loadImportantChanges, POLL_TIMEOUT)
                    actions.setPollTimeout(timeout)

                    return humanizedNotifications
                },
            },
        ],
    })),
    reducers({
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
        hasUnread: [(s) => [s.importantChanges], (importantChanges) => importantChanges.find((ic) => ic.unread)],
    }),
    events(({ actions }) => ({
        afterMount: () => actions.loadImportantChanges(null),
    })),
])
