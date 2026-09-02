import { MarketingAnalyticsRetentionRow } from '~/queries/schema/schema-general'

import { baselineRows } from './RetentionCohortTable'

const row = (
    breakdownValue: string,
    cohortIndex: number,
    cohortSize: number,
    counts: number[]
): MarketingAnalyticsRetentionRow => ({
    breakdownValue,
    cohortDate: '2023-01-04T00:00:00Z',
    cohortIndex,
    cohortSize,
    values: counts.map((count) => ({ count, rate: count / cohortSize, complete: true })),
})

describe('baselineRows', () => {
    it('weights the combined rate by cohort size instead of averaging the channels', () => {
        // A channel with 10 people retaining 100% and one with 1000 retaining 10% is a 10.9% baseline,
        // not the 55% an average of the two rates would report.
        const combined = baselineRows([row('small', 0, 10, [10]), row('big', 0, 1000, [100])])

        expect(combined).toHaveLength(1)
        expect(combined[0].cohortSize).toBe(1010)
        expect(combined[0].values[0].count).toBe(110)
        expect(combined[0].values[0].rate).toBeCloseTo(110 / 1010)
    })

    it('keeps cohorts apart while merging the channels within each one', () => {
        const combined = baselineRows([
            row('google', 0, 5, [5, 2]),
            row('bing', 0, 5, [5, 4]),
            row('google', 1, 8, [8, 1]),
        ])

        expect(combined.map((r) => [r.cohortIndex, r.cohortSize])).toEqual([
            [0, 10],
            [1, 8],
        ])
        expect(combined[0].values[1].count).toBe(6)
    })

    it('does not mutate the rows it was handed', () => {
        // The same array backs the per-channel tables rendered next to the baseline, so merging in
        // place would silently double the counts they show.
        const source = [row('google', 0, 5, [5, 2]), row('bing', 0, 5, [5, 4])]

        baselineRows(source)

        expect(source[0].cohortSize).toBe(5)
        expect(source[0].values[1].count).toBe(2)
    })
})
