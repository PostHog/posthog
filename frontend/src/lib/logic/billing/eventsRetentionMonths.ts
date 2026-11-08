import { AvailableFeature, BillingFeatureType, BillingPlanType } from '~/types'

const MONTHS_PER_UNIT: Record<string, number> = { month: 1, months: 1, year: 12, years: 12 }

export function eventsRetentionMonths(features: BillingFeatureType[] | null | undefined): number | null {
    const feature = features?.find((feature) => feature.key === AvailableFeature.PRODUCT_ANALYTICS_DATA_RETENTION)
    const monthsPerUnit = feature?.unit ? MONTHS_PER_UNIT[feature.unit] : undefined
    return feature?.limit && monthsPerUnit ? feature.limit * monthsPerUnit : null
}

export function keepsEventsRetentionMonths(
    currentPlan: BillingPlanType | null | undefined,
    targetPlan: BillingPlanType | null | undefined
): boolean {
    const months = eventsRetentionMonths(currentPlan?.features)
    return months !== null && months === eventsRetentionMonths(targetPlan?.features)
}

export function longestEventsRetentionMonths(plans: (BillingPlanType | null | undefined)[]): number | null {
    const months = plans
        .map((plan) => eventsRetentionMonths(plan?.features))
        .filter((value): value is number => value !== null)
    return months.length ? Math.max(...months) : null
}
