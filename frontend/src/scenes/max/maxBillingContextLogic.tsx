import { connect, kea, path, selectors } from 'kea'

import { dayjs } from 'lib/dayjs'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { isAddonVisible } from 'scenes/billing/billing-utils'
import { billingLogic } from 'scenes/billing/billingLogic'
import { BillingSpendResponse, billingSpendLogic } from 'scenes/billing/billingSpendLogic'
import { BillingUsageResponse, billingUsageLogic } from 'scenes/billing/billingUsageLogic'
import { hogFunctionsListLogic } from 'scenes/hog-functions/list/hogFunctionsListLogic'
import { organizationLogic } from 'scenes/organizationLogic'
import { teamLogic } from 'scenes/teamLogic'

import { BillingType, HogFunctionType, TeamType } from '~/types'

import type { maxBillingContextLogicType } from './maxBillingContextLogicType'

export const DEFAULT_BILLING_DATE_FROM = dayjs().subtract(1, 'month').subtract(1, 'day').format('YYYY-MM-DD')
export const DEFAULT_BILLING_DATE_TO = dayjs().subtract(1, 'day').format('YYYY-MM-DD')

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
    docs_url?: string
    projected_amount_usd?: string | null
    projected_amount_usd_with_limit?: string | null
}

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
    addons: MaxAddonInfo[]
}

export enum MaxBillingContextSubscriptionLevel {
    FREE = 'free',
    PAID = 'paid',
    CUSTOM = 'custom',
}

export interface MaxBillingContextTrial {
    is_active: boolean
    expires_at?: string
    target?: string
}

export enum MaxBillingContextBillingPeriodInterval {
    MONTH = 'month',
    YEAR = 'year',
}

export interface MaxBillingContextBillingPeriod {
    current_period_start: string
    current_period_end: string
    interval: MaxBillingContextBillingPeriodInterval
}

export interface MaxBillingContextSettings {
    autocapture_on: boolean
    active_destinations: number
}

export interface MaxBillingContext {
    // Overall billing status
    has_active_subscription: boolean
    subscription_level: MaxBillingContextSubscriptionLevel
    billing_plan: string | null
    is_deactivated?: boolean

    // Products information
    products: MaxProductInfo[]

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
    trial?: MaxBillingContextTrial

    // Billing period
    billing_period?: MaxBillingContextBillingPeriod

    // Usage history
    usage_history?: BillingUsageResponse['results']
    // Spend history
    spend_history?: BillingSpendResponse['results']

    // Settings
    settings: MaxBillingContextSettings
}

export const billingToMaxContext = (
    billing: BillingType | null,
    featureFlags: Record<string, any>,
    currentTeam: TeamType,
    destinations: HogFunctionType[],
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

        return usageKey ? (billing[key]?.[usageKey] ?? null) : null
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
        const addons = product.addons
            .filter((addon) => isAddonVisible(product, addon, featureFlags))
            .map((addon) => {
                return {
                    type: addon.type,
                    name: addon.name,
                    description: addon.description || '',
                    is_used: (addon.current_usage || 0) > 0,
                    has_exceeded_limit: (addon.percentage_usage || 0) > 1,
                    current_usage: addon.current_usage || 0,
                    usage_limit: addon.usage_limit,
                    percentage_usage: addon.percentage_usage,
                    docs_url: addon.docs_url || undefined,
                    projected_amount_usd: addon.projected_amount_usd,
                }
            })
        return {
            type: product.type,
            name: product.name,
            description: product.description || '',
            is_used: (product.current_usage || 0) > 0,
            has_exceeded_limit: product.percentage_usage > 1,
            current_usage: product.current_usage,
            usage_limit: product.usage_limit,
            percentage_usage: product.percentage_usage || 0,
            custom_limit_usd: customLimit,
            next_period_custom_limit_usd: nextPeriodCustomLimit,
            projected_amount_usd: product.projected_amount_usd,
            projected_amount_usd_with_limit: product.projected_amount_usd_with_limit,
            docs_url: product.docs_url,
            addons: addons,
        }
    })

    return {
        has_active_subscription: billing.has_active_subscription || false,
        subscription_level:
            (billing.subscription_level as MaxBillingContextSubscriptionLevel) ||
            MaxBillingContextSubscriptionLevel.FREE,
        billing_plan: billing.billing_plan || null,
        is_deactivated: billing.deactivated,
        products: maxProducts,
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
                  interval: billing.billing_period.interval as MaxBillingContextBillingPeriodInterval,
              }
            : undefined,
        usage_history: usageResponse?.results,
        spend_history: spendResponse?.results,
        settings: {
            autocapture_on: !currentTeam.autocapture_opt_out,
            active_destinations: destinations.filter((destination) => destination.enabled).length,
        },
    }
}

export const maxBillingContextLogic = kea<maxBillingContextLogicType>([
    path(['scenes', 'max', 'maxBillingContextLogic']),
    connect(() => ({
        values: [
            billingLogic,
            ['billing'],
            billingUsageLogic({
                initialFilters: { breakdowns: ['type', 'team'] },
                dateFrom: DEFAULT_BILLING_DATE_FROM, // we set them here so we are sure it will stay fixed to a 1 month period even if the usage logic changes default values
                dateTo: DEFAULT_BILLING_DATE_TO,
                dashboardItemId: 'max-billing-context', // This makes it a separate instance, prevents conflicts with the spend logic on the usage page
            }),
            ['billingUsageResponse'],
            billingSpendLogic({
                initialFilters: { breakdowns: ['type', 'team'] },
                dateFrom: DEFAULT_BILLING_DATE_FROM, // same here for spend
                dateTo: DEFAULT_BILLING_DATE_TO,
                dashboardItemId: 'max-billing-context', // This makes it a separate instance, prevents conflicts with the spend logic on the spend page
            }),
            ['billingSpendResponse'],
            organizationLogic,
            ['isAdminOrOwner'],
            teamLogic,
            ['currentTeam'],
            featureFlagLogic,
            ['featureFlags'],
            hogFunctionsListLogic({ type: 'destination' }),
            ['hogFunctions'],
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
                s.hogFunctions,
            ],
            (
                billing: BillingType | null,
                billingUsageResponse: BillingUsageResponse | null,
                billingSpendResponse: BillingSpendResponse | null,
                isAdminOrOwner: boolean,
                currentTeam: TeamType,
                featureFlags: Record<string, any>,
                destinations: HogFunctionType[]
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
            {
                equalityCheck: (prev: any[], next: any[]) => {
                    if (!prev || !next) {
                        return prev === next
                    }
                    return (
                        prev[0] === next[0] /* billing */ &&
                        prev[1] === next[1] /* billingUsageResponse */ &&
                        prev[2] === next[2] /* billingSpendResponse */ &&
                        prev[3] === next[3] /* isAdminOrOwner */ &&
                        prev[4]?.autocapture_opt_out === next[4]?.autocapture_opt_out /* currentTeam */ &&
                        prev[5] === next[5] /* featureFlags */ &&
                        prev[6]?.length === next[6]?.length /* destinations */
                    )
                },
            },
        ],
    }),
])
