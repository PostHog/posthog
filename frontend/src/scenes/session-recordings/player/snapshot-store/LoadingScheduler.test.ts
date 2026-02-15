import { EventType } from '@posthog/rrweb-types'

import { RecordingSnapshot, SessionRecordingSnapshotSource } from '~/types'

import { LoadingScheduler } from './LoadingScheduler'
import { SnapshotStore } from './SnapshotStore'

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
        store.markLoaded(i, snaps)
    }
    return store
}

describe('LoadingScheduler', () => {
    describe('buffer ahead', () => {
        it('starts in buffer_ahead mode', () => {
            const scheduler = new LoadingScheduler()
            expect(scheduler.currentMode).toEqual({ kind: 'buffer_ahead' })
        })

        it('loads ahead from anchor position', () => {
            const store = createLoadedStore(10, [])
            const scheduler = new LoadingScheduler()

            const batch = scheduler.getNextBatch(store, 3)
            expect(batch).toEqual({
                sourceIndices: [0, 1, 2],
                reason: 'buffer_ahead',
            })
        })

        it('loads ahead from playback position', () => {
            const store = createLoadedStore(50, [])
            const scheduler = new LoadingScheduler()

            const batch = scheduler.getNextBatch(store, 5, tsForMinute(20))
            expect(batch?.reason).toBe('buffer_ahead')
            expect(batch?.sourceIndices[0]).toBe(20)
        })

        it('skips already loaded sources', () => {
            const store = createLoadedStore(10, [0, 1, 2])
            const scheduler = new LoadingScheduler()

            const batch = scheduler.getNextBatch(store, 3)
            expect(batch).toEqual({
                sourceIndices: [3, 4, 5],
                reason: 'buffer_ahead',
            })
        })

        it('returns null when all sources ahead are loaded', () => {
            const store = createLoadedStore(3, [0, 1, 2])
            const scheduler = new LoadingScheduler()

            expect(scheduler.getNextBatch(store)).toBeNull()
        })

        it('returns null when store is empty', () => {
            const store = new SnapshotStore()
            const scheduler = new LoadingScheduler()

            expect(scheduler.getNextBatch(store)).toBeNull()
        })

        it('respects buffer limit', () => {
            const store = createLoadedStore(100, [])
            const scheduler = new LoadingScheduler()

            // With playback at 0, should buffer ahead up to BUFFER_AHEAD_SOURCES (30)
            // i.e. indices 0-29 inclusive
            const batch = scheduler.getNextBatch(store, 100, tsForMinute(0))
            expect(batch?.sourceIndices.length).toBeLessThanOrEqual(100)
            const maxIdx = Math.max(...batch!.sourceIndices)
            expect(maxIdx).toBe(29)
        })

        it('does not load backward from playback position', () => {
            // Sources 0-9 unloaded, 10-19 loaded
            const store = createLoadedStore(
                20,
                Array.from({ length: 10 }, (_, i) => i + 10)
            )
            const scheduler = new LoadingScheduler()

            // Playback at minute 15 — should not try to load 0-9
            const batch = scheduler.getNextBatch(store, 10, tsForMinute(15))
            expect(batch).toBeNull()
        })
    })

    describe('seek mode', () => {
        it('enters seek mode on seekTo', () => {
            const scheduler = new LoadingScheduler()
            scheduler.seekTo(tsForMinute(5))
            expect(scheduler.currentMode).toEqual({ kind: 'seek', targetTimestamp: tsForMinute(5) })
        })

        it('loads window around target on first batch', () => {
            const store = createLoadedStore(20, [])
            const scheduler = new LoadingScheduler()
            scheduler.seekTo(tsForMinute(10))

            const batch = scheduler.getNextBatch(store, 11)
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
            const scheduler = new LoadingScheduler()
            scheduler.seekTo(tsForMinute(targetMinute))

            const batch = scheduler.getNextBatch(store, 20)!
            if (expectedStart !== undefined) {
                expect(batch.sourceIndices[0]).toBe(expectedStart)
            }
            if (expectedEnd !== undefined) {
                expect(batch.sourceIndices[batch.sourceIndices.length - 1]).toBe(expectedEnd)
            }
        })

        it('clears seek and buffers ahead when canPlayAt is true', () => {
            const loaded = Array.from({ length: 13 }, (_, i) => i)
            const store = createLoadedStore(20, loaded, [0])
            const scheduler = new LoadingScheduler()
            scheduler.seekTo(tsForMinute(5))

            const batch = scheduler.getNextBatch(store, 10)
            expect(scheduler.currentMode).toEqual({ kind: 'buffer_ahead' })
            expect(batch?.reason).toBe('buffer_ahead')
        })

        it('fills gap between FullSnapshot and target', () => {
            const loaded = [0, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15, 16, 17]
            const store = createLoadedStore(20, loaded, [0])
            const scheduler = new LoadingScheduler()
            scheduler.seekTo(tsForMinute(10))

            const batch = scheduler.getNextBatch(store, 10)
            expect(batch?.reason).toBe('seek_gap_fill')
            expect(batch?.sourceIndices).toContain(1)
            expect(batch?.sourceIndices).toContain(4)
        })

        it('searches backward when no FullSnapshot found', () => {
            const loaded = [7, 8, 9, 10, 11, 12, 13, 14, 15, 16, 17]
            const store = createLoadedStore(20, loaded, [])
            const scheduler = new LoadingScheduler()
            scheduler.seekTo(tsForMinute(10))

            const batch = scheduler.getNextBatch(store, 10)
            expect(batch?.reason).toBe('seek_backward')
            expect(batch?.sourceIndices.every((i) => i < 8)).toBe(true)
        })

        it('skips over loaded ranges when searching backward', () => {
            // Sources 3-7 loaded (no FullSnapshot), 0-2 unloaded, target window 8-17 loaded
            const loaded = [3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15, 16, 17]
            const store = createLoadedStore(20, loaded, [])
            const scheduler = new LoadingScheduler()
            scheduler.seekTo(tsForMinute(10))

            // Should skip over 3-7 (loaded) and find 0-2 (unloaded)
            const batch = scheduler.getNextBatch(store, 10)
            expect(batch?.reason).toBe('seek_backward')
            expect(batch?.sourceIndices).toEqual([0, 1, 2])
        })

        it('gives up and falls to buffer_ahead when backward search exhausted', () => {
            const allIndices = Array.from({ length: 20 }, (_, i) => i)
            const store = createLoadedStore(20, allIndices, [])
            const scheduler = new LoadingScheduler()
            scheduler.seekTo(tsForMinute(10))

            const batch = scheduler.getNextBatch(store, 10)
            expect(scheduler.currentMode).toEqual({ kind: 'buffer_ahead' })
            expect(batch).toBeNull()
        })
    })

    describe('buffer ahead after seek', () => {
        it('buffers ahead from seek range end', () => {
            const loaded = Array.from({ length: 16 }, (_, i) => i)
            const store = createLoadedStore(20, loaded, [0])
            const scheduler = new LoadingScheduler()
            scheduler.seekTo(tsForMinute(8))

            // Seek resolves → buffers ahead from seekRangeEnd
            const batch = scheduler.getNextBatch(store, 5)
            expect(scheduler.currentMode).toEqual({ kind: 'buffer_ahead' })
            expect(batch?.reason).toBe('buffer_ahead')
            expect(batch?.sourceIndices).toEqual([16, 17, 18, 19])
        })

        it('does not load backward after seek', () => {
            // Sources 3-19 loaded with FullSnapshot at 3, sources 0-2 unloaded
            const loaded = Array.from({ length: 17 }, (_, i) => i + 3)
            const store = createLoadedStore(20, loaded, [3])
            const scheduler = new LoadingScheduler()
            scheduler.seekTo(tsForMinute(8))

            // Seek resolves. No forward to load, no backward loading → null
            const batch = scheduler.getNextBatch(store, 10)
            expect(batch).toBeNull()
        })
    })

    describe('clearSeek', () => {
        it('switches back to buffer_ahead mode', () => {
            const scheduler = new LoadingScheduler()
            scheduler.seekTo(tsForMinute(5))
            scheduler.clearSeek()
            expect(scheduler.currentMode).toEqual({ kind: 'buffer_ahead' })
        })
    })

    describe('isSeeking', () => {
        it('is false in buffer_ahead mode', () => {
            const scheduler = new LoadingScheduler()
            expect(scheduler.isSeeking).toBe(false)
        })

        it('is true after seekTo', () => {
            const scheduler = new LoadingScheduler()
            scheduler.seekTo(tsForMinute(5))
            expect(scheduler.isSeeking).toBe(true)
        })

        it('is false after clearSeek', () => {
            const scheduler = new LoadingScheduler()
            scheduler.seekTo(tsForMinute(5))
            scheduler.clearSeek()
            expect(scheduler.isSeeking).toBe(false)
        })
    })
})
