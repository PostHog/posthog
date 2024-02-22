import { actions, connect, kea, listeners, path, reducers, selectors } from 'kea'
import { loaders } from 'kea-loaders'
import { actionToUrl, router, urlToAction } from 'kea-router'
import api from 'lib/api'
import { dayjs } from 'lib/dayjs'
import { Sorting } from 'lib/lemon-ui/LemonTable'
import { lemonToast } from 'lib/lemon-ui/LemonToast/LemonToast'
import { PaginationManual } from 'lib/lemon-ui/PaginationControl'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { objectDiffShallow, objectsEqual, toParams } from 'lib/utils'
import { eventUsageLogic } from 'lib/utils/eventUsageLogic'
import { deleteDashboardLogic } from 'scenes/dashboard/deleteDashboardLogic'
import { duplicateDashboardLogic } from 'scenes/dashboard/duplicateDashboardLogic'
import { urls } from 'scenes/urls'

import { dashboardsModel } from '~/models/dashboardsModel'
import { insightsModel } from '~/models/insightsModel'
import { InsightModel, LayoutView, SavedInsightsTabs } from '~/types'

import { teamLogic } from '../teamLogic'
import type { savedInsightsLogicType } from './savedInsightsLogicType'

export const INSIGHTS_PER_PAGE = 30

export interface InsightsResult {
    results: InsightModel[]
    count: number
    previous?: string
    next?: string
    /* not in the API response */
    filters?: SavedInsightFilters | null
    /* not in the API response */
    offset: number
}

export interface SavedInsightFilters {
    layoutView: LayoutView
    order: string
    tab: SavedInsightsTabs
    search: string
    insightType: string
    createdBy: number | 'All users'
    dateFrom: string | dayjs.Dayjs | undefined | null
    dateTo: string | dayjs.Dayjs | undefined | null
    page: number
    dashboardId: number | undefined | null
}

function cleanFilters(values: Partial<SavedInsightFilters>): SavedInsightFilters {
    return {
        layoutView: values.layoutView || LayoutView.List,
        order: values.order || '-last_modified_at', // Sync with `sorting` selector
        tab: values.tab || SavedInsightsTabs.All,
        search: String(values.search || ''),
        insightType: values.insightType || 'All types',
        createdBy: (values.tab !== SavedInsightsTabs.Yours && values.createdBy) || 'All users',
        dateFrom: values.dateFrom || 'all',
        dateTo: values.dateTo || undefined,
        page: parseInt(String(values.page)) || 1,
        dashboardId: values.dashboardId,
    }
}

export const savedInsightsLogic = kea<savedInsightsLogicType>([
    path(['scenes', 'saved-insights', 'savedInsightsLogic']),
    connect({
        values: [teamLogic, ['currentTeamId'], featureFlagLogic, ['featureFlags']],
        logic: [eventUsageLogic],
    }),
    actions({
        setSavedInsightsFilters: (
            filters: Partial<SavedInsightFilters>,
            merge: boolean = true,
            debounce: boolean = true
        ) => ({ filters, merge, debounce }),
        updateFavoritedInsight: (insight: InsightModel, favorited: boolean) => ({ insight, favorited }),
        renameInsight: (insight: InsightModel) => ({ insight }),
        duplicateInsight: (insight: InsightModel, redirectToInsight = false) => ({
            insight,
            redirectToInsight,
        }),
        loadInsights: (debounce: boolean = true) => ({ debounce }),
        setInsight: (insight: InsightModel) => ({ insight }),
        addInsight: (insight: InsightModel) => ({ insight }),
    }),
    loaders(({ values }) => ({
        insights: {
            __default: { results: [], count: 0, filters: null, offset: 0 } as InsightsResult,
            loadInsights: async ({ debounce }, breakpoint) => {
                if (debounce && values.insights.filters !== null) {
                    await breakpoint(300)
                }
                const { filters } = values

                const params = {
                    ...values.paramsFromFilters,
                    basic: true,
                    include_query_insights: true,
                }

                const response = await api.get(
                    `api/projects/${teamLogic.values.currentTeamId}/insights/?${toParams(params)}`
                )

                if (filters.search && String(filters.search).match(/^[0-9]+$/)) {
                    try {
                        const insight: InsightModel = await api.get(
                            `api/projects/${teamLogic.values.currentTeamId}/insights/${filters.search}/?include_query_insights=true`
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
                if (
                    router.values.location.pathname === urls.savedInsights() &&
                    router.values.lastMethod !== 'POP' &&
                    values.insights.filters?.page !== filters.page
                ) {
                    window.scrollTo(0, 0)
                }

                return { ...response, filters, offset: params.offset }
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
            setInsight: (insight: InsightModel) => {
                const results = values.insights.results.map((i) => (i.short_id === insight.short_id ? insight : i))
                return { ...values.insights, results }
            },
        },
    })),
    reducers({
        rawFilters: [
            null as Partial<SavedInsightFilters> | null,
            {
                setSavedInsightsFilters: (state, { filters, merge }) =>
                    cleanFilters({
                        ...(merge ? state || {} : {}),
                        ...filters,
                        // Reset page on filter change EXCEPT if it's page or view that's being updated
                        ...('page' in filters || 'layoutView' in filters ? {} : { page: 1 }),
                    }),
            },
        ],
    }),
    selectors(({ actions }) => ({
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
                    // Sync with `cleanFilters` function
                    return {
                        columnKey: 'last_modified_at',
                        order: -1,
                    }
                }
                return filters.order.startsWith('-')
                    ? {
                          columnKey: filters.order.slice(1),
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
                ...(!!filters.dashboardId && {
                    dashboards: [filters.dashboardId],
                }),
            }),
        ],
        pagination: [
            (s) => [s.filters, s.count],
            (filters, count): PaginationManual => {
                return {
                    controlled: true,
                    pageSize: INSIGHTS_PER_PAGE,
                    currentPage: filters.page,
                    entryCount: count,
                    onBackward: () =>
                        actions.setSavedInsightsFilters({
                            page: filters.page - 1,
                        }),
                    onForward: () =>
                        actions.setSavedInsightsFilters({
                            page: filters.page + 1,
                        }),
                }
            },
        ],
    })),
    listeners(({ actions, asyncActions, values, selectors }) => ({
        setSavedInsightsFilters: async ({ merge, debounce }, breakpoint, __, previousState) => {
            const oldFilters = selectors.filters(previousState)
            const firstLoad = selectors.rawFilters(previousState) === null
            const { filters } = values // not taking from props because sometimes we merge them

            if (
                debounce &&
                !firstLoad &&
                typeof filters.search !== 'undefined' &&
                filters.search !== oldFilters.search
            ) {
                await breakpoint(300)
            }
            if (firstLoad || !objectsEqual(oldFilters, filters)) {
                await asyncActions.loadInsights(debounce)
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
            insightsModel.actions.renameInsight(insight)
        },
        duplicateInsight: async ({ insight, redirectToInsight }) => {
            const newInsight = await api.create(`api/projects/${values.currentTeamId}/insights`, {
                ...insight,
                name: insight.name ? `${insight.name} (copy)` : insight.name,
            })
            actions.loadInsights()
            redirectToInsight && router.actions.push(urls.insightEdit(newInsight.short_id))
        },
        setDates: () => {
            actions.loadInsights()
        },
        [insightsModel.actionTypes.renameInsightSuccess]: ({ item }) => {
            actions.setInsight(item)
        },
        [dashboardsModel.actionTypes.updateDashboardInsight]: () => actions.loadInsights(),
        [deleteDashboardLogic.actionTypes.submitDeleteDashboardSuccess]: ({ deleteDashboard }) => {
            if (deleteDashboard.deleteInsights) {
                actions.loadInsights()
            }
        },
        [duplicateDashboardLogic.actionTypes.submitDuplicateDashboardSuccess]: ({ duplicateDashboard }) => {
            if (duplicateDashboard.duplicateTiles) {
                actions.loadInsights()
            }
        },
    })),
    actionToUrl(({ values }) => {
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
            if (router.values.location.pathname === urls.savedInsights()) {
                const nextValues = cleanFilters(values.filters)
                const urlValues = cleanFilters(router.values.searchParams)
                if (!objectsEqual(nextValues, urlValues)) {
                    return [
                        urls.savedInsights(),
                        objectDiffShallow(cleanFilters({}), nextValues),
                        {},
                        { replace: false },
                    ]
                }
            }
        }
        return {
            loadInsights: changeUrl,
            setLayoutView: changeUrl,
        }
    }),
    urlToAction(({ actions, values }) => ({
        [urls.savedInsights()]: async (_, searchParams, hashParams) => {
            if (hashParams.fromItem && String(hashParams.fromItem).match(/^[0-9]+$/)) {
                // `fromItem` for legacy /insights url redirect support
                const insightNumericId = parseInt(hashParams.fromItem)
                try {
                    const { short_id }: InsightModel = await api.get(
                        `api/projects/${teamLogic.values.currentTeamId}/insights/${insightNumericId}`
                    )
                    if (!short_id) {
                        throw new Error('Could not find short_id')
                    }
                    router.actions.replace(hashParams.edit ? urls.insightEdit(short_id) : urls.insightView(short_id))
                } catch (e) {
                    lemonToast.error(`Insight ID ${insightNumericId} couldn't be retrieved`)
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
    })),
])
