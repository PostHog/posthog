import { kea } from 'kea'
import { router } from 'kea-router'

import { breadcrumbsLogic } from '~/layout/navigation/Breadcrumbs/breadcrumbsLogic'
import {
    isInsightVizNode,
    isRevenueAnalyticsGrowthRateQuery,
    isRevenueAnalyticsOverviewQuery,
    isRevenueAnalyticsTopCustomersQuery,
} from '~/queries/utils'
import { sceneLogic } from '~/scenes/sceneLogic'

import type { maxContextLogicType } from './maxContextLogicType'
import {
    DashboardDisplayContext,
    InsightContextForMax,
    MaxContextShape,
    MaxNavigationContext,
    MultiInsightContainer,
} from './maxTypes'

export const maxContextLogic = kea<maxContextLogicType>({
    path: ['lib', 'ai', 'maxContextLogic'],
    connect: () => ({
        values: [breadcrumbsLogic({ hashParams: {} }), ['documentTitle']],
        actions: [],
    }),
    actions: {
        addOrUpdateActiveInsight: (key: string, data: InsightContextForMax) => ({ key, data }),
        removeActiveInsight: (key: string) => ({ key }),
        clearAllActiveInsights: true,
        setNavigationContext: (path: string, pageTitle?: string) => ({ path, pageTitle }),
        clearNavigationContext: true,
        setDashboardContext: (dashboardContext: DashboardDisplayContext) => ({ dashboardContext }),
        clearDashboardContext: true,
        addRevenueAnalyticsQueries: (queries: Record<string, any>) => ({ queries }),
        clearRevenueAnalyticsQueries: true,
    },
    reducers: {
        activeInsights: [
            {} as MultiInsightContainer,
            {
                addOrUpdateActiveInsight: (
                    state: MultiInsightContainer,
                    { key, data }: { key: string; data: InsightContextForMax }
                ) => ({ ...state, [key]: data }),
                removeActiveInsight: (state: MultiInsightContainer, { key }: { key: string }) => {
                    const { [key]: _removed, ...rest } = state
                    return rest
                },
                clearAllActiveInsights: () => ({}),
            },
        ],
        navigation: [
            null as MaxNavigationContext | null,
            {
                setNavigationContext: (_: any, { path, pageTitle }: { path: string; pageTitle?: string }) => ({
                    path,
                    page_title: pageTitle,
                }),
                clearNavigationContext: () => null,
            },
        ],
        dashboardContext: [
            null as DashboardDisplayContext | null,
            {
                setDashboardContext: (_: any, { dashboardContext }: { dashboardContext: DashboardDisplayContext }) =>
                    dashboardContext,
                clearDashboardContext: () => null,
            },
        ],
        revenueAnalyticsQueries: [
            null as Record<string, any> | null,
            {
                addRevenueAnalyticsQueries: (_: any, { queries }: { queries: Record<string, any> }) => queries,
                clearRevenueAnalyticsQueries: () => null,
            },
        ],
    },
    listeners: ({ actions, values }) => ({
        [router.actionTypes.locationChanged]: () => {
            actions.clearAllActiveInsights()
            actions.clearDashboardContext()
            actions.clearRevenueAnalyticsQueries()
        },
        [sceneLogic.actionTypes.setScene]: () => {
            // Scene has been set, now update navigation with proper title
            setTimeout(() => {
                actions.setNavigationContext(router.values.location.pathname, values.documentTitle)
            }, 100)
        },
    }),
    events: ({ actions, values }) => ({
        afterMount: () => {
            actions.setNavigationContext(router.values.location.pathname, values.documentTitle)
        },
    }),
    selectors: {
        compiledContext: [
            (s: any) => [s.activeInsights, s.navigation, s.dashboardContext, s.revenueAnalyticsQueries],
            (
                activeInsights: MultiInsightContainer | null,
                navigation: MaxNavigationContext | null,
                dashboardContext: DashboardDisplayContext | null,
                revenueAnalyticsQueries: Record<string, any> | null
            ): MaxContextShape | null => {
                const context: MaxContextShape = {}
                let hasData = false

                // Set dashboard as primary focus if available
                if (dashboardContext) {
                    context.active_dashboard = dashboardContext
                    hasData = true
                }

                if (activeInsights && Object.keys(activeInsights).length > 0) {
                    context.active_insights = activeInsights
                    hasData = true
                }

                // Add revenue analytics queries as insights if available
                if (revenueAnalyticsQueries) {
                    const revenueInsights: MultiInsightContainer = {}
                    Object.entries(revenueAnalyticsQueries).forEach(([key, query]) => {
                        revenueInsights[`revenue-analytics-${key}`] = {
                            id: `revenue-analytics-${key}`,
                            name: isRevenueAnalyticsOverviewQuery(query)
                                ? 'Revenue Analytics Overview'
                                : isRevenueAnalyticsGrowthRateQuery(query)
                                ? 'Revenue Analytics Growth Rate'
                                : isRevenueAnalyticsTopCustomersQuery(query)
                                ? 'Revenue Analytics Top Customers'
                                : 'Revenue Analytics',
                            query: isInsightVizNode(query) ? query.source : query,
                            insight_type:
                                (isInsightVizNode(query) ? query.source.kind : query.kind) || 'REVENUE_ANALYTICS',
                        }
                    })

                    if (Object.keys(revenueInsights).length > 0) {
                        context.active_insights = { ...(context.active_insights || {}), ...revenueInsights }
                        hasData = true
                    }
                }

                if (navigation) {
                    context.global_info = { ...(context.global_info || {}), navigation }
                    hasData = true
                }
                return hasData ? context : null
            },
        ],
        contextSummary: [
            (s: any) => [s.activeInsights, s.dashboardContext, s.revenueAnalyticsQueries],
            (
                activeInsights: MultiInsightContainer | null,
                dashboardContext: DashboardDisplayContext | null,
                revenueAnalyticsQueries: Record<string, any> | null
            ): { items: Array<{ icon: 'dashboard' | 'insights'; text: string }> } | null => {
                const contextItems: Array<{ icon: 'dashboard' | 'insights'; text: string }> = []

                if (dashboardContext) {
                    contextItems.push({
                        icon: 'dashboard',
                        text: `Dashboard: ${dashboardContext.name || 'Current dashboard'}`,
                    })
                }

                let totalInsights = 0
                if (activeInsights && Object.keys(activeInsights).length > 0) {
                    totalInsights += Object.keys(activeInsights).length
                }
                if (revenueAnalyticsQueries && Object.keys(revenueAnalyticsQueries).length > 0) {
                    totalInsights += Object.keys(revenueAnalyticsQueries).length
                }

                if (totalInsights > 0) {
                    contextItems.push({
                        icon: 'insights',
                        text: `${totalInsights} insight${totalInsights > 1 ? 's' : ''} from this page`,
                    })
                }

                if (contextItems.length === 0) {
                    return null
                }

                return {
                    items: contextItems,
                }
            },
        ],
    },
})
