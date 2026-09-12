import { MarketingAnalyticsRetentionRow } from '~/queries/schema/schema-general'

import { isFoldedBreakdownValue } from '../../logic/marketingBreakdown'

export const SUMMARY_PERIODS = 5

export interface SummaryCell {
    returned: number
    /** Only cohorts that fully lived through this period, so an unfinished one can't deflate it. */
    eligible: number
    rate: number | null
    cohorts: number
}

export interface SummaryRow {
    breakdownValue: string
    acquired: number
    /** Always SUMMARY_PERIODS long. */
    cells: SummaryCell[]
}

/**
 * Rates are weighted by cohort size, so a week that acquired 50 people cannot swing a column as hard
 * as one that acquired 5,000. The folded "Other" row is left out: it is a sum of the long tail, so
 * ranking it against real channels floats a row nobody can act on above them.
 */
export function summarizeByBreakdown(rows: MarketingAnalyticsRetentionRow[]): SummaryRow[] {
    const byValue = new Map<string, SummaryRow>()

    for (const row of rows) {
        if (isFoldedBreakdownValue(row.breakdownValue)) {
            continue
        }
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
