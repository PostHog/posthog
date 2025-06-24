import { actions, connect, kea, listeners, path, reducers, selectors } from 'kea'
import { loaders } from 'kea-loaders'
import { actionToUrl, router, urlToAction } from 'kea-router'
import api, { CountedPaginatedResponse } from 'lib/api'
import { AlertType } from 'lib/components/Alerts/types'
import { dayjs } from 'lib/dayjs'
import { Sorting } from 'lib/lemon-ui/LemonTable'
import { lemonToast } from 'lib/lemon-ui/LemonToast/LemonToast'
import { PaginationManual } from 'lib/lemon-ui/PaginationControl'
import { objectDiffShallow, objectsEqual, toParams } from 'lib/utils'
import { eventUsageLogic } from 'lib/utils/eventUsageLogic'
import { deleteDashboardLogic } from 'scenes/dashboard/deleteDashboardLogic'
import { duplicateDashboardLogic } from 'scenes/dashboard/duplicateDashboardLogic'
import { insightsApi } from 'scenes/insights/utils/api'
import { sceneLogic } from 'scenes/sceneLogic'
import { Scene } from 'scenes/sceneTypes'
import { urls } from 'scenes/urls'

import { SIDE_PANEL_CONTEXT_KEY, SidePanelSceneContext } from '~/layout/navigation-3000/sidepanel/types'
import { dashboardsModel } from '~/models/dashboardsModel'
import { insightsModel } from '~/models/insightsModel'
import { getQueryBasedInsightModel } from '~/queries/nodes/InsightViz/utils'
import { InsightModel, LayoutView, QueryBasedInsightModel, SavedInsightsTabs } from '~/types'

import { teamLogic } from '../teamLogic'
import type { savedInsightsLogicType } from './savedInsightsLogicType'

export const INSIGHTS_PER_PAGE = 30

export interface InsightsResult extends CountedPaginatedResponse<QueryBasedInsightModel> {
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

export function cleanFilters(values: Partial<SavedInsightFilters>): SavedInsightFilters {
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
    connect(() => ({
        values: [teamLogic, ['currentTeamId'], sceneLogic, ['activeScene']],
        logic: [eventUsageLogic],
    })),
    actions({
        setSavedInsightsFilters: (
            filters: Partial<SavedInsightFilters>,
            merge: boolean = true,
            debounce: boolean = true
        ) => ({ filters, merge, debounce }),
        updateFavoritedInsight: (insight: QueryBasedInsightModel, favorited: boolean) => ({ insight, favorited }),
        renameInsight: (insight: QueryBasedInsightModel) => ({ insight }),
        duplicateInsight: (insight: QueryBasedInsightModel, redirectToInsight = false) => ({
            insight,
            redirectToInsight,
        }),
        loadInsights: (debounce: boolean = true) => ({ debounce }),
        updateInsight: (insight: QueryBasedInsightModel) => ({ insight }),
        addInsight: (insight: QueryBasedInsightModel) => ({ insight }),
        openAlertModal: (alertId: AlertType['id']) => ({ alertId }),
        closeAlertModal: true,
        setDashboardUpdateLoading: (insightId: number, loading: boolean) => ({ insightId, loading }),
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
                }

                const legacyResponse: CountedPaginatedResponse<InsightModel> = await api.get(
                    `api/environments/${teamLogic.values.currentTeamId}/insights/?${toParams(params)}`
                )
                const response = {
                    ...legacyResponse,
                    results: legacyResponse.results.map((legacyInsight) => getQueryBasedInsightModel(legacyInsight)),
                }

                if (filters.search && String(filters.search).match(/^[0-9]+$/)) {
                    try {
                        const insight = await insightsApi.getByNumericId(Number(filters.search))
                        return {
                            ...response,
                            count: response.count + 1,
                            results: [insight, ...response.results],
                            filters,
                            offset: params.offset,
                        } as CountedPaginatedResponse<QueryBasedInsightModel> & { offset: number }
                    } catch {
                        // no insight with this ID found, discard
                    }
                }

                // scroll to top if the page changed, except if changed via back/forward
                if (
                    sceneLogic.findMounted()?.values.activeScene === Scene.SavedInsights &&
                    router.values.lastMethod !== 'POP' &&
                    values.insights.filters?.page !== filters.page
                ) {
                    window.scrollTo(0, 0)
                }

                return {
                    ...response,
                    filters,
                    offset: params.offset,
                } as CountedPaginatedResponse<QueryBasedInsightModel> & { offset: number }
            },
            updateFavoritedInsight: async ({ insight, favorited }) => {
                const response = await insightsApi.update(insight.id, {
                    favorited,
                })
                const updatedInsights = values.insights.results.map((i) =>
                    i.short_id === insight.short_id ? response : i
                )
                return { ...values.insights, results: updatedInsights }
            },
        },
    })),
    reducers({
        insights: {
            updateInsight: (state, { insight }) => ({
                ...state,
                results: state.results.map((i) => (i.short_id === insight.short_id ? insight : i)),
            }),
            addInsight: (state, { insight }) => ({
                ...state,
                count: state.count + 1,
                results: [insight, ...state.results],
            }),
        },
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
        alertModalId: [
            null as AlertType['id'] | null,
            {
                openAlertModal: (_, { alertId }) => alertId,
                closeAlertModal: () => null,
            },
        ],
        dashboardUpdatesInProgress: [
            {} as Record<number, boolean>,
            {
                setDashboardUpdateLoading: (state, { insightId, loading }) => {
                    return { ...state, [insightId]: loading }
                },
            },
        ],
    }),
    selectors({
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
                }
            },
        ],
        [SIDE_PANEL_CONTEXT_KEY]: [
            () => [],
            (): SidePanelSceneContext => {
                return {
                    discussions_disabled: true,
                }
            },
        ],
    }),
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
            const newInsight = await insightsApi.duplicate(insight)
            actions.addInsight(newInsight)
            redirectToInsight && router.actions.push(urls.insightEdit(newInsight.short_id))
        },
        setDates: () => {
            actions.loadInsights()
        },
        [insightsModel.actionTypes.renameInsightSuccess]: ({ item }) => {
            actions.updateInsight(item)
        },
        [dashboardsModel.actionTypes.updateDashboardInsight]: ({ insight }) => {
            const matchingInsightIndex = values.insights.results.findIndex((i) => i.id === insight.id)
            if (matchingInsightIndex >= 0) {
                actions.updateInsight(insight)
            } else {
                actions.addInsight(insight)
            }
        },
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
            const currentScene = sceneLogic.findMounted()?.values
            if (currentScene?.activeScene === Scene.SavedInsights) {
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
        [urls.savedInsights()]: async (
            _,
            { alert_id, ...searchParams }, // search params,
            hashParams
        ) => {
            if (alert_id) {
                actions.openAlertModal(alert_id)
            } else {
                actions.closeAlertModal()
            }

            if (hashParams.fromItem && String(hashParams.fromItem).match(/^[0-9]+$/)) {
                // `fromItem` for legacy /insights url redirect support
                const insightNumericId = parseInt(hashParams.fromItem)
                try {
                    const insight = await insightsApi.getByNumericId(insightNumericId)
                    if (!insight?.short_id) {
                        throw new Error('Could not find insight or missing short_id')
                    }
                    router.actions.replace(
                        hashParams.edit ? urls.insightEdit(insight.short_id) : urls.insightView(insight.short_id)
                    )
                } catch {
                    lemonToast.error(`Insight ID ${insightNumericId} couldn't be retrieved`)
                    router.actions.push(urls.savedInsights())
                }
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
