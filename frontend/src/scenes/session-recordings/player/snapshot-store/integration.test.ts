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

        const currentIndex = opts.playbackPosition ? store.getSourceIndexForTimestamp(opts.playbackPosition) : 0
        if (opts.maxEvicted !== undefined) {
            store.evict(currentIndex, opts.maxEvicted)
        }

        scheduler.onBatchLoaded()
    }

    return batches
}

describe('SnapshotStore + LoadingScheduler integration', () => {
    it('loads a short recording sequentially from start to finish', () => {
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

        // All loaded sequentially
        expect(batches.every((b) => b.reason === 'sequential')).toBe(true)
        // All 10 sources loaded
        for (let i = 0; i < 10; i++) {
            expect(store.isSourceLoaded(i)).toBe(true)
        }
        // Can play at any point
        expect(store.canPlayAt(tsForMinute(0))).toBe(true)
        expect(store.canPlayAt(tsForMinute(9))).toBe(true)
    })

    it('interrupts sequential loading with a seek to the middle', () => {
        const store = new SnapshotStore()
        const scheduler = new LoadingScheduler()
        store.setSources(makeSources(30))

        // Start sequential — load the first batch
        const firstBatch = scheduler.getNextBatch(store, 3)!
        expect(firstBatch.reason).toBe('sequential')
        for (const idx of firstBatch.sourceIndices) {
            store.markLoaded(
                idx,
                idx === 0
                    ? [makeFullSnapshot(tsForMinute(idx)), makeSnapshot(tsForMinute(idx) + 100)]
                    : [makeSnapshot(tsForMinute(idx))]
            )
        }

        // User seeks to minute 20
        scheduler.seekTo(tsForMinute(20))
        expect(scheduler.currentMode).toEqual({ kind: 'seek', targetTimestamp: tsForMinute(20) })

        // Run the loading loop from here
        const batches = runLoadingLoop(store, scheduler, {
            snapshotFactory: (i) => [makeSnapshot(tsForMinute(i))],
            batchSize: 10,
        })

        const reasons = batches.map((b) => b.reason)

        // First batch should target the seek window around minute 20
        expect(reasons[0]).toBe('seek_target')

        // Source 0 already has a FullSnapshot from the initial sequential load,
        // so the scheduler fills the gap (sources 3-17) rather than searching backward
        expect(reasons).toContain('seek_gap_fill')

        // After the gap is filled, canPlayAt succeeds and it continues forward
        expect(reasons).toContain('forward_from_seek')

        // All 30 sources eventually loaded
        for (let i = 0; i < 30; i++) {
            expect(store.isSourceLoaded(i)).toBe(true)
        }
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

        // Should load seek window, find FullSnapshot at 12, fill gap 12→15, then continue
        expect(reasons[0]).toBe('seek_target')

        // Should be playable at the target after seek resolution
        expect(store.canPlayAt(tsForMinute(15))).toBe(true)

        // Should have switched to sequential continuation
        expect(scheduler.currentMode).toEqual({ kind: 'sequential' })
    })

    it('eviction keeps future sources during forward playback', () => {
        const store = new SnapshotStore()
        const scheduler = new LoadingScheduler()
        store.setSources(makeSources(20))

        // Load everything with playback at minute 10, max 8 loaded
        const batches = runLoadingLoop(store, scheduler, {
            snapshotFactory: (i) =>
                i === 0
                    ? [makeFullSnapshot(tsForMinute(i)), makeSnapshot(tsForMinute(i) + 100)]
                    : [makeSnapshot(tsForMinute(i))],
            batchSize: 5,
            playbackPosition: tsForMinute(10),
            maxEvicted: 8,
        })

        // Should have loaded and evicted some sources
        expect(batches.length).toBeGreaterThan(0)

        // Future sources (11-19) should be preferentially kept over past (0-9)
        const loadedIndices: number[] = []
        const evictedIndices: number[] = []
        for (let i = 0; i < 20; i++) {
            const state = store.getEntry(i)?.state
            if (state === 'loaded') {
                loadedIndices.push(i)
            } else if (state === 'evicted') {
                evictedIndices.push(i)
            }
        }

        // All evicted sources should be past sources (before playback position)
        // except when we've exhausted all past sources
        const evictedFuture = evictedIndices.filter((i) => i > 10)
        const evictedPast = evictedIndices.filter((i) => i < 10)

        // Past sources should be evicted before future ones
        if (evictedFuture.length > 0) {
            // If any future source was evicted, ALL past sources must already be evicted
            for (let i = 0; i < 10; i++) {
                if (i !== 0 && i !== 10) {
                    // 0 might be protected (FullSnapshot), 10 might be protected (current)
                    expect(evictedPast).toContain(i)
                }
            }
        }
    })

    it('seek then continue fills the whole recording', () => {
        const store = new SnapshotStore()
        const scheduler = new LoadingScheduler()
        store.setSources(makeSources(20))

        // FullSnapshot at source 0
        // Seek to minute 10
        scheduler.seekTo(tsForMinute(10))

        const batches = runLoadingLoop(store, scheduler, {
            snapshotFactory: (i) =>
                i === 0
                    ? [makeFullSnapshot(tsForMinute(i)), makeSnapshot(tsForMinute(i) + 100)]
                    : [makeSnapshot(tsForMinute(i))],
            batchSize: 5,
        })

        const reasons = batches.map((b) => b.reason)

        // Should see: seek_target → seek_backward (finds FullSnapshot at 0) → seek_gap_fill → forward_from_seek → backward_to_start/sequential
        expect(reasons[0]).toBe('seek_target')

        // After everything loads, all sources should be loaded
        for (let i = 0; i < 20; i++) {
            expect(store.isSourceLoaded(i)).toBe(true)
        }

        // Should have loaded forward from seek before going backward
        const forwardIdx = reasons.indexOf('forward_from_seek')
        const backwardIdx = reasons.indexOf('backward_to_start')
        if (forwardIdx >= 0 && backwardIdx >= 0) {
            expect(forwardIdx).toBeLessThan(backwardIdx)
        }
    })

    it('buffer-ahead throttle pauses and resumes as playback advances', () => {
        const store = new SnapshotStore()
        const scheduler = new LoadingScheduler()
        // 2 hours of recording
        store.setSources(makeSources(120))

        // Load first 70 minutes
        for (let i = 0; i < 70; i++) {
            store.markLoaded(i, [i === 0 ? makeFullSnapshot(tsForMinute(i)) : makeSnapshot(tsForMinute(i))])
        }

        // Playback at minute 0 → 70 minutes buffered → throttled
        expect(scheduler.getNextBatch(store, 5, tsForMinute(0))).toBeNull()

        // Playback advances to minute 30 → only 40 min buffered → resumes
        const batch = scheduler.getNextBatch(store, 5, tsForMinute(30))
        expect(batch).not.toBeNull()
        expect(batch?.reason).toBe('sequential')
        expect(batch?.sourceIndices[0]).toBe(70)
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

        // Then load sources 0-5 sequentially (backward search)
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
})
