import { BREAKDOWN_OTHER_STRING_LABEL } from 'scenes/insights/utils'

import { MarketingAnalyticsRetentionRow } from '~/queries/schema/schema-general'

import { SUMMARY_PERIODS, summarizeByBreakdown } from './summarizeByBreakdown'

const row = (
    breakdownValue: string,
    cohortIndex: number,
    cohortSize: number,
    /** One entry per period. `null` is a period the cohort has not finished living through. */
    counts: (number | null)[]
): MarketingAnalyticsRetentionRow => ({
    breakdownValue,
    cohortDate: '2026-08-02T00:00:00Z',
    cohortIndex,
    cohortSize,
    values: Array.from({ length: SUMMARY_PERIODS }, (_, period) => {
        const count = counts[period] ?? null
        return {
            count: count ?? 0,
            rate: count === null ? null : count / cohortSize,
            complete: count !== null,
        }
    }),
})

describe('summarizeByBreakdown', () => {
    it('weights each period by cohort size rather than averaging the cohorts', () => {
        // A 100-person cohort retaining 50% and a 900-person cohort retaining 10% is 14%, not the 30%
        // an unweighted average of the two cohort rates would report.
        const [summary] = summarizeByBreakdown([row('google', 0, 100, [100, 50]), row('google', 1, 900, [900, 90])])

        expect(summary.cells[1].returned).toBe(140)
        expect(summary.cells[1].eligible).toBe(1000)
        expect(summary.cells[1].rate).toBeCloseTo(0.14)
    })

    it('leaves cohorts that have not finished a period out of that period entirely', () => {
        // A zero from the unfinished cohort would deflate the column instead of being absent from it.
        const [summary] = summarizeByBreakdown([row('google', 0, 100, [100, 40]), row('google', 1, 100, [100, null])])

        expect(summary.cells[0].cohorts).toBe(2)
        expect(summary.cells[1].cohorts).toBe(1)
        expect(summary.cells[1].eligible).toBe(100)
        expect(summary.cells[1].rate).toBeCloseTo(0.4)
    })

    it('reports no rate for a period no cohort has reached', () => {
        const [summary] = summarizeByBreakdown([row('google', 0, 100, [100, null])])

        expect(summary.cells[2].rate).toBeNull()
        expect(summary.cells[2].cohorts).toBe(0)
    })

    it('ranks by how many people the value brought in', () => {
        const summary = summarizeByBreakdown([row('small', 0, 10, [10]), row('big', 0, 500, [500])])

        expect(summary.map((s) => s.breakdownValue)).toEqual(['big', 'small'])
        expect(summary[0].acquired).toBe(500)
    })

    it('leaves the folded "Other" row out of the ranking', () => {
        // Its 5000 would outrank every real channel, and it is a sum of the tail, not a channel.
        const summary = summarizeByBreakdown([
            row(BREAKDOWN_OTHER_STRING_LABEL, 0, 5000, [5000, 4000]),
            row('google', 0, 100, [100, 50]),
        ])

        expect(summary.map((s) => s.breakdownValue)).toEqual(['google'])
    })

    it('does not mutate the rows the per-cohort tables also render', () => {
        const source = [row('google', 0, 100, [100, 40])]

        summarizeByBreakdown(source)

        expect(source[0].cohortSize).toBe(100)
        expect(source[0].values[1].count).toBe(40)
    })
})
