import { formatAggregationAxisValue } from 'scenes/insights/aggregationAxisFormat'
import { TrendsFilter } from '~/queries/schema'

describe('formatAggregationAxisValue', () => {
    const formatTestcases: { candidate: number; filters: TrendsFilter; expected: string }[] = [
        { candidate: 34, filters: { aggregationAxisFormat: 'duration' }, expected: '34s' },
        { candidate: 340, filters: { aggregationAxisFormat: 'duration' }, expected: '5m 40s' },
        { candidate: 3940, filters: { aggregationAxisFormat: 'duration' }, expected: '1h 5m 40s' },
        { candidate: 3.944, filters: { aggregationAxisFormat: 'percentage' }, expected: '3.94%' },
        { candidate: 3.956, filters: { aggregationAxisFormat: 'percentage' }, expected: '3.96%' },
        { candidate: 3940, filters: { aggregationAxisFormat: 'percentage' }, expected: '3,940%' },
        { candidate: 34, filters: { aggregationAxisFormat: 'numeric' }, expected: '34' },
        { candidate: 394, filters: { aggregationAxisFormat: 'numeric' }, expected: '394' },
        { candidate: 3940, filters: { aggregationAxisFormat: 'numeric' }, expected: '3,940' },
        { candidate: 3940, filters: {}, expected: '3,940' },
        // @ts-expect-error
        { candidate: 3940, filters: { aggregationAxisFormat: 'unexpected' }, expected: '3,940' },
        {
            candidate: 3940,
            filters: {
                aggregationAxisFormat: 'numeric',
                aggregationAxisPrefix: '£',
                aggregationAxisPostfix: '💖',
            },
            expected: '£3,940💖',
        },
    ]
    formatTestcases.forEach((testcase) => {
        it(`correctly formats "${testcase.candidate}" as ${testcase.expected} when filters are ${testcase.filters}`, () => {
            expect(formatAggregationAxisValue(testcase.filters, testcase.candidate)).toEqual(testcase.expected)
        })
    })
})
