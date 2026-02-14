import { EventType } from '@posthog/rrweb-types'

import { RecordingSnapshot, SessionRecordingSnapshotSource } from '~/types'

import { LoadingScheduler } from './LoadingScheduler'
import { SnapshotStore } from './SnapshotStore'
import { LoadBatch } from './types'

// Each source represents 1 minute of recording
function makeSources(count: number): SessionRecordingSnapshotSource[] {
    return Array.from({ length: count }, (_, i) => ({
        source: 'blob_v2' as const,
        blob_key: String(i),
        start_timestamp: new Date(Date.UTC(2023, 7, 11, 12, i, 0)).toISOString(),
        end_timestamp: new Date(Date.UTC(2023, 7, 11, 12, i + 1, 0)).toISOString(),
    }))
}

function tsForMinute(minute: number, second: number = 30): number {
    return new Date(Date.UTC(2023, 7, 11, 12, minute, second)).getTime()
}

function makeSnapshot(timestamp: number, windowId: number = 1): RecordingSnapshot {
    return { timestamp, windowId, type: EventType.IncrementalSnapshot, data: {} } as unknown as RecordingSnapshot
}

function makeFullSnapshot(timestamp: number, windowId: number = 1): RecordingSnapshot {
    return {
        timestamp,
        windowId,
        type: EventType.FullSnapshot,
        data: { node: {}, initialOffset: { top: 0, left: 0 } },
    } as unknown as RecordingSnapshot
}

/**
 * Simulates what snapshotDataLogic does in a loop:
 * get next batch → "load" each source → evict → repeat.
 *
 * The snapshotFactory controls what snapshots each source produces.
 * Returns the sequence of batches that were loaded.
 */
function runLoadingLoop(
    store: SnapshotStore,
    scheduler: LoadingScheduler,
    opts: {
        snapshotFactory: (sourceIndex: number) => RecordingSnapshot[]
        batchSize?: number
        playbackPosition?: number
        maxEvicted?: number
        maxIterations?: number
    }
): LoadBatch[] {
    const batches: LoadBatch[] = []
    const maxIterations = opts.maxIterations ?? 100
    let iterations = 0

    while (iterations++ < maxIterations) {
        const batch = scheduler.getNextBatch(store, opts.batchSize ?? 5, opts.playbackPosition)
        if (!batch) {
            break
        }

        batches.push(batch)

        for (const idx of batch.sourceIndices) {
            const snaps = opts.snapshotFactory(idx)
            store.markLoaded(idx, snaps)
        }

        if (opts.maxEvicted !== undefined && !scheduler.isSeeking) {
            const currentIndex = opts.playbackPosition ? store.getSourceIndexForTimestamp(opts.playbackPosition) : 0
            store.evict(currentIndex, opts.maxEvicted)
        }
    }

    return batches
}

describe('SnapshotStore + LoadingScheduler integration', () => {
    it('loads a short recording from start to buffer limit', () => {
        const store = new SnapshotStore()
        const scheduler = new LoadingScheduler()
        store.setSources(makeSources(10))

        const batches = runLoadingLoop(store, scheduler, {
            snapshotFactory: (i) =>
                i === 0
                    ? [makeFullSnapshot(tsForMinute(i)), makeSnapshot(tsForMinute(i) + 100)]
                    : [makeSnapshot(tsForMinute(i))],
            batchSize: 3,
        })

        // All loaded via buffer_ahead (10 sources < buffer limit of 30)
        expect(batches.every((b) => b.reason === 'buffer_ahead')).toBe(true)
        for (let i = 0; i < 10; i++) {
            expect(store.getEntry(i)?.state === 'loaded').toBe(true)
        }
        expect(store.canPlayAt(tsForMinute(0))).toBe(true)
        expect(store.canPlayAt(tsForMinute(9))).toBe(true)
    })

    it('seek loads window and buffers ahead, does not load backward', () => {
        const store = new SnapshotStore()
        const scheduler = new LoadingScheduler()
        store.setSources(makeSources(50))

        // Seek to minute 30
        scheduler.seekTo(tsForMinute(30))

        const batches = runLoadingLoop(store, scheduler, {
            snapshotFactory: (i) =>
                i === 28
                    ? [makeFullSnapshot(tsForMinute(i)), makeSnapshot(tsForMinute(i) + 100)]
                    : [makeSnapshot(tsForMinute(i))],
            batchSize: 10,
        })

        const reasons = batches.map((b) => b.reason)

        // Seek target first
        expect(reasons[0]).toBe('seek_target')
        // Then buffer ahead
        expect(reasons).toContain('buffer_ahead')
        // No backward loading
        expect(store.canPlayAt(tsForMinute(30))).toBe(true)

        // Sources ahead of seek should be loaded, sources before should not
        expect(store.getEntry(30)?.state).toBe('loaded')
        expect(store.getEntry(49)?.state).toBe('loaded')
        // Sources well before the seek window should remain unloaded
        expect(store.getEntry(0)?.state).toBe('unloaded')
        expect(store.getEntry(10)?.state).toBe('unloaded')
    })

    it('seek resolves quickly when a FullSnapshot exists near the target', () => {
        const store = new SnapshotStore()
        const scheduler = new LoadingScheduler()
        store.setSources(makeSources(30))

        // Seek to minute 15
        scheduler.seekTo(tsForMinute(15))

        // FullSnapshot at source 12 (near the seek window)
        const batches = runLoadingLoop(store, scheduler, {
            snapshotFactory: (i) =>
                i === 12
                    ? [makeFullSnapshot(tsForMinute(i)), makeSnapshot(tsForMinute(i) + 100)]
                    : [makeSnapshot(tsForMinute(i))],
            batchSize: 10,
        })

        const reasons = batches.map((b) => b.reason)

        expect(reasons[0]).toBe('seek_target')
        expect(store.canPlayAt(tsForMinute(15))).toBe(true)
        expect(scheduler.currentMode).toEqual({ kind: 'buffer_ahead' })
    })

    it('eviction trims sources when buffer exceeds max loaded', () => {
        const store = new SnapshotStore()
        const scheduler = new LoadingScheduler()
        store.setSources(makeSources(20))

        // Buffer ahead from playback at minute 5, max 8 loaded
        runLoadingLoop(store, scheduler, {
            snapshotFactory: (i) =>
                i === 5
                    ? [makeFullSnapshot(tsForMinute(i)), makeSnapshot(tsForMinute(i) + 100)]
                    : [makeSnapshot(tsForMinute(i))],
            batchSize: 5,
            playbackPosition: tsForMinute(5),
            maxEvicted: 8,
        })

        const loadedCount = Array.from({ length: 20 }, (_, i) => i).filter(
            (i) => store.getEntry(i)?.state === 'loaded'
        ).length

        // Should not exceed the eviction limit
        expect(loadedCount).toBeLessThanOrEqual(8)
        // Current playback source should still be loaded
        expect(store.getEntry(5)?.state).toBe('loaded')
    })

    it('buffer ahead stops at BUFFER_AHEAD_SOURCES limit', () => {
        const store = new SnapshotStore()
        const scheduler = new LoadingScheduler()
        store.setSources(makeSources(100))

        // Start from beginning, no seek
        const batches = runLoadingLoop(store, scheduler, {
            snapshotFactory: (i) =>
                i === 0
                    ? [makeFullSnapshot(tsForMinute(i)), makeSnapshot(tsForMinute(i) + 100)]
                    : [makeSnapshot(tsForMinute(i))],
            batchSize: 10,
            playbackPosition: tsForMinute(0),
        })

        // Should not load all 100 sources — only the buffer ahead
        const loadedCount = Array.from({ length: 100 }, (_, i) => i).filter(
            (i) => store.getEntry(i)?.state === 'loaded'
        ).length
        expect(loadedCount).toBeLessThan(100)
        expect(loadedCount).toBeGreaterThan(0)

        // Sources beyond the buffer should be unloaded
        expect(store.getEntry(99)?.state).toBe('unloaded')

        // All batches should be buffer_ahead
        expect(batches.every((b) => b.reason === 'buffer_ahead')).toBe(true)
    })

    it('sliding window: advancing playback position loads more ahead', () => {
        const store = new SnapshotStore()
        const scheduler = new LoadingScheduler()
        store.setSources(makeSources(100))

        // Load initial buffer at position 0
        runLoadingLoop(store, scheduler, {
            snapshotFactory: (i) =>
                i === 0
                    ? [makeFullSnapshot(tsForMinute(i)), makeSnapshot(tsForMinute(i) + 100)]
                    : [makeSnapshot(tsForMinute(i))],
            batchSize: 10,
            playbackPosition: tsForMinute(0),
        })

        const initialLoaded = Array.from({ length: 100 }, (_, i) => i).filter(
            (i) => store.getEntry(i)?.state === 'loaded'
        ).length

        // Advance playback to minute 20 — should load more ahead
        const newBatches = runLoadingLoop(store, scheduler, {
            snapshotFactory: (i) => [makeSnapshot(tsForMinute(i))],
            batchSize: 10,
            playbackPosition: tsForMinute(20),
        })

        const afterAdvanceLoaded = Array.from({ length: 100 }, (_, i) => i).filter(
            (i) => store.getEntry(i)?.state === 'loaded'
        ).length

        expect(newBatches.length).toBeGreaterThan(0)
        expect(afterAdvanceLoaded).toBeGreaterThan(initialLoaded)
    })

    it('second seek after first seek was partially resolved', () => {
        const store = new SnapshotStore()
        const scheduler = new LoadingScheduler()
        store.setSources(makeSources(30))

        // Start seeking to minute 10
        scheduler.seekTo(tsForMinute(10))
        const firstBatch = scheduler.getNextBatch(store, 10)!
        expect(firstBatch.reason).toBe('seek_target')

        // Load the first seek batch
        for (const idx of firstBatch.sourceIndices) {
            store.markLoaded(idx, [makeSnapshot(tsForMinute(idx))])
        }

        // Before seek resolves, user seeks to minute 25 instead
        scheduler.seekTo(tsForMinute(25))
        expect(scheduler.currentMode).toEqual({ kind: 'seek', targetTimestamp: tsForMinute(25) })

        // New seek should load around minute 25
        const secondBatch = scheduler.getNextBatch(store, 10)!
        expect(secondBatch.reason).toBe('seek_target')
        expect(secondBatch.sourceIndices.some((i) => i >= 23)).toBe(true)
    })

    it('getAllLoadedSnapshots returns sorted data across multiple load rounds', () => {
        const store = new SnapshotStore()
        const scheduler = new LoadingScheduler()
        store.setSources(makeSources(10))

        // Seek to minute 8 — loads sources 6-9 first
        scheduler.seekTo(tsForMinute(8))
        const seekBatch = scheduler.getNextBatch(store, 10)!
        for (const idx of seekBatch.sourceIndices) {
            store.markLoaded(idx, [makeSnapshot(tsForMinute(idx))])
        }

        // Then load sources 0-5 via backward search
        const nextBatch = scheduler.getNextBatch(store, 10)!
        for (const idx of nextBatch.sourceIndices) {
            store.markLoaded(idx, [idx === 0 ? makeFullSnapshot(tsForMinute(idx)) : makeSnapshot(tsForMinute(idx))])
        }

        // Merged snapshots should be sorted regardless of load order
        const allSnapshots = store.getAllLoadedSnapshots()
        for (let i = 1; i < allSnapshots.length; i++) {
            expect(allSnapshots[i].timestamp).toBeGreaterThanOrEqual(allSnapshots[i - 1].timestamp)
        }
    })

    it('non-contiguous batch indices are split into contiguous sub-batches', () => {
        const store = new SnapshotStore()
        const scheduler = new LoadingScheduler()
        store.setSources(makeSources(20))

        // Pre-load sources 3-6 so the scheduler's next batch will have a gap
        for (let i = 3; i <= 6; i++) {
            store.markLoaded(i, [makeSnapshot(tsForMinute(i))])
        }

        const batch = scheduler.getNextBatch(store, 10, tsForMinute(0))!
        expect(batch.reason).toBe('buffer_ahead')
        // Batch should be [0,1,2, 7,8,9,...] — non-contiguous because 3-6 are loaded
        expect(batch.sourceIndices).toContain(0)
        expect(batch.sourceIndices).toContain(7)
        expect(batch.sourceIndices).not.toContain(3)

        // Simulate snapshotDataLogic's contiguous truncation
        const indices = batch.sourceIndices
        const contiguous = [indices[0]]
        for (let i = 1; i < indices.length; i++) {
            if (indices[i] !== indices[i - 1] + 1) {
                break
            }
            contiguous.push(indices[i])
        }

        // First contiguous group should be [0,1,2]
        expect(contiguous).toEqual([0, 1, 2])

        // Load just the first contiguous group
        for (const idx of contiguous) {
            store.markLoaded(idx, [idx === 0 ? makeFullSnapshot(tsForMinute(idx)) : makeSnapshot(tsForMinute(idx))])
        }

        // Next batch should pick up from source 7 (the next unloaded)
        const nextBatch = scheduler.getNextBatch(store, 10, tsForMinute(0))!
        expect(nextBatch.sourceIndices[0]).toBe(7)
    })

    it('eviction does not cause infinite loading loop', () => {
        const store = new SnapshotStore()
        const scheduler = new LoadingScheduler()
        store.setSources(makeSources(55))

        // Seek to middle with FullSnapshot at source 25
        scheduler.seekTo(tsForMinute(30))

        const batches = runLoadingLoop(store, scheduler, {
            snapshotFactory: (i) =>
                i === 25
                    ? [makeFullSnapshot(tsForMinute(i)), makeSnapshot(tsForMinute(i) + 100)]
                    : [makeSnapshot(tsForMinute(i))],
            batchSize: 10,
            playbackPosition: tsForMinute(30),
            maxEvicted: 50,
            maxIterations: 20,
        })

        // Should converge within the iteration limit (not hit maxIterations)
        expect(batches.length).toBeLessThan(20)
    })
})
