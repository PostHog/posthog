import { AnyResponseType } from '~/queries/schema/schema-general'
import { InsightShortId } from '~/types'

import { consumeFreshInsightResult, stashFreshInsightResult } from './freshInsightResults'

describe('freshInsightResults', () => {
    const shortId = 'abc123' as InsightShortId
    const otherShortId = 'def456' as InsightShortId
    const response = { results: [[1]], columns: ['count'] } as unknown as AnyResponseType

    it('returns undefined when nothing has been stashed', () => {
        expect(consumeFreshInsightResult(shortId)).toBeUndefined()
    })

    it('returns the stashed result for the matching short id', () => {
        stashFreshInsightResult(shortId, response)
        expect(consumeFreshInsightResult(shortId)).toBe(response)
    })

    it('consumes the result so a second read returns undefined (one-shot)', () => {
        stashFreshInsightResult(shortId, response)
        expect(consumeFreshInsightResult(shortId)).toBe(response)
        expect(consumeFreshInsightResult(shortId)).toBeUndefined()
    })

    it('keeps results for different insights independent', () => {
        const otherResponse = { results: [[2]], columns: ['count'] } as unknown as AnyResponseType
        stashFreshInsightResult(shortId, response)
        stashFreshInsightResult(otherShortId, otherResponse)
        expect(consumeFreshInsightResult(otherShortId)).toBe(otherResponse)
        expect(consumeFreshInsightResult(shortId)).toBe(response)
    })

    it('overwrites a previously stashed result for the same insight', () => {
        const newerResponse = { results: [[3]], columns: ['count'] } as unknown as AnyResponseType
        stashFreshInsightResult(shortId, response)
        stashFreshInsightResult(shortId, newerResponse)
        expect(consumeFreshInsightResult(shortId)).toBe(newerResponse)
    })
})
