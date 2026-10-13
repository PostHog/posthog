import { NodeKind } from '~/queries/schema/schema-general'
import { initKeaTests } from '~/test/init'

import { getRetainedResponse, responseCacheKey, retainResponse } from './responseCache'

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
    { results: ['x'.repeat(200_001)] },
])('does not retain unusable or oversized results: %p', (response) => {
    retainResponse('example', response)
    expect(getRetainedResponse('example')).toBeNull()
})

test('evicts the least recently used result when capacity is reached', () => {
    for (let index = 0; index < 100; index++) {
        retainResponse(String(index), { results: [index] })
    }
    getRetainedResponse('0')
    retainResponse('next', { results: [] })
    expect(getRetainedResponse('0')).toEqual({ results: [0] })
    expect(getRetainedResponse('1')).toBeNull()
})
