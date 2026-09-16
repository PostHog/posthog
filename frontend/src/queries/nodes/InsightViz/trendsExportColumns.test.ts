import { BreakdownFilter } from '~/queries/schema/schema-general'
import { TrendResult } from '~/types'

import { trendsExportColumns } from './trendsExportColumns'

const series = (result: Partial<TrendResult>): TrendResult =>
    ({ action: null, count: 0, data: [], days: [], label: 'Pageview', labels: [], ...result }) as TrendResult

describe('trendsExportColumns', () => {
    it('lists the series column and every date bucket once', () => {
        const results = [
            series({ data: [1, 2], labels: ['1-Jan-2026', '2-Jan-2026'] }),
            series({ data: [3, 4], labels: ['1-Jan-2026', '2-Jan-2026'] }),
        ]

        expect(trendsExportColumns(results)).toEqual(['series', '1-Jan-2026', '2-Jan-2026'])
    })

    it('names the breakdown column after the property it breaks down by', () => {
        const results = [series({ breakdown_value: 'Chrome', data: [1], labels: ['1-Jan-2026'] })]
        const breakdownFilter: BreakdownFilter = { breakdown: '$browser', breakdown_type: 'event' }

        expect(trendsExportColumns(results, breakdownFilter)).toEqual(['series', '$browser', '1-Jan-2026'])
    })

    it('takes the date labels from the current period when comparing', () => {
        // The previous-period series is indexed with an offset, so its own labels are the wrong ones.
        const results = [
            series({ compare_label: 'current' as TrendResult['compare_label'], data: [1], labels: ['1-Jan-2026'] }),
            series({ compare_label: 'previous' as TrendResult['compare_label'], data: [2], labels: ['1-Dec-2025'] }),
        ]

        expect(trendsExportColumns(results)).toEqual(['series', '1-Jan-2026'])
    })

    it('uses the total column when the insight aggregates to a single value', () => {
        const results = [series({ aggregated_value: 42, data: [], labels: [] })]

        expect(trendsExportColumns(results)).toEqual(['series', 'Total Sum'])
    })

    it('returns nothing when there are no results', () => {
        expect(trendsExportColumns([])).toEqual([])
    })
})
