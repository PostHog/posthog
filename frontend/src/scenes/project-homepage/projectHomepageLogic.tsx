import { connect, kea, path, selectors } from 'kea'
import { loaders } from 'kea-loaders'
import api from 'lib/api'
import { dashboardLogic, DashboardLogicProps } from 'scenes/dashboard/dashboardLogic'
import { MaxContextInput, createMaxContextHelpers } from 'scenes/max/maxTypes'
import { projectLogic } from 'scenes/projectLogic'
import { teamLogic } from 'scenes/teamLogic'

import { getQueryBasedInsightModel } from '~/queries/nodes/InsightViz/utils'
import { DashboardPlacement, DashboardType, InsightModel, QueryBasedInsightModel } from '~/types'

import type { projectHomepageLogicType } from './projectHomepageLogicType'

export const projectHomepageLogic = kea<projectHomepageLogicType>([
    path(['scenes', 'project-homepage', 'projectHomepageLogic']),
    connect(() => ({
        values: [teamLogic, ['currentTeam'], projectLogic, ['currentProjectId']],
    })),

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
        maxContext: [
            (s) => [
                (state) => {
                    // Get the dashboard from the mounted dashboardLogic
                    const dashboardLogicProps = s.dashboardLogicProps(state)
                    if (!dashboardLogicProps) {
                        return null
                    }
                    const logic = dashboardLogic.findMounted(dashboardLogicProps)
                    if (!logic) {
                        return null
                    }
                    return logic.selectors.dashboard(state)
                },
            ],
            (dashboard: DashboardType<QueryBasedInsightModel> | null): MaxContextInput[] => {
                if (!dashboard) {
                    return []
                }
                return [createMaxContextHelpers.dashboard(dashboard)]
            },
        ],
    }),

    loaders(({ values }) => ({
        recentInsights: [
            [] as QueryBasedInsightModel[],
            {
                loadRecentInsights: async () => {
                    const insights = await api.get<InsightModel[]>(
                        `api/environments/${values.currentProjectId}/insights/my_last_viewed`
                    )
                    return insights.map((legacyInsight) => getQueryBasedInsightModel(legacyInsight))
                },
            },
        ],
    })),
])
