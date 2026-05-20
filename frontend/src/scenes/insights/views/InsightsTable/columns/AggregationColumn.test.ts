import { IndexedTrendResult } from 'scenes/trends/types'

import { getAggregatedValue } from './AggregationColumn'

describe('getAggregatedValue', () => {
    it('returns undefined when data is null on a time-series row (regression: formula rows pre-fix crashed in average/median)', () => {
        const item = { data: null, count: 0, aggregated_value: 0 } as unknown as IndexedTrendResult
        expect(getAggregatedValue(item, 'average', false)).toBeUndefined()
        expect(getAggregatedValue(item, 'median', false)).toBeUndefined()
    })
})
