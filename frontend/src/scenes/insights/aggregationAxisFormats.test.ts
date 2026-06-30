import {
    AggregationAxisFormat,
    defaultAggregationAxisFormatForDisplay,
    formatAggregationAxisValue,
    formatAggregationAxisValueWithShareOfTotal,
} from 'scenes/insights/aggregationAxisFormat'

import { CurrencyCode } from '~/queries/schema/schema-general'
import { ChartDisplayType, FilterType } from '~/types'

describe('formatAggregationAxisValue', () => {
    const formatTestcases = [
        { candidate: 34, filters: { aggregation_axis_format: 'duration' }, expected: '34s' },
        { candidate: 340, filters: { aggregation_axis_format: 'duration' }, expected: '5m 40s' },
        { candidate: 3940, filters: { aggregation_axis_format: 'duration' }, expected: '1h 5m 40s' },
        { candidate: 3.944, filters: { aggregation_axis_format: 'percentage' }, expected: '3.94%' },
        { candidate: 3.956, filters: { aggregation_axis_format: 'percentage' }, expected: '3.96%' },
        { candidate: 3940, filters: { aggregation_axis_format: 'percentage' }, expected: '3,940%' },
        { candidate: 2.5341, filters: { aggregation_axis_format: 'percentage', decimalPlaces: 3 }, expected: '2.534%' },
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
        {
            candidate: 3940,
            filters: { aggregation_axis_format: 'currency' },
            expected: '$3,940.00',
        },
        {
            candidate: 3940,
            filters: { aggregation_axis_format: 'currency' },
            currency: 'EUR' as CurrencyCode,
            expected: '€3,940.00',
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
            expect(
                formatAggregationAxisValue(
                    testcase.filters as Partial<FilterType>,
                    testcase.candidate,
                    testcase.currency
                )
            ).toEqual(testcase.expected)
        })
    })
})

describe('defaultAggregationAxisFormatForDisplay', () => {
    const cases: { display: ChartDisplayType; expected: AggregationAxisFormat | undefined }[] = [
        { display: ChartDisplayType.Metric, expected: 'short' },
        { display: ChartDisplayType.BoldNumber, expected: undefined },
        { display: ChartDisplayType.ActionsLineGraph, expected: undefined },
        { display: ChartDisplayType.ActionsPie, expected: undefined },
    ]

    cases.forEach(({ display, expected }) => {
        it(`returns ${String(expected)} for ${display}`, () => {
            expect(defaultAggregationAxisFormatForDisplay(display)).toEqual(expected)
        })
    })

    it('returns undefined when no display is set', () => {
        expect(defaultAggregationAxisFormatForDisplay(null)).toBeUndefined()
        expect(defaultAggregationAxisFormatForDisplay(undefined)).toBeUndefined()
    })
})

describe('formatAggregationAxisValueWithShareOfTotal', () => {
    const shareTestcases = [
        { candidate: 250, total: 1000, filters: {}, expected: '250 (25%)' },
        { candidate: 333, total: 1000, filters: {}, expected: '333 (33.3%)' },
        { candidate: 1000, total: 1000, filters: {}, expected: '1,000 (100%)' },
        {
            candidate: 250,
            total: 1000,
            filters: { aggregation_axis_format: 'numeric' },
            expected: '250 (25%)',
        },
        {
            candidate: 250,
            total: 1000,
            filters: { aggregation_axis_format: 'currency' },
            expected: '$250.00 (25%)',
        },
        {
            candidate: 60,
            total: 100,
            filters: { aggregation_axis_format: 'duration' },
            expected: '1m (60%)',
        },
        // Percentage axis formats already render a % suffix, so we skip share-of-total to avoid "37% (60%)".
        {
            candidate: 37,
            total: 100,
            filters: { aggregation_axis_format: 'percentage' },
            expected: '37%',
        },
        {
            candidate: 0.37,
            total: 1,
            filters: { aggregation_axis_format: 'percentage_scaled' },
            expected: '37%',
        },
        {
            candidate: 37,
            total: 100,
            filters: { aggregationAxisFormat: 'percentage' },
            expected: '37%',
        },
        // When total is zero (or otherwise falsy), skip the share-of-total to avoid "NaN%".
        { candidate: 0, total: 0, filters: {}, expected: '0' },
        { candidate: 0, total: 0, filters: { aggregation_axis_format: 'currency' }, expected: '$0.00' },
    ]

    shareTestcases.forEach((testcase) => {
        it(`correctly formats "${testcase.candidate}" of total ${testcase.total} as ${
            testcase.expected
        } when filters are ${JSON.stringify(testcase.filters)}`, () => {
            expect(
                formatAggregationAxisValueWithShareOfTotal(
                    testcase.filters as Partial<FilterType>,
                    testcase.candidate,
                    testcase.total
                )
            ).toEqual(testcase.expected)
        })
    })
})
