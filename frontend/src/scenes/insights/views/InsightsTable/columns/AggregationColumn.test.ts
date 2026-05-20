import { IndexedTrendResult } from 'scenes/trends/types'

import { getAggregatedValue } from './AggregationColumn'

describe('getAggregatedValue', () => {
    it.each(['average', 'median'] as const)(
        'returns undefined for %s when data is null (regression: formula rows pre-fix crashed)',
        (aggregation) => {
            const item = { data: null, count: 0, aggregated_value: 0 } as unknown as IndexedTrendResult
            expect(getAggregatedValue(item, aggregation, false)).toBeUndefined()
        }
    )
})
