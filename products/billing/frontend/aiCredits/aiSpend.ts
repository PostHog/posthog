import { getSeriesColor } from 'lib/colors'
import { Dayjs, dayjs } from 'lib/dayjs'

import type {
    AICreditHistoryResponseApi,
    AISpendDayApi,
    AISpendProductApi,
    AISpendResponseApi,
} from 'products/billing/frontend/generated/api.schemas'

// A year of billing periods, like billing's usage and spend ranges. The spend route allows one more
// period back, because the page compares each period with the one before it.
export const BILLING_PERIODS_SHOWN = 12

export interface BillingPeriodOption {
    periodsAgo: number
    label: string
}

export interface ChartedProduct extends AISpendProductApi {
    color: string
    /** This product's part of the period's spend, from 0 to 1. */
    share: number
}

export interface AISpendSummary {
    spendUsd: number
    periodStart: Dayjs
    /** The day the next period starts. */
    periodEnd: Dayjs
    dailyAverageUsd: number
    previousDailyAverageUsd: number | null
    /** The change in the daily average from the previous period, as a fraction. */
    changeFromPrevious: number | null
    busiestDay: { date: Dayjs; spendUsd: number } | null
    productsWithSpend: number
}

export type SpendLimitOutlook = { reached: true } | { reached: false; date: Dayjs | null }

function periodDays(spend: AISpendResponseApi): number {
    return dayjs.utc(spend.period_end).diff(dayjs.utc(spend.period_start), 'day')
}

function dayTotal(day: AISpendDayApi): number {
    return Object.values(day.spend_usd).reduce((sum, value) => sum + Number(value), 0)
}

export function summarizeSpend(
    spend: AISpendResponseApi,
    previous: AISpendResponseApi | null,
    now: Dayjs
): AISpendSummary {
    const periodStart = dayjs.utc(spend.period_start)
    const spendUsd = Number(spend.spend_usd)
    // A day counts once it has started, so the average doesn't jump at midnight.
    const daysSoFar = Math.min(Math.max(Math.ceil(now.diff(periodStart, 'day', true)), 1), periodDays(spend))
    const dailyAverageUsd = spendUsd / daysSoFar
    const previousDailyAverageUsd = previous ? Number(previous.spend_usd) / periodDays(previous) : null

    let busiestDay: AISpendSummary['busiestDay'] = null
    for (const day of spend.days) {
        const total = dayTotal(day)
        if (total > 0 && (!busiestDay || total > busiestDay.spendUsd)) {
            busiestDay = { date: dayjs.utc(day.date), spendUsd: total }
        }
    }

    return {
        spendUsd,
        periodStart,
        periodEnd: dayjs.utc(spend.period_end),
        dailyAverageUsd,
        previousDailyAverageUsd,
        changeFromPrevious: previousDailyAverageUsd
            ? (dailyAverageUsd - previousDailyAverageUsd) / previousDailyAverageUsd
            : null,
        busiestDay,
        productsWithSpend: spend.products.filter((product) => Number(product.spend_usd) > 0).length,
    }
}

/** When the period's spend reaches the limit at the current daily average. Null means it doesn't this period. */
export function spendLimitOutlook(summary: AISpendSummary, limitUsd: number, now: Dayjs): SpendLimitOutlook {
    if (summary.spendUsd >= limitUsd) {
        return { reached: true }
    }
    if (summary.dailyAverageUsd <= 0) {
        return { reached: false, date: null }
    }
    // dayjs rounds a fractional day, so the time to the limit goes in as milliseconds.
    const date = now.add(((limitUsd - summary.spendUsd) / summary.dailyAverageUsd) * 86_400_000, 'millisecond')
    return { reached: false, date: date.isBefore(summary.periodEnd) ? date : null }
}

/** Whole days the balance lasts at the current daily average, or null with no spend to go by. */
export function balanceRunwayDays(balanceUsd: number, dailyAverageUsd: number): number | null {
    return dailyAverageUsd > 0 && balanceUsd > 0 ? Math.floor(balanceUsd / dailyAverageUsd) : null
}

/** Products by spend, largest first, each with its chart color. */
export function chartedProducts(spend: AISpendResponseApi): ChartedProduct[] {
    const total = Number(spend.spend_usd)
    return [...spend.products]
        .sort((a, b) => Number(b.spend_usd) - Number(a.spend_usd))
        .map((product, index) => ({
            ...product,
            color: getSeriesColor(index),
            share: total > 0 ? Number(product.spend_usd) / total : 0,
        }))
}

/** Every day of the period, so the days still to come show as empty. */
export function periodDates(spend: AISpendResponseApi): string[] {
    const start = dayjs.utc(spend.period_start)
    return Array.from({ length: periodDays(spend) }, (_, index) => start.add(index, 'day').format('YYYY-MM-DD'))
}

/** The automatic reloads charged since the period started, or null when the loaded history may not reach back that far. */
export function reloadedSince(history: AICreditHistoryResponseApi | null, periodStart: string): number | null {
    if (!history) {
        return null
    }
    const start = dayjs.utc(periodStart)
    const oldest = history.results[history.results.length - 1]
    if (history.has_more && (!oldest || !dayjs(oldest.created_at).isBefore(start))) {
        return null
    }
    return history.results
        .filter((entry) => entry.kind === 'automatic_reload' && !dayjs(entry.created_at).isBefore(start))
        .reduce((sum, entry) => sum + Number(entry.amount_usd), 0)
}

function periodLabel(start: Dayjs, end: Dayjs): string {
    const last = end.subtract(1, 'day')
    const first = start.year() === last.year() ? start.format('MMM D') : start.format('MMM D, YYYY')
    return `${first} – ${last.format('MMM D, YYYY')}`
}

/**
 * The current billing period and the ones before it. Each bound counts back from the current start, as
 * the spend route does, so a period anchored on the 31st stays on the 31st.
 */
export function billingPeriodOptions(periodStart: string, periodEnd: string, count: number): BillingPeriodOption[] {
    const currentStart = dayjs.utc(periodStart)
    return Array.from({ length: count }, (_, periodsAgo) => ({
        periodsAgo,
        label: periodLabel(
            currentStart.subtract(periodsAgo, 'month'),
            periodsAgo === 0 ? dayjs.utc(periodEnd) : currentStart.subtract(periodsAgo - 1, 'month')
        ),
    }))
}
