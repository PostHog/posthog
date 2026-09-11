import { scene } from './Group'

describe('Group scene', () => {
    // A group key with a stray `%` (e.g. `50%off`) makes decodeURIComponent throw
    // `URIError: URI malformed`; paramsToProps must fall back to the raw key so the
    // scene still renders instead of hard-crashing.
    it.each<[string, string]>([
        ['50%25off', '50%off'], // valid encoding is decoded
        ['50%off', '50%off'], // malformed `%` falls back to the raw key
        ['foo bar', 'foo bar'], // whitespace passes through untouched
    ])('paramsToProps turns raw groupKey %s into groupKey %s without throwing', (rawGroupKey, expected) => {
        expect(
            scene.paramsToProps?.({
                params: { groupTypeIndex: '0', groupKey: rawGroupKey },
                searchParams: {},
                hashParams: {},
            })
        ).toEqual({
            groupTypeIndex: 0,
            groupKey: expected,
        })
    })
})
