import { kea } from 'kea'
import { DashboardItemType, InsightShortId } from '~/types'
import api from 'lib/api'
import { teamLogic } from 'scenes/teamLogic'
import { eventUsageLogic } from 'lib/utils/eventUsageLogic'
import { combineUrl, router } from 'kea-router'
import { insightRouterLogicType } from './insightRouterLogicType'
import { urls } from 'scenes/urls'

export const insightRouterLogic = kea<insightRouterLogicType>({
    path: ['scenes', 'insights', 'insightRouterLogic'],
    actions: {
        loadInsight: (id: InsightShortId) => ({ id }),
        setError: true,
    },
    reducers: {
        error: [
            false,
            {
                setError: () => true,
            },
        ],
    },
    listeners: ({ actions }) => ({
        loadInsight: async ({ id }) => {
            const response = await api.get(`api/projects/${teamLogic.values.currentTeamId}/insights/?short_id=${id}`)
            if (response.results.length) {
                const item = response.results[0] as DashboardItemType
                eventUsageLogic.actions.reportInsightShortUrlVisited(true, item.filters.insight || null)
                router.actions.replace(
                    combineUrl(urls.insightView(item.short_id, item.filters), undefined, {
                        fromItemName: item.name,
                        fromDashboard: item.dashboard,
                        id: item.short_id,
                    }).url
                )
            } else {
                eventUsageLogic.actions.reportInsightShortUrlVisited(false, null)
                actions.setError()
            }
        },
    }),
    urlToAction: ({ actions }) => ({
        [urls.insightRouter(':shortId')]: ({ shortId }) => {
            if (shortId) {
                actions.loadInsight(shortId as InsightShortId)
            }
        },
    }),
})
