import { shouldUpdatePlaybackPosition } from './snapshot-sync'

describe('shouldUpdatePlaybackPosition', () => {
    it.each([
        {
            name: 'first call (no previous update) → true',
            newTimestamp: 10000,
            lastUpdate: undefined,
            expected: true,
        },
        {
            name: 'just after last update (< 5s) → false',
            newTimestamp: 10000,
            lastUpdate: 9000,
            expected: false,
        },
        {
            name: 'exactly 5s after last update → false (not strictly greater)',
            newTimestamp: 15000,
            lastUpdate: 10000,
            expected: false,
        },
        {
            name: '5.001s after last update → true',
            newTimestamp: 15001,
            lastUpdate: 10000,
            expected: true,
        },
        {
            name: 'well after last update (30s) → true',
            newTimestamp: 40000,
            lastUpdate: 10000,
            expected: true,
        },
    ])('$name', ({ newTimestamp, lastUpdate, expected }) => {
        expect(shouldUpdatePlaybackPosition(newTimestamp, lastUpdate)).toBe(expected)
    })
})
