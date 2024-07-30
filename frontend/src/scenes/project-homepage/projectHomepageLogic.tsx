import { afterMount, connect, kea, path, selectors } from 'kea'
import { loaders } from 'kea-loaders'
import api from 'lib/api'
import { DashboardLogicProps } from 'scenes/dashboard/dashboardLogic'
import { teamLogic } from 'scenes/teamLogic'

import { DashboardPlacement, InsightModel, PersonType, QueryBasedInsightModel } from '~/types'

import type { projectHomepageLogicType } from './projectHomepageLogicType'

export const projectHomepageLogic = kea<projectHomepageLogicType>([
    path(['scenes', 'project-homepage', 'projectHomepageLogic']),
    connect({
        values: [teamLogic, ['currentTeamId', 'currentTeam']],
    }),

    selectors({
        primaryDashboardId: [() => [teamLogic.selectors.currentTeam], (currentTeam) => currentTeam?.primary_dashboard],
        dashboardLogicProps: [
            (s) => [s.primaryDashboardId],
            (primaryDashboardId): DashboardLogicProps | null =>
                primaryDashboardId
                    ? {
                          id: primaryDashboardId,
                          placement: DashboardPlacement.ProjectHomepage,
                      }
                    : null,
        ],
    }),

    loaders(({ values }) => ({
        recentInsights: [
            [] as QueryBasedInsightModel[],
            {
                loadRecentInsights: async () => {
                    return await api.get(`api/projects/${values.currentTeamId}/insights/my_last_viewed`)
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
        actions.loadPersons()
    }),
])
