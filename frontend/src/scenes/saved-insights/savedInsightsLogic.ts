import { kea } from 'kea'
import { router } from 'kea-router'
import api from 'lib/api'
import { toParams } from 'lib/utils'
import { DashboardItemType, LayoutView, SavedInsightsTabs, UserBasicType } from '~/types'
import { savedInsightsLogicType } from './savedInsightsLogicType'
import { prompt } from 'lib/logic/prompt'
import { toast } from 'react-toastify'
import { Dayjs } from 'dayjs'
import { dashboardItemsModel } from '~/models/dashboardItemsModel'

interface InsightsResult {
    results: DashboardItemType[]
    count: number
    previous?: string
    next?: string
}

export const savedInsightsLogic = kea<savedInsightsLogicType<InsightsResult>>({
    actions: {
        addGraph: (type: string) => ({ type }),
        setInsightType: (type: string) => ({ type }),
        setCreatedBy: (user: Partial<UserBasicType> | 'All users') => ({ user }),
        setLayoutView: (view: string) => ({ view }),
        setTab: (tab: string) => ({ tab }),
        setDates: (dateFrom: string | Dayjs | undefined, dateTo: string | Dayjs | undefined) => ({
            dateFrom,
            dateTo,
        }),
        setSearchTerm: (term: string) => ({ term }),
        renameInsight: (id: number) => ({ id }),
        duplicateInsight: (insight: DashboardItemType) => ({ insight }),
        addToDashboard: (item: DashboardItemType, dashboardId: number) => ({ item, dashboardId }),
        orderByUpdatedAt: true,
        orderByCreator: true,
    },
    loaders: ({ values }) => ({
        insights: {
            __default: { results: [], count: 0 } as InsightsResult,
            loadInsights: async () => {
                const response = await api.get(
                    'api/insight/?' +
                        toParams({
                            order: values.order,
                            limit: 15,
                            saved: true,
                            ...(values.tab === SavedInsightsTabs.Yours && { user: true }),
                            ...(values.tab === SavedInsightsTabs.Favorites && { favorited: true }),
                            ...(values.searchTerm && { search: values.searchTerm }),
                            ...(values.insightType.toLowerCase() !== 'all types' && { insight: values.insightType }),
                            ...(values.createdBy !== 'All users' && { created_by: values.createdBy?.id }),
                            ...(values.dates.dateFrom && {
                                date_from: values.dates.dateFrom,
                                date_to: values.dates.dateTo,
                            }),
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
            setInsight: (insight: DashboardItemType) => {
                const results = values.insights.results.map((i) => (i.id === insight.id ? insight : i))
                return { ...values.insights, results }
            },
        },
    }),
    reducers: {
        layoutView: [
            LayoutView.List,
            {
                setLayoutView: (_, { view }) => view,
            },
        ],
        order: [
            '-updated_at',
            {
                orderByUpdatedAt: (state) => (state === '-updated_at' ? 'updated_at' : '-updated_at'),
                orderByCreator: (state) => (state === 'created_by' ? '-created_by' : 'created_by'),
            },
        ],
        tab: [
            SavedInsightsTabs.All,
            {
                setTab: (_, { tab }) => tab,
            },
        ],
        searchTerm: [
            '' as string,
            {
                setSearchTerm: (_, { term }) => term,
            },
        ],
        insightType: [
            'All types',
            {
                setInsightType: (_, { type }) => type.toUpperCase(),
            },
        ],
        createdBy: [
            null as Partial<UserBasicType> | null | 'All users',
            {
                setCreatedBy: (_, { user }) => user,
            },
        ],
        dates: [
            {
                dateFrom: undefined as string | Dayjs | undefined,
                dateTo: undefined as string | Dayjs | undefined,
            },
            {
                setDates: (_, dates) => dates,
            },
        ],
    },
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
        addGraph: ({ type }) => {
            router.actions.push(`/insights?insight=${type.toString().toUpperCase()}&backToURL=/saved_insights`)
        },
        setTab: () => {
            actions.loadInsights()
        },
        setSearchTerm: ({ term }) => {
            if (term.length === 0) {
                actions.loadInsights()
            }
        },
        setInsightType: () => {
            actions.loadInsights()
        },
        setCreatedBy: () => {
            actions.loadInsights()
        },
        orderByUpdatedAt: () => {
            actions.loadInsights()
        },
        orderByCreator: () => {
            actions.loadInsights()
        },
        renameInsight: async ({ id }) => {
            prompt({ key: `rename-insight-${id}` }).actions.prompt({
                title: 'Rename panel',
                placeholder: 'Please enter the new name',
                value: name,
                error: 'You must enter name',
                success: async (name: string) => {
                    const insight = await api.update(`api/insight/${id}`, { name })
                    toast('Successfully renamed item')
                    actions.setInsight(insight)
                },
            })
        },
        duplicateInsight: async ({ insight }) => {
            await api.create('api/insight', insight)
            actions.loadInsights()
        },
        setDates: () => {
            actions.loadInsights()
        },
        [dashboardItemsModel.actionTypes.renameDashboardItemSuccess]: ({ item }) => {
            actions.setInsight(item)
        },
    }),
    events: ({ actions }) => ({
        afterMount: () => {
            actions.loadInsights()
        },
    }),
})
