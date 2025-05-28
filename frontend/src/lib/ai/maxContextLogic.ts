import { kea } from 'kea'
import { router } from 'kea-router'

import { breadcrumbsLogic } from '~/layout/navigation/Breadcrumbs/breadcrumbsLogic'
import { billingLogic } from '~/scenes/billing/billingLogic'
import { sceneLogic } from '~/scenes/sceneLogic'
import { BillingType } from '~/types'

import type { maxContextLogicType } from './maxContextLogicType'
import {
    DashboardDisplayContext,
    GlobalBillingContext,
    InsightContextForMax,
    MaxAddonInfo,
    MaxContextShape,
    MaxNavigationContext,
    MaxProductInfo,
    MultiInsightContainer,
} from './maxTypes'

// Utility function to transform billing data for Max context
export function transformBillingDataForMax(billing: BillingType | null): GlobalBillingContext | null {
    if (!billing) {
        return null
    }

    // Transform products
    const products: MaxProductInfo[] =
        billing.products?.map((product) => ({
            type: product.type,
            name: product.name,
            description: product.description,
            is_used: (product.current_usage || 0) > 0,
            has_exceeded_limit: product.has_exceeded_limit || false,
            current_usage: product.current_usage,
            usage_limit: product.usage_limit,
            percentage_usage: product.percentage_usage || 0,
        })) || []

    // Transform addons (flattened from all products)
    const addons: MaxAddonInfo[] = []
    billing.products?.forEach((product) => {
        if (product.addons) {
            product.addons.forEach((addon) => {
                addons.push({
                    type: addon.type,
                    name: addon.name,
                    description: addon.description,
                    is_used: (addon.current_usage || 0) > 0,
                    has_exceeded_limit: (addon.usage_limit && addon.current_usage > addon.usage_limit) || false,
                    current_usage: addon.current_usage || 0,
                    usage_limit: addon.usage_limit,
                    percentage_usage: addon.percentage_usage,
                    included_with_main_product: addon.included_with_main_product,
                })
            })
        }
    })

    return {
        has_active_subscription: billing.has_active_subscription || false,
        subscription_level: billing.subscription_level || 'free',
        billing_plan: billing.billing_plan,
        is_deactivated: billing.deactivated,
        products,
        addons,
        total_current_amount_usd: billing.current_total_amount_usd,
        total_projected_amount_usd: billing.projected_total_amount_usd,
        trial: billing.trial
            ? {
                  is_active: billing.trial.status === 'active',
                  expires_at: billing.trial.expires_at,
                  target: billing.trial.target,
              }
            : undefined,
        billing_period: billing.billing_period
            ? {
                  current_period_start: billing.billing_period.current_period_start?.toISOString(),
                  current_period_end: billing.billing_period.current_period_end?.toISOString(),
                  interval: billing.billing_period.interval,
              }
            : undefined,
    }
}

export const maxContextLogic = kea<maxContextLogicType>({
    path: ['lib', 'ai', 'maxContextLogic'],
    connect: () => ({
        values: [breadcrumbsLogic({ hashParams: {} }), ['documentTitle'], billingLogic, ['billing']],
        actions: [],
    }),
    actions: {
        addOrUpdateActiveInsight: (key: string, data: InsightContextForMax) => ({ key, data }),
        removeActiveInsight: (key: string) => ({ key }),
        clearAllActiveInsights: true,
        setGlobalBillingContext: (billingContext: GlobalBillingContext) => ({ billingContext }),
        clearGlobalBillingContext: true,
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
        globalBilling: [
            null as GlobalBillingContext | null,
            {
                setGlobalBillingContext: (_: any, { billingContext }: { billingContext: GlobalBillingContext }) =>
                    billingContext,
                clearGlobalBillingContext: () => null,
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
        transformedBillingContext: [
            () => [billingLogic.selectors.billing],
            (billing: BillingType | null): GlobalBillingContext | null => {
                return transformBillingDataForMax(billing)
            },
        ],
        compiledContext: [
            (s: any) => [s.activeInsights, s.transformedBillingContext, s.navigation, s.dashboardContext],
            (
                activeInsights: MultiInsightContainer | null,
                globalBilling: GlobalBillingContext | null,
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

                if (globalBilling) {
                    context.global_info = { ...(context.global_info || {}), billing: globalBilling }
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
