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
                        `api/projects/${values.currentTeamId}/insights/?recently_viewed=true`
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
