import { kea } from 'kea'
import { router } from 'kea-router'
import api from 'lib/api'
import { objectDiffShallow, objectsEqual, toParams } from 'lib/utils'
import { DashboardItemType, LayoutView, SavedInsightsTabs } from '~/types'
import { savedInsightsLogicType } from './savedInsightsLogicType'
import { prompt } from 'lib/logic/prompt'
import { toast } from 'react-toastify'
import { Dayjs } from 'dayjs'
import { dashboardItemsModel } from '~/models/dashboardItemsModel'
import { teamLogic } from '../teamLogic'
import { urls } from 'scenes/urls'
import { eventUsageLogic } from 'lib/utils/eventUsageLogic'

export interface InsightsResult {
    results: DashboardItemType[]
    count: number
    previous?: string
    next?: string
    /** not in the API response */
    filters?: SavedInsightFilters | null
}

export interface SavedInsightFilters {
    layoutView: LayoutView
    order: string
    tab: SavedInsightsTabs
    search: string
    insightType: string
    createdBy: number | 'All users'
    dateFrom?: string | Dayjs | undefined
    dateTo?: string | Dayjs | undefined
}

function cleanFilters(values: Partial<SavedInsightFilters>): SavedInsightFilters {
    return {
        layoutView: values.layoutView || LayoutView.List,
        order: values.order || '-updated_at',
        tab: values.tab || SavedInsightsTabs.All,
        search: String(values.search || ''),
        insightType: values.insightType || 'All types',
        createdBy: (values.tab !== SavedInsightsTabs.Yours && values.createdBy) || 'All users',
        dateFrom: values.dateFrom || 'all',
        dateTo: values.dateTo || undefined,
    }
}

export const savedInsightsLogic = kea<savedInsightsLogicType<InsightsResult, SavedInsightFilters>>({
    connect: {
        values: [teamLogic, ['currentTeamId']],
        logic: [eventUsageLogic],
    },
    actions: {
        setSavedInsightsFilters: (filters: Partial<SavedInsightFilters>, merge = true) => ({ filters, merge }),
        addGraph: (type: string) => ({ type }),

        renameInsight: (id: number) => ({ id }),
        duplicateInsight: (insight: DashboardItemType) => ({ insight }),
        loadInsights: true,
    },
    loaders: ({ values }) => ({
        insights: {
            __default: { results: [], count: 0, filters: null } as InsightsResult,
            loadInsights: async (_, breakpoint) => {
                if (values.insights.filters !== null) {
                    await breakpoint(300)
                }
                const { filters } = values
                const params = {
                    order: filters.order,
                    limit: 15,
                    saved: true,
                    ...(filters.tab === SavedInsightsTabs.Yours && { user: true }),
                    ...(filters.tab === SavedInsightsTabs.Favorites && { favorited: true }),
                    ...(filters.search && { search: filters.search }),
                    ...(filters.insightType?.toLowerCase() !== 'all types' && {
                        insight: filters.insightType?.toUpperCase(),
                    }),
                    ...(filters.createdBy !== 'All users' && { created_by: filters.createdBy }),
                    ...(filters.dateFrom &&
                        filters.dateFrom !== 'all' && {
                            date_from: filters.dateFrom,
                            date_to: filters.dateTo,
                        }),
                }
                const response = await api.get(
                    `api/projects/${teamLogic.values.currentTeamId}/insights/?${toParams(params)}`
                )

                if (filters.search && String(filters.search).match(/^[0-9]+$/)) {
                    try {
                        const insight = await api.get(
                            `api/projects/${teamLogic.values.currentTeamId}/insights/${filters.search}`
                        )
                        return {
                            ...response,
                            count: response.count + 1,
                            results: [insight, ...response.results],
                            filters,
                        }
                    } catch (e) {
                        // no insight with this ID found, discard
                    }
                }

                return { ...response, filters }
            },
            loadPaginatedInsights: async (url: string) => await api.get(url),
            updateFavoritedInsight: async ({ id, favorited }) => {
                const response = await api.update(`api/projects/${teamLogic.values.currentTeamId}/insights/${id}`, {
                    favorited,
                })
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
        rawFilters: [
            null as Partial<SavedInsightFilters> | null,
            {
                setSavedInsightsFilters: (state, { filters, merge }) =>
                    cleanFilters(
                        merge
                            ? {
                                  ...(state || {}),
                                  ...filters,
                              }
                            : filters
                    ),
            },
        ],
    },
    selectors: {
        filters: [(s) => [s.rawFilters], (rawFilters): SavedInsightFilters => cleanFilters(rawFilters || {})],
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
        usingFilters: [
            (s) => [s.filters],
            (filters) => !objectsEqual(cleanFilters({ ...filters, tab: SavedInsightsTabs.All }), cleanFilters({})),
        ],
    },
    listeners: ({ actions, values, selectors }) => ({
        addGraph: ({ type }) => {
            router.actions.push(
                `/insights?insight=${encodeURIComponent(String(type).toUpperCase())}&backToURL=${encodeURIComponent(
                    urls.savedInsights()
                )}`
            )
        },
        setSavedInsightsFilters: async ({ merge }, breakpoint, __, previousState) => {
            const oldFilters = selectors.filters(previousState)
            const firstLoad = selectors.rawFilters(previousState) === null
            const { filters } = values // not taking from props because sometimes we merge them

            if (!firstLoad && typeof filters.search !== 'undefined' && filters.search !== oldFilters.search) {
                await breakpoint(300)
            }
            if (firstLoad || !objectsEqual(oldFilters, filters)) {
                actions.loadInsights()
            }

            // Filters from clicks come with "merge: true",
            // Filters from the URL come with "merge: false" and override everything
            if (merge) {
                let keys = Object.keys(objectDiffShallow(oldFilters, filters))
                if (keys.includes('tab')) {
                    keys = keys.filter((k) => k !== 'tab')
                    eventUsageLogic.actions.reportSavedInsightTabChanged(filters.tab)
                }
                if (keys.includes('layoutView')) {
                    keys = keys.filter((k) => k !== 'layoutView')
                    eventUsageLogic.actions.reportSavedInsightLayoutChanged(filters.layoutView)
                }
                if (keys.length > 0) {
                    eventUsageLogic.actions.reportSavedInsightFilterUsed(keys)
                }
            }
        },
        renameInsight: async ({ id }) => {
            prompt({ key: `rename-insight-${id}` }).actions.prompt({
                title: 'Rename panel',
                placeholder: 'Please enter the new name',
                value: name,
                error: 'You must enter name',
                success: async (name: string) => {
                    const insight = await api.update(`api/projects/${teamLogic.values.currentTeamId}/insights/${id}`, {
                        name,
                    })
                    toast('Successfully renamed item')
                    actions.setInsight(insight)
                },
            })
        },
        duplicateInsight: async ({ insight }) => {
            await api.create(`api/projects/${values.currentTeamId}/insights`, insight)
            actions.loadInsights()
        },
        setDates: () => {
            actions.loadInsights()
        },
        [dashboardItemsModel.actionTypes.renameDashboardItemSuccess]: ({ item }) => {
            actions.setInsight(item)
        },
    }),
    actionToUrl: ({ values }) => {
        const changeUrl = (): [string, Record<string, any>, Record<string, any>, { replace: true }] | void => {
            const nextValues = cleanFilters(values.filters)
            const urlValues = cleanFilters(router.values.searchParams)
            if (!objectsEqual(nextValues, urlValues)) {
                return ['/saved_insights', objectDiffShallow(cleanFilters({}), nextValues), {}, { replace: true }]
            }
        }
        return {
            loadInsights: changeUrl,
            setLayoutView: changeUrl,
        }
    },
    urlToAction: ({ actions, values }) => ({
        '/saved_insights': (_, searchParams) => {
            const currentFilters = cleanFilters(values.filters)
            const nextFilters = cleanFilters(searchParams)
            if (values.rawFilters === null || !objectsEqual(currentFilters, nextFilters)) {
                actions.setSavedInsightsFilters(nextFilters, false)
            }
        },
    }),
})
