import { actions, connect, events, kea, listeners, path, reducers, selectors } from 'kea'
import { loaders } from 'kea-loaders'
import posthog from 'posthog-js'

import api from 'lib/api'
import { FEATURE_FLAGS } from 'lib/constants'
import { Sorting } from 'lib/lemon-ui/LemonTable'
import { lemonToast } from 'lib/lemon-ui/LemonToast/LemonToast'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { objectsEqual, toParams } from 'lib/utils'
import { eventUsageLogic } from 'lib/utils/eventUsageLogic'
import { DashboardLoadAction, dashboardLogic } from 'scenes/dashboard/dashboardLogic'
import { insightsApi } from 'scenes/insights/utils/api'
import { teamLogic } from 'scenes/teamLogic'
import { userLogic } from 'scenes/userLogic'

import { getQueryBasedInsightModel } from '~/queries/nodes/InsightViz/utils'
import type { QueryBasedInsightModel } from '~/types'

import type { addSavedInsightsModalLogicType } from './addSavedInsightsModalLogicType'
import { SavedInsightFilters, cleanFilters } from './savedInsightsLogic'

interface InsightListParams {
    order: string
    limit: number
    offset?: number
    saved: true
    basic: true
    search?: string
    insight?: string
    created_by?: number[]
    date_from?: SavedInsightFilters['dateFrom']
    date_to?: SavedInsightFilters['dateTo']
    dashboards?: number[]
    tags?: string
}

export const INSIGHTS_PER_PAGE = 15

export const addSavedInsightsModalLogic = kea<addSavedInsightsModalLogicType>([
    path(['scenes', 'saved-insights', 'addSavedInsightsModalLogic']),
    connect(() => ({
        values: [teamLogic, ['currentTeamId'], userLogic, ['user'], featureFlagLogic, ['featureFlags']],
        logic: [eventUsageLogic],
    })),
    actions({
        setModalFilters: (filters: Partial<SavedInsightFilters>, merge: boolean = true) => ({
            filters,
            merge,
        }),
        loadInsights: true,
        setModalPage: (page: number) => ({ page }),

        setDashboardUpdateLoading: (insightId: number, loading: boolean) => ({ insightId, loading }),
        addInsightToDashboard: (insight: QueryBasedInsightModel, dashboardId: number) => ({ insight, dashboardId }),
        removeInsightFromDashboard: (insight: QueryBasedInsightModel, dashboardId: number) => ({
            insight,
            dashboardId,
        }),
        dashboardUpdateFailed: (insightId: number) => ({ insightId }),

        updateInsight: (insight: QueryBasedInsightModel) => ({ insight }),
    }),
    loaders(({ values }) => ({
        insights: {
            __default: { results: [] as QueryBasedInsightModel[], count: 0 },
            loadInsights: async (_, breakpoint) => {
                await breakpoint(300)

                const { order, page, search, dashboardId, insightType, createdBy, dateFrom, dateTo, tags } =
                    values.filters

                const perPage = values.insightsPerPage
                const params: InsightListParams = {
                    order,
                    limit: perPage,
                    offset: Math.max(0, (page - 1) * perPage),
                    saved: true,
                    basic: true,
                }
                if (search) {
                    params.search = search
                }
                if (insightType && insightType.toLowerCase() !== 'all types') {
                    params.insight = insightType.toUpperCase()
                }
                if (dateFrom && dateFrom !== 'all') {
                    params.date_from = dateFrom
                    params.date_to = dateTo || undefined
                }
                if (dashboardId) {
                    params.dashboards = [dashboardId]
                }
                if (createdBy !== 'All users') {
                    params.created_by = createdBy as number[]
                }
                if (tags && tags.length > 0) {
                    params.tags = JSON.stringify(tags)
                }

                const response = await api.get(
                    `api/environments/${teamLogic.values.currentTeamId}/insights/?${toParams(params)}`
                )

                breakpoint()

                return {
                    ...response,
                    results: response.results.map((rawInsight: any) => getQueryBasedInsightModel(rawInsight)),
                }
            },
        },
        userInsights: {
            __default: { count: 0 },
            loadUserInsights: async () => {
                const response = await api.get(
                    `api/environments/${teamLogic.values.currentTeamId}/insights/?${toParams({
                        user: true,
                        saved: true,
                        basic: true,
                        limit: 1,
                    })}`
                )
                return { count: response.count }
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
        hasLoadedInsights: [
            false,
            {
                loadInsightsSuccess: () => true,
                loadInsightsFailure: () => true,
            },
        ],
    }),
    selectors({
        filters: [
            (s) => [s.rawModalFilters],
            (rawModalFilters): SavedInsightFilters => cleanFilters(rawModalFilters || {}),
        ],
        hasFilteredUI: [
            (s) => [s.featureFlags],
            (featureFlags): boolean => {
                const variant = featureFlags[FEATURE_FLAGS.PRODUCT_ANALYTICS_DASHBOARD_MODAL_SMART_DEFAULTS]
                return variant === 'filtered' || variant === 'smart-filtered'
            },
        ],
        hasSmartDefaults: [
            (s) => [s.featureFlags],
            (featureFlags): boolean =>
                featureFlags[FEATURE_FLAGS.PRODUCT_ANALYTICS_DASHBOARD_MODAL_SMART_DEFAULTS] === 'smart-filtered',
        ],
        insightsPerPage: [() => [], (): number => INSIGHTS_PER_PAGE],
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
        },
        setModalFilters: async (_, breakpoint, __, previousState) => {
            const oldFilters = selectors.filters(previousState)
            const newFilters = values.filters

            if (!objectsEqual(oldFilters, newFilters)) {
                actions.loadInsights()
            }

            if (newFilters.search !== undefined && newFilters.search !== oldFilters.search) {
                await breakpoint(1000)
                posthog.capture('insight dashboard modal searched', {
                    search_term: newFilters.search,
                })
            }
        },

        loadUserInsightsSuccess: () => {
            const { userInsights, user, hasSmartDefaults } = values
            if (hasSmartDefaults && userInsights.count > 0 && user?.id) {
                actions.setModalFilters({ createdBy: [user.id] })
            } else {
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
            } catch (e) {
                actions.dashboardUpdateFailed(insight.id)
                lemonToast.error('Failed to add insight to dashboard')
                throw e
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
            } catch (e) {
                actions.dashboardUpdateFailed(insight.id)
                lemonToast.error('Failed to remove insight from dashboard')
                throw e
            } finally {
                eventUsageLogic.actions.reportRemovedInsightFromDashboard(insight, dashboardId)
                actions.setDashboardUpdateLoading(insight.id, false)
            }
        },
    })),
    events(({ actions, values }) => ({
        afterMount: () => {
            if (values.hasSmartDefaults) {
                actions.loadUserInsights()
            } else {
                actions.loadInsights()
            }
        },
    })),
])
