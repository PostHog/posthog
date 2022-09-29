import { actions, events, kea, path, reducers } from 'kea'
import { loaders } from 'kea-loaders'
import api from 'lib/api'
import { teamLogic } from 'scenes/teamLogic'
import { ActivityLogItem, humanize, HumanizedActivityLogItem } from 'lib/components/ActivityLog/humanizeActivity'

import type { notificationsLogicType } from './notificationsLogicType'

const POLL_TIMEOUT = 5000

export const notificationsLogic = kea<notificationsLogicType>([
    path(['layout', 'navigation', 'TopBar', 'notificationsLogic']),
    actions({
        toggleNotificationsPopover: true,
        togglePolling: (pageIsVisible: boolean) => ({ pageIsVisible }),
        setPollTimeout: (pollTimeout: number) => ({ pollTimeout }),
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
                    const humanizedNotifications = response.flatMap((ali) => {
                        if (ali.scope === 'Insight') {
                            return humanize([ali], true)
                        } else if (ali.scope === 'FeatureFlag') {
                            return humanize([ali], true)
                        } else {
                            throw new Error('Cannot notify about activity log item in scope: ' + ali.scope)
                        }
                    })
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
    }),
    events(({ actions }) => ({
        afterMount: () => actions.loadImportantChanges(null),
    })),
])
