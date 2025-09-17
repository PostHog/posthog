import { actions, connect, events, kea, listeners, path, reducers, selectors } from 'kea'
import { loaders } from 'kea-loaders'

import api from 'lib/api'
import { Sorting } from 'lib/lemon-ui/LemonTable'
import { lemonToast } from 'lib/lemon-ui/LemonToast/LemonToast'
import { objectsEqual, toParams } from 'lib/utils'
import { eventUsageLogic } from 'lib/utils/eventUsageLogic'
import { DashboardLoadAction, dashboardLogic } from 'scenes/dashboard/dashboardLogic'
import { insightsApi } from 'scenes/insights/utils/api'
import { teamLogic } from 'scenes/teamLogic'

import { getQueryBasedInsightModel } from '~/queries/nodes/InsightViz/utils'
import type { QueryBasedInsightModel } from '~/types'

import type { addSavedInsightsModalLogicType } from './addSavedInsightsModalLogicType'
import { SavedInsightFilters, cleanFilters } from './savedInsightsLogic'

export const INSIGHTS_PER_PAGE = 30

export const addSavedInsightsModalLogic = kea<addSavedInsightsModalLogicType>([
    path(['scenes', 'saved-insights', 'addSavedInsightsModalLogic']),
    connect(() => ({
        values: [teamLogic, ['currentTeamId']],
        logic: [eventUsageLogic],
    })),
    actions({
        setModalFilters: (filters: Partial<SavedInsightFilters>, merge: boolean = true, debounce: boolean = true) => ({
            filters,
            merge,
            debounce,
        }),
        loadInsights: true,
        setModalPage: (page: number) => ({ page }),

        setDashboardUpdateLoading: (insightId: number, loading: boolean) => ({ insightId, loading }),
        addInsightToDashboard: (insight: QueryBasedInsightModel, dashboardId: number) => ({ insight, dashboardId }),
        removeInsightFromDashboard: (insight: QueryBasedInsightModel, dashboardId: number) => ({
            insight,
            dashboardId,
        }),

        updateInsight: (insight: QueryBasedInsightModel) => ({ insight }),
    }),
    loaders(({ values }) => ({
        insights: {
            __default: { results: [] as QueryBasedInsightModel[], count: 0 },
            loadInsights: async () => {
                const { order, page, search, dashboardId, insightType, createdBy, dateFrom, dateTo } = values.filters

                const params: Record<string, any> = {
                    order,
                    limit: INSIGHTS_PER_PAGE,
                    offset: Math.max(0, (page - 1) * INSIGHTS_PER_PAGE),
                    saved: true,
                    basic: true,
                }

                if (search) {
                    params.search = search
                }
                if (insightType && insightType.toLowerCase() !== 'all types') {
                    params.insight = insightType.toUpperCase()
                }
                if (createdBy && createdBy !== 'All users') {
                    params.created_by = createdBy
                }
                if (dateFrom && dateFrom !== 'all') {
                    params.date_from = dateFrom
                    params.date_to = dateTo || undefined
                }
                if (dashboardId) {
                    params.dashboards = [dashboardId]
                }

                const response = await api.get(
                    `api/environments/${teamLogic.values.currentTeamId}/insights/?${toParams(params)}`
                )

                return {
                    ...response,
                    results: response.results.map((rawInsight: any) => getQueryBasedInsightModel(rawInsight)),
                }
            },
        },
    })),
    reducers({
        rawModalFilters: [
            null as Partial<SavedInsightFilters> | null,
            {
                setModalFilters: (state, { filters, merge }) => {
                    return cleanFilters({
                        ...(merge ? state || {} : {}),
                        ...filters,
                        ...('page' in filters ? {} : { page: 1 }),
                    })
                },
            },
        ],
        insights: {
            updateInsight: (state, { insight }) => ({
                ...state,
                results: state.results.map((i) => (i.short_id === insight.short_id ? insight : i)),
            }),
        },
        dashboardUpdatesInProgress: [
            {} as Record<number, boolean>,
            {
                setDashboardUpdateLoading: (state, { insightId, loading }) => ({
                    ...state,
                    [insightId]: loading,
                }),
            },
        ],
    }),
    selectors({
        filters: [
            (s) => [s.rawModalFilters],
            (rawModalFilters): SavedInsightFilters => cleanFilters(rawModalFilters || {}),
        ],
        count: [(s) => [s.insights], (insights) => insights.count],
        sorting: [
            (s) => [s.filters],
            (filters): Sorting | null =>
                filters.order
                    ? filters.order.startsWith('-')
                        ? { columnKey: filters.order.slice(1), order: -1 }
                        : { columnKey: filters.order, order: 1 }
                    : null,
        ],
        modalPage: [(s) => [s.filters], (filters) => filters.page],
    }),
    listeners(({ actions, values, selectors }) => ({
        setModalPage: async ({ page }) => {
            actions.setModalFilters({ page }, true)
            actions.loadInsights()
        },
        setModalFilters: async ({ debounce }, breakpoint, __, previousState) => {
            const oldFilters = selectors.filters(previousState)
            const newFilters = values.filters

            if (debounce) {
                await breakpoint(300)
            }
            if (!objectsEqual(oldFilters, newFilters)) {
                actions.loadInsights()
            }
        },

        addInsightToDashboard: async ({ insight, dashboardId }) => {
            try {
                actions.setDashboardUpdateLoading(insight.id, true)
                const response = await insightsApi.update(insight.id, {
                    dashboards: [...(insight.dashboards || []), dashboardId],
                })
                if (response) {
                    actions.updateInsight(response)
                    const logic = dashboardLogic({ id: dashboardId })
                    logic.mount()
                    logic.actions.loadDashboard({ action: DashboardLoadAction.Update })
                    logic.unmount()
                    lemonToast.success('Insight added to dashboard')
                }
            } finally {
                eventUsageLogic.actions.reportSavedInsightToDashboard(insight, dashboardId)
                actions.setDashboardUpdateLoading(insight.id, false)
            }
        },
        removeInsightFromDashboard: async ({ insight, dashboardId }) => {
            try {
                actions.setDashboardUpdateLoading(insight.id, true)
                const response = await insightsApi.update(insight.id, {
                    dashboards: (insight.dashboards || []).filter((d) => d !== dashboardId),
                    dashboard_tiles: (insight.dashboard_tiles || []).filter((dt) => dt.dashboard_id !== dashboardId),
                })
                if (response) {
                    actions.updateInsight(response)
                    const logic = dashboardLogic({ id: dashboardId })
                    logic.mount()
                    logic.actions.loadDashboard({ action: DashboardLoadAction.Update })
                    logic.unmount()
                    lemonToast.success('Insight removed from dashboard')
                }
            } finally {
                eventUsageLogic.actions.reportRemovedInsightFromDashboard(insight, dashboardId)
                actions.setDashboardUpdateLoading(insight.id, false)
            }
        },
    })),
    events(({ actions }) => ({
        afterMount: () => {
            actions.loadInsights()
        },
    })),
])
