import { MarketingAnalyticsRetentionRow } from '~/queries/schema/schema-general'

/** Periods the summary compares across. Past this the table stops being scannable at a glance, and the
 *  later columns rest on a single cohort anyway. The per-cohort panels below carry the full range. */
export const SUMMARY_PERIODS = 5

export interface SummaryCell {
    /** People from the eligible cohorts who came back in this period. */
    returned: number
    /**
     * People who could have. Only cohorts that fully lived through this period count, so this shrinks
     * as the period index grows and later columns rest on fewer, older cohorts.
     */
    eligible: number
    /** returned / eligible. Null when no cohort has lived through this period yet. */
    rate: number | null
    /** How many cohorts fed this cell, so the table can say what each column rests on. */
    cohorts: number
}

export interface SummaryRow {
    breakdownValue: string
    /** Everyone acquired under this value, across every cohort. */
    acquired: number
    /** One per period, always SUMMARY_PERIODS long. */
    cells: SummaryCell[]
}

/**
 * One row per breakdown value: how each channel retains, with the cohorts collapsed.
 *
 * The per-cohort panels answer "how is this channel doing over time". This answers the question a
 * marketer actually opens the tab with, which is "which channel should I put money into", and that one
 * needs the channels side by side rather than in separate collapsed panels.
 *
 * Rates are weighted by cohort size rather than averaged across cohorts: a week that acquired 50 people
 * must not swing the number as hard as one that acquired 5,000.
 *
 * Only cells the cohort has fully lived through are counted. Including the rest would quietly deflate
 * every column, because a cohort that has not reached period 3 yet would otherwise contribute a zero to
 * it. The cost is that each column has its own denominator, which is why `eligible` and `cohorts` come
 * back with the rate instead of being dropped.
 */
export function summarizeByBreakdown(rows: MarketingAnalyticsRetentionRow[]): SummaryRow[] {
    const byValue = new Map<string, SummaryRow>()

    for (const row of rows) {
        let summary = byValue.get(row.breakdownValue)
        if (!summary) {
            summary = {
                breakdownValue: row.breakdownValue,
                acquired: 0,
                cells: Array.from({ length: SUMMARY_PERIODS }, () => ({
                    returned: 0,
                    eligible: 0,
                    rate: null,
                    cohorts: 0,
                })),
            }
            byValue.set(row.breakdownValue, summary)
        }

        summary.acquired += row.cohortSize
        row.values.slice(0, SUMMARY_PERIODS).forEach((cell, period) => {
            if (!cell.complete) {
                return
            }
            const into = summary.cells[period]
            into.returned += cell.count
            into.eligible += row.cohortSize
            into.cohorts += 1
        })
    }

    return [...byValue.values()]
        .map((summary) => ({
            ...summary,
            cells: summary.cells.map((cell) => ({
                ...cell,
                rate: cell.eligible ? cell.returned / cell.eligible : null,
            })),
        }))
        .sort((a, b) => b.acquired - a.acquired)
}
