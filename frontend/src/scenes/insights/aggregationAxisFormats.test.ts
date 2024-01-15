import { formatAggregationAxisValue } from 'scenes/insights/aggregationAxisFormat'

import { FilterType } from '~/types'

describe('formatAggregationAxisValue', () => {
    const formatTestcases = [
        { candidate: 34, filters: { aggregation_axis_format: 'duration' }, expected: '34s' },
        { candidate: 340, filters: { aggregation_axis_format: 'duration' }, expected: '5m 40s' },
        { candidate: 3940, filters: { aggregation_axis_format: 'duration' }, expected: '1h 5m 40s' },
        { candidate: 3.944, filters: { aggregation_axis_format: 'percentage' }, expected: '3.94%' },
        { candidate: 3.956, filters: { aggregation_axis_format: 'percentage' }, expected: '3.96%' },
        { candidate: 3940, filters: { aggregation_axis_format: 'percentage' }, expected: '3,940%' },
        { candidate: 34, filters: { aggregation_axis_format: 'numeric' }, expected: '34' },
        { candidate: 394, filters: { aggregation_axis_format: 'numeric' }, expected: '394' },
        { candidate: 3940, filters: { aggregation_axis_format: 'numeric' }, expected: '3,940' },
        { candidate: 3940, filters: {}, expected: '3,940' },
        { candidate: 3940, filters: { aggregation_axis_format: 'unexpected' }, expected: '3,940' },
        {
            candidate: 3940,
            filters: {
                aggregation_axis_format: 'numeric',
                aggregation_axis_prefix: '£',
                aggregation_axis_postfix: '💖',
            },
            expected: '£3,940💖',
        },
        {
            candidate: 3940,
            filters: {
                aggregationAxisFormat: 'numeric',
                aggregationAxisPrefix: '£',
                aggregationAxisPostfix: '💖',
            },
            expected: '£3,940💖',
        },
        { candidate: 0.8709423, filters: {}, expected: '0.87' },
        { candidate: 0.8709423, filters: { decimal_places: 2 }, expected: '0.87' },
        { candidate: 0.8709423, filters: { decimal_places: 3 }, expected: '0.871' },
        { candidate: 0.8709423, filters: { decimalPlaces: 3 }, expected: '0.871' },
        { candidate: 0.8709423, filters: { decimal_places: 9 }, expected: '0.8709423' },
        { candidate: 0.8709423, filters: { decimal_places: -1 }, expected: '0.87' }, // Fall back to default for unsupported values
    ]
    formatTestcases.forEach((testcase) => {
        it(`correctly formats "${testcase.candidate}" as ${testcase.expected} when filters are ${JSON.stringify(
            testcase.filters
        )}`, () => {
            expect(formatAggregationAxisValue(testcase.filters as Partial<FilterType>, testcase.candidate)).toEqual(
                testcase.expected
            )
        })
    })
})
