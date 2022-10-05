import { dayjs } from 'lib/dayjs'
import { BillingProductV2Type, BillingV2Type } from '~/types'

export const summarizeUsage = (usage: number | null): string => {
    if (usage === null) {
        return ''
    } else if (usage < 1000) {
        return `${usage} events`
    } else if (Math.round(usage / 1000) < 1000) {
        return `${Math.round(usage / 1000)} thousand`
    } else {
        return `${Math.round(usage / 1000000)} million`
    }
}

export const projectUsage = (
    usage: number | undefined,
    period: BillingV2Type['billing_period']
): number | undefined => {
    if (typeof usage === 'undefined') {
        return usage
    }
    if (!period) {
        return usage
    }

    const timeSoFar = dayjs().diff(period.current_period_start, 'hours')
    const timeTotal = period.current_period_end.diff(period.current_period_start, 'hours')

    return Math.round((usage / timeSoFar) * timeTotal)
}

export const convertUsageToAmount = (usage: number, tiers: BillingProductV2Type['tiers']): string => {
    return '100.00'
}

export const convertAmountToUsage = (amount: string, tiers: BillingProductV2Type['tiers']): number => {
    const amountFloat = parseFloat(amount)

    console.log({ amount })

    return amountFloat * 2100
}
