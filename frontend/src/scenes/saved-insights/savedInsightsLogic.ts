import { kea } from 'kea'
import { router } from 'kea-router'
import api from 'lib/api'
import { errorToast, objectDiffShallow, objectsEqual, toParams } from 'lib/utils'
import { DashboardItemType, LayoutView, SavedInsightsTabs } from '~/types'
import { savedInsightsLogicType } from './savedInsightsLogicType'
import { Dayjs } from 'dayjs'
import { dashboardItemsModel } from '~/models/dashboardItemsModel'
import { teamLogic } from '../teamLogic'
import { eventUsageLogic } from 'lib/utils/eventUsageLogic'
import { Sorting } from 'lib/components/LemonTable'
import { urls } from 'scenes/urls'

export const INSIGHTS_PER_PAGE = 15

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
    dateFrom: string | Dayjs | undefined | 'all'
    dateTo: string | Dayjs | undefined
    page: number
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
        page: parseInt(String(values.page)) || 1,
    }
}

export const savedInsightsLogic = kea<savedInsightsLogicType<InsightsResult, SavedInsightFilters>>({
    path: ['scenes', 'saved-insights', 'savedInsightsLogic'],
    connect: {
        values: [teamLogic, ['currentTeamId']],
        logic: [eventUsageLogic],
    },
    actions: {
        setSavedInsightsFilters: (filters: Partial<SavedInsightFilters>, merge = true) => ({ filters, merge }),
        addGraph: (type: string) => ({ type }),
        updateFavoritedInsight: (insight: DashboardItemType, favorited: boolean) => ({ insight, favorited }),
        renameInsight: (insight: DashboardItemType) => ({ insight }),
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
                const params = values.paramsFromFilters
                const response = await api.get(
                    `api/projects/${teamLogic.values.currentTeamId}/insights/?${toParams(params)}`
                )

                if (filters.search && String(filters.search).match(/^[0-9]+$/)) {
                    try {
                        const insight: DashboardItemType = await api.get(
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

                // scroll to top if the page changed, except if changed via back/forward
                if (router.values.lastMethod !== 'POP' && values.insights.filters?.page !== filters.page) {
                    window.scrollTo(0, 0)
                }

                return { ...response, filters }
            },
            updateFavoritedInsight: async ({ insight, favorited }) => {
                const response = await api.update(
                    `api/projects/${teamLogic.values.currentTeamId}/insights/${insight.id}`,
                    {
                        favorited,
                    }
                )
                const updatedInsights = values.insights.results.map((i) =>
                    i.short_id === insight.short_id ? response : i
                )
                return { ...values.insights, results: updatedInsights }
            },
            setInsight: (insight: DashboardItemType) => {
                const results = values.insights.results.map((i) => (i.short_id === insight.short_id ? insight : i))
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
        count: [(s) => [s.insights], (insights) => insights.count],
        usingFilters: [
            (s) => [s.filters],
            (filters) => !objectsEqual(cleanFilters({ ...filters, tab: SavedInsightsTabs.All }), cleanFilters({})),
        ],
        sorting: [
            (s) => [s.filters],
            (filters): Sorting | null => {
                if (!filters.order) {
                    return null
                }
                return filters.order.startsWith('-')
                    ? {
                          columnKey: filters.order.substr(1),
                          order: -1,
                      }
                    : {
                          columnKey: filters.order,
                          order: 1,
                      }
            },
        ],
        paramsFromFilters: [
            (s) => [s.filters],
            (filters) => ({
                order: filters.order,
                limit: INSIGHTS_PER_PAGE,
                offset: Math.max(0, (filters.page - 1) * INSIGHTS_PER_PAGE),
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
            }),
        ],
    },
    listeners: ({ actions, values, selectors }) => ({
        addGraph: ({ type }) => {
            router.actions.push(`/insights?insight=${encodeURIComponent(String(type).toUpperCase())}`)
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
        renameInsight: async ({ insight }) => {
            dashboardItemsModel.actions.renameDashboardItem(insight)
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
        const changeUrl = ():
            | [
                  string,
                  Record<string, any>,
                  Record<string, any>,
                  {
                      replace: boolean
                  }
              ]
            | void => {
            const nextValues = cleanFilters(values.filters)
            const urlValues = cleanFilters(router.values.searchParams)
            if (!objectsEqual(nextValues, urlValues)) {
                return [urls.savedInsights(), objectDiffShallow(cleanFilters({}), nextValues), {}, { replace: false }]
            }
        }
        return {
            loadInsights: changeUrl,
            setLayoutView: changeUrl,
        }
    },
    urlToAction: ({ actions, values }) => ({
        [urls.savedInsights()]: async (_, searchParams, hashParams) => {
            if (hashParams.fromItem && String(hashParams.fromItem).match(/^[0-9]+$/)) {
                // `fromItem` for legacy /insights url redirect support
                const insightId = parseInt(hashParams.fromItem)
                try {
                    const { short_id }: DashboardItemType = await api.get(
                        `api/projects/${teamLogic.values.currentTeamId}/insights/${insightId}`
                    )
                    if (!short_id) {
                        throw new Error('Could not find short_id')
                    }
                    router.actions.replace(
                        hashParams.edit
                            ? urls.insightEdit(short_id, searchParams)
                            : urls.insightView(short_id, searchParams)
                    )
                } catch (e) {
                    errorToast(
                        'Could not find insight',
                        `The insight with the id "${insightId}" could not be retrieved.`,
                        ' ' // adding a " " removes "Unknown Exception" from the toast
                    )
                    router.actions.push(urls.savedInsights())
                }
                return
            } else if (searchParams.insight) {
                // old URL with `?insight=TRENDS` in query
                router.actions.replace(urls.insightNew(searchParams))
                return
            }

            const currentFilters = cleanFilters(values.filters)
            const nextFilters = cleanFilters(searchParams)
            if (values.rawFilters === null || !objectsEqual(currentFilters, nextFilters)) {
                actions.setSavedInsightsFilters(nextFilters, false)
            }
        },
    }),
})
