import { afterMount, connect, kea, path, selectors } from 'kea'

import type { projectHomepageLogicType } from './projectHomepageLogicType'
import { teamLogic } from 'scenes/teamLogic'
import { DashboardLogicProps } from 'scenes/dashboard/dashboardLogic'
import { DashboardPlacement, InsightModel, PersonType } from '~/types'
import api from 'lib/api'
import { loaders } from 'kea-loaders'

export const projectHomepageLogic = kea<projectHomepageLogicType>([
    path(['scenes', 'project-homepage', 'projectHomepageLogic']),
    connect({
        values: [teamLogic, ['currentTeamId', 'currentTeam']],
    }),

    selectors({
        primaryDashboardId: [() => [teamLogic.selectors.currentTeam], (currentTeam) => currentTeam?.primary_dashboard],
        dashboardLogicProps: [
            (s) => [s.primaryDashboardId],
            (primaryDashboardId): DashboardLogicProps => ({
                id: primaryDashboardId ?? undefined,
                placement: DashboardPlacement.ProjectHomepage,
            }),
        ],
    }),

    loaders(({ values }) => ({
        recentInsights: [
            [] as InsightModel[],
            {
                loadRecentInsights: async (_, breakpoint) => {
                    await breakpoint(100)
                    const response = await api.get(
                        `api/projects/${values.currentTeamId}/insights/?my_last_viewed=true&order=-my_last_viewed_at&basic=true`
                    )
                    return response.results
                },
            },
        ],
        persons: [
            [] as PersonType[],
            {
                loadPersons: async () => {
                    const response = await api.persons.list()
                    return response.results
                },
            },
        ],
    })),

    afterMount(({ actions }) => {
        actions.loadRecentInsights()
        actions.loadPersons()
    }),
])
