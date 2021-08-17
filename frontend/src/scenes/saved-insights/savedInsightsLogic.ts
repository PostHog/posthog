import { kea } from 'kea'
import api from 'lib/api'
import { toParams } from 'lib/utils'
import { DashboardItemType, SavedInsightsTabs, InsightType, UserBasicType } from '~/types'
import { savedInsightsLogicType } from './savedInsightsLogicType'

interface InsightsResult {
    results: DashboardItemType[]
    count: number
    previous?: string
    next?: string
}

export const savedInsightsLogic = kea<savedInsightsLogicType<InsightsResult>>({
    loaders: ({ values }) => ({
        insights: {
            __default: { results: [], count: 0 } as InsightsResult,
            loadInsights: async () => {
                const response = await api.get(
                    'api/insight/?' +
                        toParams({
                            order: '-created_at',
                            limit: 15,
                            saved: true,
                            ...(values.tab === SavedInsightsTabs.Yours && { user: true }),
                            ...(values.tab === SavedInsightsTabs.Favorites && { favorited: true }),
                            ...(values.searchTerm && { search: values.searchTerm }),
                            ...(values.insightType !== 'All types' && { insight: values.insightType }),
                            ...(values.createdBy !== 'All users' && { created_by: values.createdBy?.id }),
                        })
                )
                return response
            },
            loadPaginatedInsights: async (url: string) => await api.get(url),
            updateFavoritedInsight: async ({ id, favorited }) => {
                const response = await api.update(`api/insight/${id}`, { favorited })
                const updatedInsights = values.insights.results.map((insight) =>
                    insight.id === id ? response : insight
                )
                return { ...values.insights, results: updatedInsights }
            },
        },
        layoutView: [
            'list',
            {
                setLayoutView: (view: string) => view,
            },
        ],
        tab: [
            SavedInsightsTabs.All,
            {
                setTab: (tab: string) => {
                    console.log('tab!', tab)
                    return tab
                },
            },
        ],
        searchTerm: [
            '',
            {
                setSearchTerm: (term: string) => term,
            },
        ],
        insightType: [
            'All types',
            {
                setInsightType: (type: InsightType | 'All types') => type.toUpperCase(),
            },
        ],
        createdBy: [
            null as Partial<UserBasicType> | null | 'All users',
            {
                setCreatedBy: (user: Partial<UserBasicType> | 'All users') => user,
            },
        ],
    }),
    selectors: {
        nextResult: [(s) => [s.insights], (insights) => insights.next],
        previousResult: [(s) => [s.insights], (insights) => insights.previous],
        count: [(s) => [s.insights], (insights) => insights.count],
        offset: [
            (s) => [s.insights],
            (insights) => {
                const offset = new URLSearchParams(insights.next).get('offset') || '0'
                return parseInt(offset)
            },
        ],
    },
    listeners: ({ actions }) => ({
        setTab: () => {
            actions.loadInsights()
        },
        setSearchTerm: (term) => {
            if (term === '') {
                actions.loadInsights()
            }
        },
        setInsightType: () => {
            actions.loadInsights()
        },
        setCreatedBy: () => {
            actions.loadInsights()
        },
    }),
    events: ({ actions }) => ({
        afterMount: () => {
            actions.loadInsights()
        },
    }),
})
