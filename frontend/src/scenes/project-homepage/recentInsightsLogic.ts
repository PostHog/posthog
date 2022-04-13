import { kea } from 'kea'

import { teamLogic } from 'scenes/teamLogic'
import { InsightModel } from '~/types'
import api from 'lib/api'

import type { recentInsightsLogicType } from './recentInsightsLogicType'
export const recentInsightsLogic = kea<recentInsightsLogicType>({
    path: ['scenes', 'project-homepage', 'recentInsightsLogic'],
    connect: {
        values: [teamLogic, ['currentTeamId']],
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

    events: ({ actions }) => ({
        afterMount: () => {
            actions.loadRecentInsights()
        },
    }),
})
