import { afterMount, connect, kea, path, selectors } from 'kea'
import { BillingType, TeamType } from '~/types'

import { billingLogic } from 'scenes/billing/billingLogic'
import { billingUsageLogic } from 'scenes/billing/billingUsageLogic'
import { organizationLogic } from 'scenes/organizationLogic'
import { teamLogic } from 'scenes/teamLogic'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { pipelineDestinationsLogic } from 'scenes/pipeline/destinations/destinationsLogic'
import { DESTINATION_TYPES } from 'scenes/pipeline/destinations/constants'
import { Destination } from 'scenes/pipeline/types'
import { BillingUsageResponse } from 'scenes/billing/billingUsageLogic'
import { isAddonVisible } from 'scenes/billing/billing-utils'
import type { maxBillingContextLogicType } from './maxBillingContextLogicType'
import { billingSpendLogic, BillingSpendResponse } from 'scenes/billing/billingSpendLogic'

// Simplified product information for Max context
export interface MaxProductInfo {
    type: string
    name: string
    description: string
    is_used: boolean // current_usage > 0
    has_exceeded_limit: boolean
    current_usage?: number
    usage_limit?: number | null
    percentage_usage: number
    custom_limit_usd?: number | null
    next_period_custom_limit_usd?: number | null
    docs_url?: string
    projected_amount_usd?: string | null
    projected_amount_usd_with_limit?: string | null
}

// Simplified addon information for Max context
export interface MaxAddonInfo {
    type: string
    name: string
    description: string
    is_used: boolean // current_usage > 0
    has_exceeded_limit: boolean
    current_usage: number
    usage_limit?: number | null
    percentage_usage?: number
    custom_limit_usd?: number | null
    next_period_custom_limit_usd?: number | null
    docs_url?: string
    projected_amount_usd?: string | null
    projected_amount_usd_with_limit?: string | null
}

// Usage data context for Max
export interface MaxUsageContext {
    date_range: {
        start_date: string
        end_date: string
    }
    usage_summary: Array<{
        product_type: string
        product_name: string
        total_usage: number
        dates: string[]
        data: number[]
    }>
}

export interface MaxBillingContext {
    // Overall billing status
    has_active_subscription: boolean
    subscription_level: 'free' | 'paid' | 'custom'
    billing_plan: string | null
    is_deactivated?: boolean

    // Products information
    products: MaxProductInfo[]

    // Addons information (flattened from all products)
    addons: MaxAddonInfo[]

    // Spending
    total_current_amount_usd?: string
    projected_total_amount_usd?: string
    projected_total_amount_usd_after_discount?: string
    projected_total_amount_usd_with_limit?: string
    projected_total_amount_usd_with_limit_after_discount?: string

    // Startup program
    startup_program_label?: string
    startup_program_label_previous?: string

    // Trial information
    trial?: {
        is_active: boolean
        expires_at?: string
        target?: string
    }

    // Billing period
    billing_period?: {
        current_period_start: string
        current_period_end: string
        interval: 'month' | 'year'
    }

    // Usage history
    usage_history?: BillingUsageResponse['results']
    // Spend history
    spend_history?: BillingSpendResponse['results']

    // Settings
    settings: {
        autocapture_on: boolean
        active_destinations: number
    }
}

export const billingToMaxContext = (
    billing: BillingType | null,
    featureFlags: Record<string, any>,
    currentTeam: TeamType,
    destinations: Destination[],
    usageResponse?: BillingUsageResponse | null,
    spendResponse?: BillingSpendResponse | null
): MaxBillingContext | null => {
    if (!billing) {
        return null
    }

    // Helper function to get custom limit for a product
    const getCustomLimitForProduct = (
        key: 'custom_limits_usd' | 'next_period_custom_limits_usd',
        productType: string,
        usageKey?: string
    ): number | null => {
        if (!billing[key]) {
            return null
        }

        // First try product type, then fallback to usage key
        const customLimit = billing[key]?.[productType]
        if (customLimit === 0 || customLimit) {
            return customLimit
        }

        return usageKey ? billing[key]?.[usageKey] ?? null : null
    }

    // Filter platform products to only include the highest tier available
    const processedProducts = (billing.products || []).map((product) => {
        if (product.type === 'platform_and_support') {
            const availablePlans = product.plans || []
            const currentPlanIndex = availablePlans.findIndex((plan) => plan.current_plan)
            const highestAvailablePlan =
                currentPlanIndex >= 0 ? availablePlans[currentPlanIndex] : availablePlans[availablePlans.length - 1] // Fallback to highest plan

            if (highestAvailablePlan) {
                return {
                    ...product,
                    name: `${product.name} (${highestAvailablePlan.name})`,
                    description: highestAvailablePlan.description || product.description,
                }
            }
        }
        return product
    })

    const maxProducts: MaxProductInfo[] = processedProducts.map((product) => {
        const customLimit = getCustomLimitForProduct('custom_limits_usd', product.type, product.usage_key || undefined)
        const nextPeriodCustomLimit = getCustomLimitForProduct(
            'next_period_custom_limits_usd',
            product.type,
            product.usage_key || undefined
        )
        return {
            type: product.type,
            name: product.name,
            description: product.description || '',
            is_used: (product.current_usage || 0) > 0,
            has_exceeded_limit: product.percentage_usage > 1,
            current_usage: product.current_usage,
            usage_limit: product.tiered && product.tiers ? product.tiers?.[0].up_to : product.free_allocation,
            percentage_usage: product.percentage_usage || 0,
            custom_limit_usd: customLimit,
            next_period_custom_limit_usd: nextPeriodCustomLimit,
            projected_amount_usd: product.projected_amount_usd,
            projected_amount_usd_with_limit: product.projected_amount_usd_with_limit,
            docs_url: product.docs_url,
        }
    })

    const maxAddons: MaxAddonInfo[] = (billing.products || [])
        .flatMap((product) => (product.addons || []).map((addon) => ({ product, addon })))
        .filter(({ product, addon }) => isAddonVisible(product, addon, featureFlags))
        .map(({ addon }) => {
            const customLimit = getCustomLimitForProduct('custom_limits_usd', addon.type, addon.usage_key || undefined)
            const nextPeriodCustomLimit = getCustomLimitForProduct(
                'next_period_custom_limits_usd',
                addon.type,
                addon.usage_key || undefined
            )

            return {
                type: addon.type,
                name: addon.name,
                description: addon.description || '',
                is_used: (addon.current_usage || 0) > 0,
                has_exceeded_limit: (addon.percentage_usage || 0) > 1,
                current_usage: addon.current_usage || 0,
                usage_limit: addon.usage_limit,
                percentage_usage: addon.percentage_usage,
                custom_limit_usd: customLimit,
                next_period_custom_limit_usd: nextPeriodCustomLimit,
                docs_url: addon.docs_url || undefined,
                projected_amount_usd: addon.projected_amount_usd,
            }
        })

    return {
        has_active_subscription: billing.has_active_subscription || false,
        subscription_level: billing.has_active_subscription ? 'paid' : 'free',
        billing_plan: billing.billing_plan || null,
        is_deactivated: billing.deactivated,
        products: maxProducts,
        addons: maxAddons,
        total_current_amount_usd: billing.current_total_amount_usd,
        projected_total_amount_usd: billing.projected_total_amount_usd,
        projected_total_amount_usd_after_discount: billing.projected_total_amount_usd_after_discount,
        projected_total_amount_usd_with_limit: billing.projected_total_amount_usd_with_limit,
        projected_total_amount_usd_with_limit_after_discount:
            billing.projected_total_amount_usd_with_limit_after_discount,
        startup_program_label: billing.startup_program_label || undefined,
        startup_program_label_previous: billing.startup_program_label_previous || undefined,
        trial: billing.trial
            ? {
                  is_active: billing.trial.status === 'active',
                  expires_at: billing.trial.expires_at,
                  target: billing.trial.target,
              }
            : undefined,
        billing_period: billing.billing_period
            ? {
                  current_period_start: billing.billing_period.current_period_start.format('YYYY-MM-DD'),
                  current_period_end: billing.billing_period.current_period_end.format('YYYY-MM-DD'),
                  interval: billing.billing_period.interval,
              }
            : undefined,
        usage_history: usageResponse?.results,
        spend_history: spendResponse?.results,
        settings: {
            autocapture_on: !currentTeam.autocapture_opt_out,
            active_destinations: destinations.length,
        },
    }
}

export const maxBillingContextLogic = kea<maxBillingContextLogicType>([
    path(['lib', 'ai', 'maxBillingContextLogic']),
    connect(() => ({
        values: [
            billingLogic,
            ['billing'],
            billingUsageLogic,
            ['billingUsageResponse'],
            billingSpendLogic,
            ['billingSpendResponse'],
            organizationLogic,
            ['isAdminOrOwner'],
            teamLogic,
            ['currentTeam'],
            featureFlagLogic,
            ['featureFlags'],
            pipelineDestinationsLogic({ types: DESTINATION_TYPES }),
            ['destinations'],
        ],
        actions: [
            billingUsageLogic,
            ['loadBillingUsage', 'toggleTeamBreakdown as loadBillingUsageToggleTeamBreakdown'],
            billingSpendLogic,
            ['loadBillingSpend', 'toggleBreakdown as loadBillingSpendToggleBreakdown'],
        ],
    })),
    selectors({
        billingContext: [
            (s: any) => [
                s.billing,
                s.billingUsageResponse,
                s.billingSpendResponse,
                s.isAdminOrOwner,
                s.currentTeam,
                s.featureFlags,
                s.destinations,
            ],
            (
                billing: BillingType | null,
                billingUsageResponse: BillingUsageResponse | null,
                billingSpendResponse: BillingSpendResponse | null,
                isAdminOrOwner: boolean,
                currentTeam: TeamType,
                featureFlags: Record<string, any>,
                destinations: Destination[]
            ): MaxBillingContext | null => {
                if (!isAdminOrOwner) {
                    return null
                }
                return billingToMaxContext(
                    billing,
                    featureFlags,
                    currentTeam,
                    destinations,
                    billingUsageResponse,
                    billingSpendResponse
                )
            },
        ],
    }),
    afterMount(({ actions }) => {
        // Load usage and spend data with breakdown by team
        actions.loadBillingUsageToggleTeamBreakdown()
        actions.loadBillingUsage()
        actions.loadBillingSpendToggleBreakdown('team')
        actions.loadBillingSpend()
    }),
])
