import { kea } from 'kea'
import { DashboardItemType } from '~/types'
import api from 'lib/api'
import { teamLogic } from 'scenes/teamLogic'
import { eventUsageLogic } from 'lib/utils/eventUsageLogic'
import { combineUrl, router } from 'kea-router'
import { cleanFilters } from 'scenes/insights/utils/cleanFilters'
import { insightRouterLogicType } from './insightRouterLogicType'

export const insightRouterLogic = kea<insightRouterLogicType>({
    path: ['scenes', 'insights', 'insightRouterLogic'],
    actions: {
        loadInsight: (id: string) => ({ id }),
        setError: true,
        createInsight: (insight: Partial<DashboardItemType>) => ({ insight }),
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
                    combineUrl('/insights', item.filters, {
                        fromItem: item.id,
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
        createInsight: async ({ insight }, breakpoint) => {
            const newInsight = { name: '', description: '', tags: [], filters: {}, result: null, ...insight }
            const createdInsight = await api.create(
                `api/projects/${teamLogic.values.currentTeamId}/insights`,
                newInsight
            )
            breakpoint()
            router.actions.replace('/insights', createdInsight.filters, {
                ...router.values.hashParams,
                edit: true,
                fromItem: createdInsight.id,
            })
        },
    }),
    urlToAction: ({ actions }) => ({
        '/i/:id': ({ id }) => {
            if (id) {
                actions.loadInsight(id)
            }
        },
        '/insights/new': (_, searchParams) => {
            actions.createInsight({ filters: cleanFilters(searchParams) })
        },
    }),
})
