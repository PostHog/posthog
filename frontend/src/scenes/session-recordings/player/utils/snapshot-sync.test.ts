import { EventType } from '@posthog/rrweb-types'
import type { eventWithTime } from '@posthog/rrweb-types'

import { selectNewEvents, shouldUpdatePlaybackPosition } from './snapshot-sync'

function evt(timestamp: number): eventWithTime {
    return { timestamp, type: EventType.IncrementalSnapshot, data: {} } as unknown as eventWithTime
}

describe('selectNewEvents', () => {
    describe('legacy path (index-based slice)', () => {
        it('returns events appended after current', () => {
            const all = [evt(100), evt(200), evt(300)]
            const current = [evt(100), evt(200)]
            const result = selectNewEvents(all, current, false)
            expect(result.map((e) => e.timestamp)).toEqual([300])
        })
    })

    describe('store path (timestamp-based diffing)', () => {
        it('finds events inserted before existing ones (out-of-order loading)', () => {
            // Source at minute 30 loaded first, then source at minute 5 loaded
            const all = [evt(50), evt(100), evt(200)]
            const current = [evt(100), evt(200)]
            const result = selectNewEvents(all, current, true)
            expect(result.map((e) => e.timestamp)).toEqual([50])
        })

        it('finds events interspersed with existing ones', () => {
            const all = [evt(100), evt(150), evt(200), evt(250)]
            const current = [evt(100), evt(200)]
            const result = selectNewEvents(all, current, true)
            expect(result.map((e) => e.timestamp)).toEqual([150, 250])
        })
    })

    describe('edge cases', () => {
        it.each([
            {
                name: 'empty allSnapshots → empty result',
                all: [] as eventWithTime[],
                current: [evt(100)],
                useStore: false,
            },
            {
                name: 'empty currentEvents → returns all',
                all: [evt(100), evt(200)],
                current: [] as eventWithTime[],
                useStore: false,
            },
            {
                name: 'both empty → empty result',
                all: [] as eventWithTime[],
                current: [] as eventWithTime[],
                useStore: false,
            },
            {
                name: 'store path: empty allSnapshots → empty result',
                all: [] as eventWithTime[],
                current: [evt(100)],
                useStore: true,
            },
            {
                name: 'store path: empty currentEvents → returns all',
                all: [evt(100), evt(200)],
                current: [] as eventWithTime[],
                useStore: true,
            },
        ])('$name', ({ all, current, useStore }) => {
            const result = selectNewEvents(all, current, useStore)
            if (all.length === 0) {
                expect(result).toEqual([])
            } else if (current.length === 0) {
                expect(result.map((e) => e.timestamp)).toEqual(all.map((e) => e.timestamp))
            }
        })
    })

    describe('legacy path breaks with out-of-order loading', () => {
        it('slice misses events prepended before existing ones', () => {
            // This is WHY the store path needs findNewEvents
            const all = [evt(50), evt(100), evt(200)]
            const current = [evt(100), evt(200)]

            const legacyResult = selectNewEvents(all, current, false)
            const storeResult = selectNewEvents(all, current, true)

            // Legacy: slice(2) = [evt(200)] — WRONG, misses evt(50) and duplicates evt(200)
            expect(legacyResult.map((e) => e.timestamp)).toEqual([200])
            // Store: correctly finds only evt(50)
            expect(storeResult.map((e) => e.timestamp)).toEqual([50])
        })
    })
})

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
