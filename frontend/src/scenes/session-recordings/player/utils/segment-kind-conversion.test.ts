import { SnapshotStore } from '@posthog/replay-shared'

import { RecordingSegment, SessionRecordingSnapshotSource } from '~/types'

import { convertSegmentKinds } from './segment-kind-conversion'

function makeSources(count: number): SessionRecordingSnapshotSource[] {
    return Array.from({ length: count }, (_, i) => ({
        source: 'blob_v2' as const,
        blob_key: String(i),
        start_timestamp: new Date(Date.UTC(2023, 7, 11, 12, i, 0)).toISOString(),
        end_timestamp: new Date(Date.UTC(2023, 7, 11, 12, i + 1, 0)).toISOString(),
    }))
}

function tsForMinute(minute: number): number {
    return new Date(Date.UTC(2023, 7, 11, 12, minute, 30)).getTime()
}

function makeSegment(overrides: Partial<RecordingSegment> & Pick<RecordingSegment, 'kind'>): RecordingSegment {
    return {
        startTimestamp: tsForMinute(5),
        endTimestamp: tsForMinute(10),
        durationMs: tsForMinute(10) - tsForMinute(5),
        isActive: false,
        ...overrides,
    }
}

function storeWithSources(count: number, loadedIndices: number[] = []): SnapshotStore {
    const store = new SnapshotStore()
    store.setSources(makeSources(count))
    for (const i of loadedIndices) {
        store.markLoaded(i, [])
    }
    return store
}

function allLoaded(count: number): number[] {
    return Array.from({ length: count }, (_, i) => i)
}

describe('convertSegmentKinds', () => {
    it.each([
        {
            name: 'buffer + all sources loaded → gap (true inactivity)',
            segment: makeSegment({ kind: 'buffer' }),
            store: storeWithSources(20, allLoaded(20)),
            isLoading: false,
            expectedKind: 'gap',
            expectedIsLoading: undefined,
        },
        {
            name: 'buffer + some sources unloaded → buffer with isLoading',
            segment: makeSegment({ kind: 'buffer' }),
            store: storeWithSources(20, [0, 1, 2]),
            isLoading: true,
            expectedKind: 'buffer',
            expectedIsLoading: true,
        },
        {
            name: 'buffer + store has 0 sources (early load) → buffer with isLoading',
            segment: makeSegment({ kind: 'buffer' }),
            store: new SnapshotStore(),
            isLoading: false,
            expectedKind: 'buffer',
            expectedIsLoading: false,
        },
        {
            name: 'gap + some sources unloaded → buffer (the seek-back bug fix)',
            segment: makeSegment({ kind: 'gap' }),
            store: storeWithSources(20, [0, 1, 2]),
            isLoading: true,
            expectedKind: 'buffer',
            expectedIsLoading: true,
        },
        {
            name: 'gap + all sources loaded → gap (true inactivity)',
            segment: makeSegment({ kind: 'gap' }),
            store: storeWithSources(20, allLoaded(20)),
            isLoading: false,
            expectedKind: 'gap',
            expectedIsLoading: undefined,
        },
        {
            name: 'window (active) → unchanged regardless of store state',
            segment: makeSegment({ kind: 'window', isActive: true, windowId: 1 }),
            store: storeWithSources(20, [0, 1, 2]),
            isLoading: true,
            expectedKind: 'window',
            expectedIsLoading: undefined,
        },
        {
            name: 'window (inactive) → unchanged regardless of store state',
            segment: makeSegment({ kind: 'window', isActive: false, windowId: 1 }),
            store: storeWithSources(20, allLoaded(20)),
            isLoading: false,
            expectedKind: 'window',
            expectedIsLoading: undefined,
        },
    ])('$name', ({ segment, store, isLoading, expectedKind, expectedIsLoading }) => {
        const [result] = convertSegmentKinds([segment], store, isLoading)
        expect(result.kind).toBe(expectedKind)
        expect(result.isLoading).toBe(expectedIsLoading)
    })

    it('gap spanning partial unload — single unloaded source in range converts to buffer', () => {
        const store = new SnapshotStore()
        store.setSources(makeSources(20))
        // Load all except source 7
        for (let i = 0; i < 20; i++) {
            if (i !== 7) {
                store.markLoaded(i, [])
            }
        }

        const segment = makeSegment({
            kind: 'gap',
            startTimestamp: tsForMinute(3),
            endTimestamp: tsForMinute(12),
        })

        const [result] = convertSegmentKinds([segment], store, true)
        expect(result.kind).toBe('buffer')
        expect(result.isLoading).toBe(true)
    })

    it('processes multiple segments with mixed kinds independently', () => {
        const store = storeWithSources(20, allLoaded(20))
        const segments = [
            makeSegment({ kind: 'buffer' }),
            makeSegment({ kind: 'window', isActive: true, windowId: 1 }),
            makeSegment({ kind: 'gap' }),
        ]
        const result = convertSegmentKinds(segments, store, false)
        expect(result.map((s) => s.kind)).toEqual(['gap', 'window', 'gap'])
    })

    it('isLoading propagates current loading state to buffer segments', () => {
        const emptyStore = new SnapshotStore()
        const notLoading = convertSegmentKinds([makeSegment({ kind: 'buffer' })], emptyStore, false)
        expect(notLoading[0].isLoading).toBe(false)

        const loading = convertSegmentKinds([makeSegment({ kind: 'buffer' })], emptyStore, true)
        expect(loading[0].isLoading).toBe(true)
    })
})
