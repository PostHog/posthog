import { getDateRangeOverrideDisplay } from './InsightDetails'

describe('InsightDetails', () => {
    describe('getDateRangeOverrideDisplay', () => {
        it.each([
            {
                label: 'tile date beats dashboard date (replaced = dashboard)',
                insightDateRange: { date_from: '-14d' },
                filtersOverride: { date_from: '-30d' },
                tileFiltersOverride: { date_from: '-7d' },
                expected: {
                    source: 'tile',
                    dateFrom: '-7d',
                    dateTo: undefined,
                    replaced: { source: 'dashboard', dateFrom: '-30d', dateTo: undefined },
                },
            },
            {
                label: 'tile date beats the insight range when no dashboard date (replaced = insight)',
                insightDateRange: { date_from: '-14d' },
                filtersOverride: undefined,
                tileFiltersOverride: { date_from: '-7d' },
                expected: {
                    source: 'tile',
                    dateFrom: '-7d',
                    dateTo: undefined,
                    replaced: { source: 'insight', dateFrom: '-14d', dateTo: undefined },
                },
            },
            {
                label: 'dashboard date beats the insight range (replaced = insight)',
                insightDateRange: { date_from: '-14d' },
                filtersOverride: { date_from: '-30d' },
                tileFiltersOverride: undefined,
                expected: {
                    source: 'dashboard',
                    dateFrom: '-30d',
                    dateTo: undefined,
                    replaced: { source: 'insight', dateFrom: '-14d', dateTo: undefined },
                },
            },
            {
                label: 'no override when only the insight has a date',
                insightDateRange: { date_from: '-14d' },
                filtersOverride: undefined,
                tileFiltersOverride: undefined,
                expected: null,
            },
            {
                label: 'no replaced value when the overridden layers have no date',
                insightDateRange: undefined,
                filtersOverride: undefined,
                tileFiltersOverride: { date_from: '-7d' },
                expected: { source: 'tile', dateFrom: '-7d', dateTo: undefined, replaced: undefined },
            },
            {
                label: 'replaced dropped when identical to the winning range',
                insightDateRange: { date_from: '-7d' },
                filtersOverride: undefined,
                tileFiltersOverride: { date_from: '-7d' },
                expected: { source: 'tile', dateFrom: '-7d', dateTo: undefined, replaced: undefined },
            },
        ])('$label', ({ insightDateRange, filtersOverride, tileFiltersOverride, expected }) => {
            expect(getDateRangeOverrideDisplay(insightDateRange, filtersOverride, tileFiltersOverride, true)).toEqual(
                expected
            )
        })
    })
})
