import { kea } from 'kea'
import { router } from 'kea-router'

import { breadcrumbsLogic } from '~/layout/navigation/Breadcrumbs/breadcrumbsLogic'
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
    },
    listeners: ({ actions, values }) => ({
        [router.actionTypes.locationChanged]: () => {
            actions.clearAllActiveInsights()
            actions.clearDashboardContext()
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
            (s: any) => [s.activeInsights, s.navigation, s.dashboardContext],
            (
                activeInsights: MultiInsightContainer | null,
                navigation: MaxNavigationContext | null,
                dashboardContext: DashboardDisplayContext | null
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
                dashboardContext: DashboardDisplayContext | null
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
