import { MarketingAnalyticsRetentionRow } from '~/queries/schema/schema-general'

import { isFoldedBreakdownValue } from '../../logic/marketingBreakdown'

/** Periods the summary compares across. Past this the table stops being scannable at a glance, and the
 *  per-cohort panels below carry the full range anyway. */
export const SUMMARY_PERIODS = 5

export interface SummaryCell {
    /** People from the eligible cohorts who came back in this period. */
    returned: number
    /**
     * People who could have. Only cohorts that fully lived through this period count, so a cohort that
     * has not reached it yet cannot deflate the column with a zero.
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
 * Rates are weighted by cohort size rather than averaged across cohorts, so a week that acquired 50
 * people cannot swing a column as hard as one that acquired 5,000.
 *
 * The folded "Other" row is left out, because it is a sum of the long tail rather than a channel, so
 * ranking it against real channels floats a row nobody can act on above them. The per-cohort panels
 * still show it.
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
