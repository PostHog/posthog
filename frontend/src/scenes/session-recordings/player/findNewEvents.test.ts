import { EventType } from '@posthog/rrweb-types'
import type { eventWithTime } from '@posthog/rrweb-types'

import { findNewEvents } from './sessionRecordingPlayerLogic'

function evt(timestamp: number): eventWithTime {
    return { timestamp, type: EventType.IncrementalSnapshot, data: {} } as unknown as eventWithTime
}

describe('findNewEvents', () => {
    it.each([
        {
            name: 'both empty',
            all: [],
            current: [],
            expected: [],
        },
        {
            name: 'all empty, current has events',
            all: [],
            current: [evt(100)],
            expected: [],
        },
        {
            name: 'current empty returns all events',
            all: [evt(100), evt(200)],
            current: [],
            expected: [100, 200],
        },
        {
            name: 'identical lists returns empty',
            all: [evt(100), evt(200)],
            current: [evt(100), evt(200)],
            expected: [],
        },
        {
            name: 'new events at the end',
            all: [evt(100), evt(200), evt(300)],
            current: [evt(100), evt(200)],
            expected: [300],
        },
        {
            name: 'new events at the beginning',
            all: [evt(50), evt(100), evt(200)],
            current: [evt(100), evt(200)],
            expected: [50],
        },
        {
            name: 'new events interspersed',
            all: [evt(100), evt(150), evt(200), evt(250)],
            current: [evt(100), evt(200)],
            expected: [150, 250],
        },
        {
            name: 'duplicate timestamps — counts are tracked',
            all: [evt(100), evt(100), evt(100)],
            current: [evt(100), evt(100)],
            expected: [100],
        },
        {
            name: 'duplicate timestamps — all already present',
            all: [evt(100), evt(100)],
            current: [evt(100), evt(100), evt(100)],
            expected: [],
        },
        {
            name: 'events removed from current (e.g. after seek reset)',
            all: [evt(100), evt(200), evt(300)],
            current: [evt(100)],
            expected: [200, 300],
        },
        {
            name: 'current has events not in all (stale events after seek)',
            all: [evt(200), evt(300)],
            current: [evt(100), evt(200)],
            expected: [300],
        },
    ])('$name', ({ all, current, expected }) => {
        const result = findNewEvents(all, current)
        expect(result.map((e) => e.timestamp)).toEqual(expected)
    })
})
