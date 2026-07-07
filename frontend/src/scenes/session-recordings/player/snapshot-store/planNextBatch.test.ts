import { EventType } from 'posthog-js/rrweb-types'

import { SnapshotStore } from '@posthog/replay-shared'

import { RecordingSnapshot, SessionRecordingSnapshotSource } from '~/types'

import { LoadPlanInput, planNextBatch } from './planNextBatch'
import { markLoaded } from './test-utils'

function makeSources(count: number): SessionRecordingSnapshotSource[] {
    return Array.from({ length: count }, (_, i) => ({
        source: 'blob_v2' as const,
        blob_key: String(i),
        start_timestamp: new Date(Date.UTC(2023, 7, 11, 12, i, 0)).toISOString(),
        end_timestamp: new Date(Date.UTC(2023, 7, 11, 12, i + 1, 0)).toISOString(),
    }))
}

function makeSnapshot(timestamp: number, windowId: number = 1): RecordingSnapshot {
    return {
        timestamp,
        windowId,
        type: EventType.IncrementalSnapshot,
        data: {},
    } as unknown as RecordingSnapshot
}

function makeFullSnapshot(timestamp: number, windowId: number = 1): RecordingSnapshot {
    return {
        timestamp,
        windowId,
        type: EventType.FullSnapshot,
        data: { node: {}, initialOffset: { top: 0, left: 0 } },
    } as unknown as RecordingSnapshot
}

function tsForMinute(minute: number, second: number = 30): number {
    return new Date(Date.UTC(2023, 7, 11, 12, minute, second)).getTime()
}

function createLoadedStore(
    sourceCount: number,
    loadedIndices: number[],
    fullSnapshotIndices: number[] = []
): SnapshotStore {
    const store = new SnapshotStore()
    store.setSources(makeSources(sourceCount))
    for (const i of loadedIndices) {
        const ts = tsForMinute(i)
        const snaps = fullSnapshotIndices.includes(i)
            ? [makeFullSnapshot(ts), makeSnapshot(ts + 100)]
            : [makeSnapshot(ts)]
        markLoaded(store, i, snaps)
    }
    return store
}

function plan(
    store: SnapshotStore,
    input: Partial<LoadPlanInput> = {},
    batchSize?: number
): ReturnType<typeof planNextBatch> {
    return planNextBatch(store, { target: null, loadAll: false, ...input }, batchSize)
}

describe('planNextBatch', () => {
    describe('buffer ahead', () => {
        it('loads ahead from the start without a position', () => {
            const store = createLoadedStore(10, [])
            expect(plan(store, {}, 3)).toEqual({ sourceIndices: [0, 1, 2], reason: 'buffer_ahead' })
        })

        it('loads ahead from playback position', () => {
            const store = createLoadedStore(50, [])
            const batch = plan(store, { playbackPosition: tsForMinute(20) }, 5)
            expect(batch?.reason).toBe('buffer_ahead')
            expect(batch?.sourceIndices[0]).toBe(20)
        })

        it('skips already loaded sources', () => {
            const store = createLoadedStore(10, [0, 1, 2])
            expect(plan(store, {}, 3)).toEqual({ sourceIndices: [3, 4, 5], reason: 'buffer_ahead' })
        })

        it('returns null when all sources ahead are loaded', () => {
            const store = createLoadedStore(3, [0, 1, 2])
            expect(plan(store)).toBeNull()
        })

        it('returns null when store is empty', () => {
            expect(plan(new SnapshotStore())).toBeNull()
        })

        it('respects buffer limit', () => {
            const store = createLoadedStore(100, [])
            const batch = plan(store, { playbackPosition: tsForMinute(0) }, 100)
            expect(Math.max(...batch!.sourceIndices)).toBe(29)
        })

        it('scans forward beyond the buffer window when nothing renderable is known', () => {
            // Playhead at the start, buffer window fully loaded, but no FullSnapshot
            // anywhere — e.g. the initial full snapshot was lost at capture time
            const loaded = Array.from({ length: 30 }, (_, i) => i)
            const store = createLoadedStore(50, loaded, [])
            const batch = plan(store, { playbackPosition: tsForMinute(0) })
            expect(batch?.reason).toBe('seek_forward')
            expect(batch?.sourceIndices).toEqual([30, 31, 32, 33, 34, 35, 36, 37, 38, 39])
        })

        it('does not scan beyond the buffer window when the playhead is renderable', () => {
            const loaded = Array.from({ length: 30 }, (_, i) => i)
            const store = createLoadedStore(50, loaded, [0])
            expect(plan(store, { playbackPosition: tsForMinute(0) })).toBeNull()
        })

        it('does not sweep the recording when the playhead is parked just before the first FullSnapshot', () => {
            // A paused-at-start mount (autoPlay={false} or ?pause=true&t=0) parks the playhead at the
            // meta start, epsilon before the window's first FullSnapshot — the loaded later FullSnapshot
            // is the clamp target, so nothing beyond the buffer window may be fetched
            const loaded = Array.from({ length: 30 }, (_, i) => i)
            const store = createLoadedStore(50, loaded, [0])
            expect(plan(store, { playbackPosition: tsForMinute(0) - 50 })).toBeNull()
            expect(plan(store, { playbackPosition: tsForMinute(0) - 50, playbackWindowId: 1 })).toBeNull()
        })

        it('scans forward when the playhead window has no FullSnapshot even though another window does', () => {
            // The FullSnapshot at source 0 belongs to window 2 — it can't render
            // window-1 content at the playhead, so the scan must still fire
            const store = new SnapshotStore()
            store.setSources(makeSources(50))
            for (let i = 0; i < 30; i++) {
                const ts = tsForMinute(i)
                markLoaded(store, i, i === 0 ? [makeFullSnapshot(ts, 2), makeSnapshot(ts + 100)] : [makeSnapshot(ts)])
            }
            const batch = plan(store, { playbackPosition: tsForMinute(0), playbackWindowId: 1 })
            expect(batch?.reason).toBe('seek_forward')
            expect(batch?.sourceIndices).toEqual([30, 31, 32, 33, 34, 35, 36, 37, 38, 39])
        })

        it('does not load backward from playback position', () => {
            // Sources 0-9 unloaded, 10-19 loaded
            const store = createLoadedStore(
                20,
                Array.from({ length: 10 }, (_, i) => i + 10)
            )
            expect(plan(store, { playbackPosition: tsForMinute(15) })).toBeNull()
        })
    })

    describe('seek target', () => {
        it('loads the window around the target first', () => {
            const store = createLoadedStore(20, [])
            const batch = plan(store, { target: { timestamp: tsForMinute(10) } }, 11)
            expect(batch?.reason).toBe('seek_target')
            // Window: [target-3, target+7] = [7, 17]
            expect(batch?.sourceIndices[0]).toBe(7)
            expect(batch?.sourceIndices[batch.sourceIndices.length - 1]).toBe(17)
        })

        it.each([
            { targetMinute: 0, expectedStart: 0, description: 'clamped at recording start' },
            { targetMinute: 19, expectedEnd: 19, description: 'clamped at recording end' },
        ])('window is $description', ({ targetMinute, expectedStart, expectedEnd }) => {
            const store = createLoadedStore(20, [])
            const batch = plan(store, { target: { timestamp: tsForMinute(targetMinute) } }, 20)!
            if (expectedStart !== undefined) {
                expect(batch.sourceIndices[0]).toBe(expectedStart)
            }
            if (expectedEnd !== undefined) {
                expect(batch.sourceIndices[batch.sourceIndices.length - 1]).toBe(expectedEnd)
            }
        })

        it('ignores a satisfied target and buffers ahead instead', () => {
            const loaded = Array.from({ length: 13 }, (_, i) => i)
            const store = createLoadedStore(20, loaded, [0])
            const batch = plan(store, { target: { timestamp: tsForMinute(5) } })
            expect(batch?.reason).toBe('buffer_ahead')
        })

        it('fills gap between FullSnapshot and target', () => {
            const loaded = [0, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15, 16, 17]
            const store = createLoadedStore(20, loaded, [0])
            const batch = plan(store, { target: { timestamp: tsForMinute(10) } })
            expect(batch?.reason).toBe('seek_gap_fill')
            expect(batch?.sourceIndices).toContain(1)
            expect(batch?.sourceIndices).toContain(4)
        })

        it('searches backward when no FullSnapshot found', () => {
            const loaded = [7, 8, 9, 10, 11, 12, 13, 14, 15, 16, 17]
            const store = createLoadedStore(20, loaded, [])
            const batch = plan(store, { target: { timestamp: tsForMinute(10) } })
            expect(batch?.reason).toBe('seek_backward')
            expect(batch?.sourceIndices.every((i) => i < 8)).toBe(true)
        })

        it('skips over loaded ranges when searching backward', () => {
            // Sources 3-7 loaded (no FullSnapshot), 0-2 unloaded, target window 8-17 loaded
            const loaded = [3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15, 16, 17]
            const store = createLoadedStore(20, loaded, [])
            const batch = plan(store, { target: { timestamp: tsForMinute(10) } })
            expect(batch?.reason).toBe('seek_backward')
            expect(batch?.sourceIndices).toEqual([0, 1, 2])
        })

        it('returns null when everything is loaded and nothing can satisfy the target', () => {
            const allIndices = Array.from({ length: 20 }, (_, i) => i)
            const store = createLoadedStore(20, allIndices, [])
            expect(plan(store, { target: { timestamp: tsForMinute(10) } })).toBeNull()
        })

        it('searches forward when no FullSnapshot exists at or before the target', () => {
            // Everything up to source 17 loaded without any FullSnapshot, 18-19 unloaded
            const loaded = Array.from({ length: 18 }, (_, i) => i)
            const store = createLoadedStore(20, loaded, [])
            const batch = plan(store, { target: { timestamp: tsForMinute(10) } })
            expect(batch?.reason).toBe('seek_forward')
            expect(batch?.sourceIndices).toEqual([18, 19])
        })

        it('stops searching forward once a later FullSnapshot is known', () => {
            // No FullSnapshot before the target, but one is loaded at source 18 —
            // the player recovers by clamping the seek to it, so nothing more is needed
            const allIndices = Array.from({ length: 20 }, (_, i) => i)
            const store = createLoadedStore(20, allIndices, [18])
            expect(plan(store, { target: { timestamp: tsForMinute(10) } })).toBeNull()
        })

        it('keeps searching forward when the only later FullSnapshot belongs to another window', () => {
            // Sources 0-18 loaded; the FullSnapshot at source 18 belongs to window 2,
            // which can't render a window-1 target — source 19 must still be scanned
            const store = new SnapshotStore()
            store.setSources(makeSources(20))
            for (let i = 0; i < 19; i++) {
                const ts = tsForMinute(i)
                markLoaded(store, i, i === 18 ? [makeFullSnapshot(ts, 2), makeSnapshot(ts + 100)] : [makeSnapshot(ts)])
            }
            const batch = plan(store, { target: { timestamp: tsForMinute(10), windowId: 1 } })
            expect(batch?.reason).toBe('seek_forward')
            expect(batch?.sourceIndices).toEqual([19])
        })

        it('only counts FullSnapshots of the target window when a windowId is given', () => {
            // FullSnapshot at source 5 belongs to window 2; sources 0-2 unloaded
            const loaded = Array.from({ length: 17 }, (_, i) => i + 3)
            const store = new SnapshotStore()
            store.setSources(makeSources(20))
            for (const i of loaded) {
                const ts = tsForMinute(i)
                markLoaded(store, i, i === 5 ? [makeFullSnapshot(ts, 2), makeSnapshot(ts + 100)] : [makeSnapshot(ts)])
            }

            // A window-agnostic target is satisfied by window 2's FullSnapshot — nothing to fetch
            expect(plan(store, { target: { timestamp: tsForMinute(10) } })).toBeNull()

            // A window-1 target must keep searching backward for window 1's FullSnapshot
            const batch = plan(store, { target: { timestamp: tsForMinute(10), windowId: 1 } })
            expect(batch?.reason).toBe('seek_backward')
            expect(batch?.sourceIndices).toEqual([0, 1, 2])
        })

        it('buffers ahead from the target once the seek is satisfied', () => {
            const loaded = Array.from({ length: 16 }, (_, i) => i)
            const store = createLoadedStore(20, loaded, [0])
            const batch = plan(store, { target: { timestamp: tsForMinute(8) } }, 5)
            expect(batch?.reason).toBe('buffer_ahead')
            expect(batch?.sourceIndices).toEqual([16, 17, 18, 19])
        })

        it('does not load backward once the seek is satisfied', () => {
            // Sources 3-19 loaded with FullSnapshot at 3, sources 0-2 unloaded
            const loaded = Array.from({ length: 17 }, (_, i) => i + 3)
            const store = createLoadedStore(20, loaded, [3])
            expect(plan(store, { target: { timestamp: tsForMinute(8) } })).toBeNull()
        })
    })

    describe('fetched sources', () => {
        it('does not re-request fetched-but-unprocessed sources', () => {
            const store = new SnapshotStore()
            store.setSources(makeSources(3))
            for (let i = 0; i < 3; i++) {
                store.markFetched(i, [makeSnapshot(tsForMinute(i))])
            }

            // nothing to fetch even though nothing is playable yet — processing, not the network, is what's pending
            expect(plan(store, { target: { timestamp: tsForMinute(1) } })).toBeNull()
            expect(plan(store, { playbackPosition: tsForMinute(0) })).toBeNull()
            expect(plan(store, { loadAll: true })).toBeNull()
        })
    })

    describe('truncation to contiguous ranges', () => {
        it.each([
            { description: 'stops at loaded source in the middle', loaded: [5], expected: [3, 4] },
            { description: 'stops at two loaded sources', loaded: [5, 6], expected: [3, 4] },
            { description: 'single unloaded before loaded block', loaded: [4, 5, 6], expected: [3] },
        ])('$description', ({ loaded, expected }) => {
            // Sources 0-9, pre-load 0-2 so buffer_ahead starts at 3
            const store = createLoadedStore(10, [0, 1, 2, ...loaded])
            const batch = plan(store, { playbackPosition: tsForMinute(0) })
            expect(batch?.sourceIndices).toEqual(expected)
        })
    })

    describe('load all', () => {
        it('loads all unloaded sources from the beginning', () => {
            const store = createLoadedStore(10, [3, 4, 5])
            expect(plan(store, { loadAll: true }, 5)).toEqual({ sourceIndices: [0, 1, 2], reason: 'load_all' })
        })

        it('skips loaded sources and finds next contiguous unloaded batch', () => {
            const store = createLoadedStore(10, [0, 1, 2, 5, 6])
            expect(plan(store, { loadAll: true }, 5)?.sourceIndices).toEqual([3, 4])
        })

        it('returns null when all sources are loaded', () => {
            const allLoaded = Array.from({ length: 10 }, (_, i) => i)
            const store = createLoadedStore(10, allLoaded)
            expect(plan(store, { loadAll: true })).toBeNull()
        })

        it('overrides seek targets and playback position', () => {
            const store = createLoadedStore(50, [])
            const batch = plan(
                store,
                { loadAll: true, target: { timestamp: tsForMinute(30) }, playbackPosition: tsForMinute(40) },
                5
            )
            expect(batch?.sourceIndices).toEqual([0, 1, 2, 3, 4])
        })
    })
})
