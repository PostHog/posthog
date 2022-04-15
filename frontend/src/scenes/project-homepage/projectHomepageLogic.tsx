import { kea } from 'kea'

import { projectHomepageLogicType } from './projectHomepageLogicType'
import { teamLogic } from 'scenes/teamLogic'
import { dashboardLogic } from 'scenes/dashboard/dashboardLogic'
import { DashboardPlacement, InsightModel } from '~/types'
import api from 'lib/api'

export const projectHomepageLogic = kea<projectHomepageLogicType>({
    path: ['scenes', 'project-homepage', 'projectHomepageLogic'],
    connect: {
        values: [teamLogic, ['currentTeamId']],
    },

    selectors: {
        primaryDashboardId: [() => [teamLogic.selectors.currentTeam], (currentTeam) => currentTeam?.primary_dashboard],
        dashboardLogic: [
            (s) => [s.primaryDashboardId],
            (primaryDashboardId): ReturnType<typeof dashboardLogic.build> | null =>
                dashboardLogic.build(
                    { id: primaryDashboardId ?? undefined, placement: DashboardPlacement.ProjectHomepage },
                    false
                ),
        ],
    },

    loaders: ({ values }) => ({
        recentInsights: [
            [] as InsightModel[],
            {
                loadRecentInsights: async () => {
                    const response = await api.get(
                        `api/projects/${values.currentTeamId}/insights/?my_last_viewed=true&order=-my_last_viewed_at`
                    )
                    return response.results
                },
            },
        ],
    }),

    subscriptions: ({ cache }: projectHomepageLogicType) => ({
        dashboardLogic: (logic: ReturnType<typeof dashboardLogic.build>) => {
            cache.unmount?.()
            cache.unmount = logic ? logic.mount() : null
        },
    }),

    events: ({ cache, actions }) => ({
        afterMount: () => {
            cache.unmount?.()
            actions.loadRecentInsights()
        },
    }),
})
