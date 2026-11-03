import type { TraceSearchMatchApi, TraceSearchResultsApi } from '../../../generated/api.schemas'
import { steppedMatchId, toMatchingNodeIds, toSearchBox } from './toSearch'

const MATCHES: TraceSearchMatchApi[] = [
    { nodeId: 'trace-1', count: 2 },
    { nodeId: 'gen-1', count: 4 },
    { nodeId: 'gen-2', count: 1 },
]
const RESULTS: TraceSearchResultsApi = { total: 7, matches: MATCHES }

describe('toSearch', () => {
    test.each([
        ['next from a match', 'gen-1', 'next', 'gen-2'],
        ['next wraps', 'gen-2', 'next', 'trace-1'],
        ['previous wraps', 'trace-1', 'previous', 'gen-2'],
        ['next from a non-match', 'span-1', 'next', 'trace-1'],
        ['previous from a non-match', 'span-1', 'previous', 'gen-2'],
    ] as const)('steppedMatchId %s', (_, selected, direction, expected) => {
        expect(steppedMatchId(MATCHES, selected, direction)).toBe(expected)
    })

    test('steppedMatchId with no matches is null', () => {
        expect(steppedMatchId([], 'gen-1', 'next')).toBeNull()
    })

    test.each([
        ['the selected match', 'gen-1', 2],
        ['a step without a match', 'span-1', null],
    ])('toSearchBox places %s', (_, selected, position) => {
        expect(toSearchBox('invoice', 'ready', RESULTS, null, selected)).toEqual({
            query: 'invoice',
            status: 'ready',
            total: 7,
            matchingSteps: 3,
            position,
            failure: null,
        })
    })

    test('toMatchingNodeIds fades nothing without results', () => {
        expect(toMatchingNodeIds(null)).toBeNull()
        expect(toMatchingNodeIds(RESULTS)).toEqual(new Set(['trace-1', 'gen-1', 'gen-2']))
    })
})
