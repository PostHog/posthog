import { NodeKind } from '~/queries/schema/schema-general'
import { initKeaTests } from '~/test/init'

import {
    MAX_RETAINED_RESPONSE_LENGTH,
    getInflightResponse,
    getRetainedResponse,
    reclaimReleasedQuery,
    responseCacheKey,
    retainResponse,
    trackInflightResponse,
} from './responseCache'

beforeEach(() => initKeaTests())

test('isolates retained results by user and project and clones mutable data', () => {
    const props = {
        key: 'example',
        query: { kind: NodeKind.HogQLQuery, query: 'SELECT 1' },
        retainResponseOnUnmount: true,
    }
    const key = responseCacheKey(props, 1, 1)!
    const response = { results: [[1]] }
    retainResponse(key, response)
    response.results[0][0] = 2
    expect(getRetainedResponse(key)).toEqual({ results: [[1]] })
    expect(getRetainedResponse(responseCacheKey(props, 2, 1))).toBeNull()
    expect(getRetainedResponse(responseCacheKey(props, 1, 2))).toBeNull()
    expect(getRetainedResponse(responseCacheKey(props, undefined, 1))).toBeNull()
})

test.each([
    { result: null },
    { results: [], query_status: { complete: false } },
    { results: [], error: 'failed' },
    { results: ['x'.repeat(MAX_RETAINED_RESPONSE_LENGTH)] },
])('does not retain unusable or oversized results: %p', (response) => {
    retainResponse('example', response)
    expect(getRetainedResponse('example')).toBeNull()
})

test('reclaims the oldest released query first, and never one a node still uses', () => {
    const abandoned: string[] = []
    const track = (key: string): ReturnType<typeof trackInflightResponse> =>
        trackInflightResponse(key, new Promise(() => {}), {
            queryId: key,
            abort: () => {},
            abandon: () => abandoned.push(key),
        })
    const inUse = track('in use')
    const older = track('older')
    const newer = track('newer')
    older.release()
    newer.release()
    inUse.release()
    inUse.adopt()

    expect(reclaimReleasedQuery()).toBe(true)
    expect(reclaimReleasedQuery()).toBe(true)
    expect(reclaimReleasedQuery()).toBe(false)
    expect(abandoned).toEqual(['older', 'newer'])
    expect(getInflightResponse('in use')).toBe(inUse)
    expect(getInflightResponse('older')).toBeNull()
})
