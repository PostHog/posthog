import { AvailableFeature, BillingPlanType } from '~/types'

const MONTHS_PER_UNIT: Record<string, number> = { month: 1, months: 1, year: 12, years: 12 }

function eventsRetentionMonths(plan: BillingPlanType | null | undefined): number | null {
    const feature = plan?.features.find((feature) => feature.key === AvailableFeature.PRODUCT_ANALYTICS_DATA_RETENTION)
    const monthsPerUnit = feature?.unit ? MONTHS_PER_UNIT[feature.unit] : undefined
    return feature?.limit && monthsPerUnit ? feature.limit * monthsPerUnit : null
}

export function longestEventsRetentionMonths(plans: (BillingPlanType | null | undefined)[]): number | null {
    const months = plans.map(eventsRetentionMonths).filter((value): value is number => value !== null)
    return months.length ? Math.max(...months) : null
}
