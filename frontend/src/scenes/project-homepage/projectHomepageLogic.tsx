import { afterMount, connect, kea, path, selectors } from 'kea'

import type { projectHomepageLogicType } from './projectHomepageLogicType'
import { teamLogic } from 'scenes/teamLogic'
import { DashboardLogicProps } from 'scenes/dashboard/dashboardLogic'
import { DashboardPlacement, InsightModel, PersonType } from '~/types'
import api from 'lib/api'
import { loaders } from 'kea-loaders'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { FEATURE_FLAGS } from 'lib/constants'

export const projectHomepageLogic = kea<projectHomepageLogicType>([
    path(['scenes', 'project-homepage', 'projectHomepageLogic']),
    connect({
        values: [teamLogic, ['currentTeamId', 'currentTeam'], featureFlagLogic, ['featureFlags']],
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
        allowQueryInsights: [(s) => [s.featureFlags], (featureFlags) => !!featureFlags[FEATURE_FLAGS.HOGQL]],
    }),

    loaders(({ values }) => ({
        recentInsights: [
            [] as InsightModel[],
            {
                loadRecentInsights: async () => {
                    return await api.get(
                        `api/projects/${values.currentTeamId}/insights/my_last_viewed?include_query_insights=${values.allowQueryInsights}`
                    )
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
