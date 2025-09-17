import equal from 'fast-deep-equal'
import { LogicWrapper } from 'kea'
import { routerType } from 'kea-router/lib/routerType'
import Papa from 'papaparse'

import { FEATURE_FLAGS, OrganizationMembershipLevel } from 'lib/constants'
import { dayjs } from 'lib/dayjs'
import { compactNumber, dateStringToDayJs } from 'lib/utils'
import { Params } from 'scenes/sceneTypes'

import { OrganizationType } from '~/types'
import { BillingPeriod, BillingProductV2AddonType, BillingProductV2Type, BillingTierType, BillingType } from '~/types'

import { USAGE_TYPES } from './constants'
import type { BillingFilters, BillingSeriesForCsv, BillingUsageInteractionProps, BuildBillingCsvOptions } from './types'
import { BillingGaugeItemKind, BillingGaugeItemType } from './types'

export const isProductVariantPrimary = (productType: string): boolean =>
    ['session_replay', 'realtime_destinations'].includes(productType)

export const isProductVariantSecondary = (productType: string): boolean =>
    ['mobile_replay', 'batch_exports'].includes(productType)

export const calculateFreeTier = (product: BillingProductV2Type | BillingProductV2AddonType): number =>
    (product.subscribed && product.tiered
        ? product.tiers?.[0]?.unit_amount_usd === '0'
            ? product.tiers?.[0]?.up_to
            : 0
        : product.free_allocation) || 0

export const createGaugeItems = (
    product: BillingProductV2Type | BillingProductV2AddonType,
    options: {
        billing?: BillingType | null
        billingLimitAsUsage?: number
    } = {}
): BillingGaugeItemType[] => {
    const freeTier = calculateFreeTier(product)

    return [
        // Billing limit (only for main products, excl. product variants setup)
        options.billingLimitAsUsage &&
        options.billing?.discount_percent !== 100 &&
        !isProductVariantPrimary(product.type)
            ? {
                  type: BillingGaugeItemKind.BillingLimit,
                  text: 'Billing limit',
                  value: options.billingLimitAsUsage || 0,
              }
            : undefined,

        // Free tier
        freeTier
            ? {
                  type: BillingGaugeItemKind.FreeTier,
                  text: 'Free tier limit',
                  value: freeTier,
              }
            : undefined,

        // Projected usage
        product.projected_usage && product.projected_usage > (product.current_usage || 0)
            ? {
                  type: BillingGaugeItemKind.ProjectedUsage,
                  text: 'Projected',
                  value: product.projected_usage || 0,
              }
            : undefined,

        // Current usage
        {
            type: BillingGaugeItemKind.CurrentUsage,
            text: 'Current',
            value: product.current_usage || 0,
        },
    ].filter(Boolean) as BillingGaugeItemType[]
}

export const summarizeUsage = (usage: number | null): string => {
    if (usage === null) {
        return ''
    }
    return compactNumber(usage)
}

export const projectUsage = (usage: number | undefined, period: BillingType['billing_period']): number | undefined => {
    if (typeof usage === 'undefined') {
        return usage
    }
    if (!period) {
        return usage
    }

    const timeSoFar = dayjs().diff(period.current_period_start, 'hours')

    // If less than 6 hours have passed, we don't have enough data to project
    if (timeSoFar <= 6) {
        return usage
    }
    const timeTotal = period.current_period_end.diff(period.current_period_start, 'hours')

    return Math.round((usage / timeSoFar) * timeTotal)
}

export const convertUsageToAmount = (
    usage: number,
    productAndAddonTiers: BillingTierType[][],
    percentDiscount?: number
): string => {
    if (!productAndAddonTiers) {
        return ''
    }
    let remainingUsage = usage
    let amount = 0
    let previousTier: BillingTierType | undefined = undefined

    const tiers = productAndAddonTiers[0].map((tier, index) => {
        const allAddonsTiers = productAndAddonTiers.slice(1)
        let totalAmount = parseFloat(tier.unit_amount_usd)
        let flatFee = parseFloat(tier.flat_amount_usd || '0')
        for (const addonTiers of allAddonsTiers) {
            totalAmount += parseFloat(addonTiers[index].unit_amount_usd)
            flatFee += parseFloat(addonTiers[index].flat_amount_usd || '0')
        }
        return {
            ...tier,
            unit_amount_usd: totalAmount.toString(),
            flat_amount_usd: flatFee.toString(),
        }
    })

    for (const tier of tiers) {
        if (remainingUsage <= 0) {
            break
        }

        const tierUsageMax = tier.up_to ? tier.up_to - (previousTier?.up_to || 0) : Infinity
        const amountFloatUsd = parseFloat(tier.unit_amount_usd)
        const tierFlatFee = parseFloat(tier.flat_amount_usd || '0')
        const usageThisTier = Math.min(remainingUsage, tierUsageMax)
        remainingUsage -= usageThisTier
        amount += amountFloatUsd * usageThisTier
        if (tierFlatFee) {
            amount += tierFlatFee
        }
        previousTier = tier
    }

    // remove discount from total price
    if (percentDiscount) {
        amount = amount * (1 - percentDiscount / 100)
    }

    return amount.toFixed(2)
}

export const convertAmountToUsage = (
    amount: string,
    productAndAddonTiers: BillingTierType[][],
    discountPercent?: number
): number => {
    if (!amount) {
        return 0
    }
    if (!productAndAddonTiers || productAndAddonTiers.length === 0) {
        return 0
    }

    const tiers = productAndAddonTiers[0].map((tier, index) => {
        const allAddonsTiers = productAndAddonTiers.slice(1)
        let totalAmount = parseFloat(tier.unit_amount_usd)
        let flatFee = parseFloat(tier.flat_amount_usd || '0')
        for (const addonTiers of allAddonsTiers) {
            totalAmount += parseFloat(addonTiers[index]?.unit_amount_usd || '0')
            flatFee += parseFloat(addonTiers[index]?.flat_amount_usd || '0')
        }
        return {
            ...tier,
            unit_amount_usd: totalAmount.toString(),
            flat_amount_usd: flatFee.toString(),
        }
    })

    let remainingAmount = parseFloat(amount)
    let usage = 0
    let previousTier: BillingTierType | undefined = undefined

    if (remainingAmount === 0) {
        if (parseFloat(tiers[0].unit_amount_usd) === 0) {
            return tiers[0].up_to || 0
        }
        return 0
    }

    // consider discounts so user knows what unit amount they'll be throttled at
    if (discountPercent) {
        remainingAmount = remainingAmount / (1 - discountPercent / 100)
    }

    const allTiersZero = tiers.every((tier) => !parseFloat(tier.unit_amount_usd))

    if (allTiersZero) {
        // Free plan - usage cannot be calculated
        return tiers[0].up_to || 0
    }

    for (const tier of tiers) {
        if (remainingAmount <= 0) {
            break
        }

        const tierUsageMax = tier.up_to ? tier.up_to - (previousTier?.up_to || 0) : Infinity
        const amountFloatUsd = parseFloat(tier.unit_amount_usd)
        const tierFlatFee = parseFloat(tier.flat_amount_usd || '0')
        const usageThisTier = Math.min(remainingAmount / amountFloatUsd, tierUsageMax)

        usage += usageThisTier
        remainingAmount -= amountFloatUsd * usageThisTier
        if (tierFlatFee) {
            remainingAmount -= tierFlatFee
        }
        previousTier = tier
    }

    return Math.round(usage)
}

export const getUpgradeProductLink = ({
    product,
    redirectPath,
}: {
    product?: BillingProductV2Type
    redirectPath?: string
}): string => {
    let url = '/api/billing/activate?'
    if (redirectPath) {
        url += `redirect_path=${encodeURIComponent(redirectPath)}&`
    }

    url += `products=all_products:`
    if (product && product.type) {
        url += `&intent_product=${product.type}`
    }

    return url
}

export const convertLargeNumberToWords = (
    // The number to convert
    num: number | null,
    // The previous tier's number
    previousNum: number | null,
    // Whether we will be showing multiple tiers (to denote the first tier with 'first')
    multipleTiers: boolean = false,
    // The product type (to denote the unit)
    productType: BillingProductV2Type['type'] | null = null
): string => {
    if (num === null && previousNum) {
        return `${convertLargeNumberToWords(previousNum, null)} +`
    }
    if (num === null) {
        return ''
    }

    let denominator = 1
    if (num >= 1000000) {
        denominator = 1000000
    } else if (num >= 1000) {
        denominator = 1000
    }

    let prevDenominator = 1
    if (previousNum && previousNum >= 1000000) {
        prevDenominator = 1000000
    } else if (previousNum && previousNum >= 1000) {
        prevDenominator = 1000
    }

    return `${previousNum ? `${((previousNum + 1) / prevDenominator).toFixed(0)}-` : multipleTiers ? 'First ' : ''}${(
        num / denominator
    ).toFixed(0)}${denominator === 1000000 ? ' million' : denominator === 1000 ? 'k' : ''}${
        !previousNum && multipleTiers ? ` ${productType}s/mo` : ''
    }`
}

export const getProration = ({
    timeRemainingInSeconds,
    timeTotalInSeconds,
    amountUsd,
    hasActiveSubscription,
}: {
    timeRemainingInSeconds: number
    timeTotalInSeconds: number
    amountUsd?: string | null
    hasActiveSubscription?: boolean
}): {
    isProrated: boolean
    prorationAmount: string
} => {
    if (timeTotalInSeconds === 0) {
        return {
            isProrated: false,
            prorationAmount: '0.00',
        }
    }

    const prorationAmount = amountUsd ? parseInt(amountUsd) * (timeRemainingInSeconds / timeTotalInSeconds) : 0

    return {
        isProrated: hasActiveSubscription && amountUsd ? prorationAmount !== parseInt(amountUsd || '') : false,
        prorationAmount: prorationAmount.toFixed(2),
    }
}

export const getProrationMessage = (prorationAmount: string, unitAmountUsd: string | null): string => {
    return `Pay ~$${prorationAmount} today (prorated) and $${parseInt(unitAmountUsd || '0')} every month thereafter.`
}

/**
 * Formats the plan status for display, trial or not
 */
export const formatPlanStatus = (billing: BillingType | null): string => {
    if (!billing) {
        return ''
    }

    // Check for old-style active trial
    if (billing.free_trial_until && billing.free_trial_until.isAfter(dayjs())) {
        return '(trial plan)'
    }

    // Check for new-style active trial
    if (billing.trial?.status === 'active') {
        return '(trial plan)'
    }

    // Check for expired trial
    if (billing.trial?.status === 'expired' && billing.trial.expires_at) {
        return `(trial expired)`
    }

    // Regular paid plan
    if (billing.subscription_level !== 'free') {
        return '(your plan)'
    }

    return ''
}

/**
 * Formats a number as a currency string
 */
export const currencyFormatter = (value: number): string => {
    return new Intl.NumberFormat('en-US', {
        style: 'currency',
        currency: 'USD',
    }).format(value)
}

/**
 * Determines if the user has sufficient permissions to read billing information based on their organization membership level.
 */
export function canAccessBilling(
    currentOrganization: Pick<OrganizationType, 'membership_level'> | null | undefined
): boolean {
    if (!currentOrganization || !currentOrganization.membership_level) {
        return false
    }
    return currentOrganization.membership_level >= OrganizationMembershipLevel.Admin
}

/**
 * Synchronizes URL search parameters with billing filter state.
 * Returns the appropriate router action format for kea-router.
 * Only updates the URL if parameters have actually changed.
 */
export function syncBillingSearchParams(
    router: LogicWrapper<routerType>,
    updateParams: (searchParams: Params) => Params
): [string, Params, Record<string, any>, { replace: boolean }] {
    const currentSearchParams = { ...router.values.searchParams }
    const updatedSearchParams = updateParams(currentSearchParams)
    if (!equal(updatedSearchParams, router.values.searchParams)) {
        return [router.values.location.pathname, updatedSearchParams, router.values.hashParams, { replace: true }]
    }
    return [router.values.location.pathname, router.values.searchParams, router.values.hashParams, { replace: false }]
}

/**
 * Updates a search parameter if the value differs from the default.
 * Removes the parameter entirely if it matches the default to keep URLs clean.
 */
export function updateBillingSearchParams<T>(searchParams: Params, key: string, value: T, defaultValue: T): void {
    if (!equal(value, defaultValue)) {
        searchParams[key] = value
    } else {
        delete searchParams[key]
    }
}

/**
 * Builds properties for billing usage and spend interaction events
 */
export function buildTrackingProperties(
    action: BillingUsageInteractionProps['action'],
    values: {
        filters: BillingFilters
        dateFrom: string
        dateTo: string
        excludeEmptySeries: boolean
        teamOptions: { key: string; label: string }[]
    }
): BillingUsageInteractionProps {
    return {
        action,
        filters: values.filters,
        date_from: values.dateFrom,
        date_to: values.dateTo,
        exclude_empty: values.excludeEmptySeries,
        usage_types_count: values.filters.usage_types?.length || 0,
        usage_types_total: USAGE_TYPES.length,
        teams_count: values.filters.team_ids?.length || 0,
        teams_total: values.teamOptions.length,
        has_team_breakdown: (values.filters.breakdowns || []).includes('team'),
        interval: values.filters.interval || 'day',
    }
}

export const isAddonVisible = (
    product: BillingProductV2Type,
    addon: BillingProductV2AddonType,
    featureFlags: Record<string, any>
): boolean => {
    // Filter out inclusion-only addons if personless events are not supported
    if (addon.inclusion_only && featureFlags[FEATURE_FLAGS.PERSONLESS_EVENTS_NOT_SUPPORTED]) {
        return false
    }

    // Filter out legacy addons for platform_and_support if not subscribed
    if (product.type === 'platform_and_support' && addon.legacy_product && !addon.subscribed) {
        return false
    }

    // Filter out addons that are hidden by feature flag
    const hideAddonFlag = `billing_hide_addon_${addon.type}`
    if (featureFlags[hideAddonFlag]) {
        return false
    }

    return true
}

/**
 * Calculate billing period markers for a given date range
 * @param billingPeriodUTC - The billing period with UTC dates (start, end, interval)
 * @param dateFrom - Start date string (can be relative like '30d' or absolute)
 * @param dateTo - End date string
 * @returns Array of billing period markers
 */
export function calculateBillingPeriodMarkers(
    billingPeriodUTC: BillingPeriod,
    dateFrom: string,
    dateTo: string
): Array<{ date: dayjs.Dayjs }> {
    if (!billingPeriodUTC?.start || !billingPeriodUTC?.interval) {
        return []
    }

    // Convert user dates to UTC for comparison with billingPeriodUTC
    const from = dateStringToDayJs(dateFrom)?.utc() || dayjs(dateFrom).utc()
    const to = dateStringToDayJs(dateTo)?.utc() || dayjs(dateTo).utc()
    const interval = billingPeriodUTC.interval

    // Find the first period start that could be visible
    const periodsSinceStart = Math.ceil(billingPeriodUTC.start.diff(from, interval))
    const firstVisiblePeriod = billingPeriodUTC.start.subtract(Math.max(0, periodsSinceStart), interval)

    // Collect all period starts within the range
    const markers = []
    let periodStart = firstVisiblePeriod

    while (periodStart.isSameOrBefore(to)) {
        if (periodStart.isSameOrAfter(from)) {
            markers.push({
                date: periodStart,
            })
        }
        periodStart = periodStart.add(1, interval)
    }

    return markers
}

const sumSeries = (values: number[]): number => values.reduce((sum, v) => sum + v, 0)

/**
 * Keep up to N decimals without trailing zeros.
 * Falls back to 10 decimals for very small numbers if not specified.
 */
export const formatWithDecimals = (value: number, decimals?: number): string => {
    const needsFixedFormat = typeof decimals === 'number' || (Math.abs(value) < 1e-6 && value !== 0)

    return needsFixedFormat
        ? value
              .toFixed(decimals ?? 10)
              .replace(/0+$/, '')
              .replace(/\.$/, '')
        : String(value)
}

/**
 * Build CSV from the billing usage and spend data:
 * - columns are [Series, Total, ...dates]
 * - rows are visible series (products and/or projects)
 * - sorted by total desc
 * Values can be clamped to N decimals via options.decimals.
 */
export function buildBillingCsv(params: {
    series: BillingSeriesForCsv[]
    dates: string[]
    hiddenSeries?: number[]
    options?: BuildBillingCsvOptions
}): string {
    const { series, dates, hiddenSeries = [], options } = params

    const visible = series.filter((s) => !hiddenSeries.includes(s.id))
    const withTotalSorted = visible.map((s) => ({ ...s, total: sumSeries(s.data) })).sort((a, b) => b.total - a.total)

    const header = ['Series', 'Total', ...dates]
    const rows = withTotalSorted.map((s) => [
        s.label,
        formatWithDecimals(s.total, options?.decimals),
        ...s.data.map((v) => formatWithDecimals(v, options?.decimals)),
    ])

    return Papa.unparse([header, ...rows])
}
