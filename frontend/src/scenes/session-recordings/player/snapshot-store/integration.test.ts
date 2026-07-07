import { EventType, IncrementalSource } from 'posthog-js/rrweb-types'

import { LoadBatch, SnapshotStore } from '@posthog/replay-shared'

import { RecordingSegment, RecordingSnapshot, SessionRecordingSnapshotSource } from '~/types'

import { createSegments, mapSnapshotsToWindowId } from '../utils/segmenter'
import { SeekTarget, planNextBatch } from './planNextBatch'
import { allLoadedSnapshots, markLoaded } from './test-utils'

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
 * plan next batch → "load" each source → repeat.
 *
 * The snapshotFactory controls what snapshots each source produces.
 * Returns the sequence of batches that were loaded.
 */
function runLoadingLoop(
    store: SnapshotStore,
    opts: {
        snapshotFactory: (sourceIndex: number) => RecordingSnapshot[]
        target?: SeekTarget
        batchSize?: number
        playbackPosition?: number
        maxIterations?: number
    }
): LoadBatch[] {
    const batches: LoadBatch[] = []
    const maxIterations = opts.maxIterations ?? 100
    let iterations = 0

    while (iterations++ < maxIterations) {
        const batch = planNextBatch(
            store,
            { target: opts.target ?? null, loadAll: false, playbackPosition: opts.playbackPosition },
            opts.batchSize ?? 5
        )
        if (!batch) {
            break
        }

        batches.push(batch)

        for (const idx of batch.sourceIndices) {
            const snaps = opts.snapshotFactory(idx)
            markLoaded(store, idx, snaps)
        }
    }

    return batches
}

describe('SnapshotStore + planNextBatch integration', () => {
    it('loads a short recording from start to buffer limit', () => {
        const store = new SnapshotStore()
        store.setSources(makeSources(10))

        const batches = runLoadingLoop(store, {
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
        store.setSources(makeSources(50))

        const batches = runLoadingLoop(store, {
            snapshotFactory: (i) =>
                i === 28
                    ? [makeFullSnapshot(tsForMinute(i)), makeSnapshot(tsForMinute(i) + 100)]
                    : [makeSnapshot(tsForMinute(i))],
            target: { timestamp: tsForMinute(30) },
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
        store.setSources(makeSources(30))

        // FullSnapshot at source 12 (near the seek window)
        const target = { timestamp: tsForMinute(15) }
        const batches = runLoadingLoop(store, {
            snapshotFactory: (i) =>
                i === 12
                    ? [makeFullSnapshot(tsForMinute(i)), makeSnapshot(tsForMinute(i) + 100)]
                    : [makeSnapshot(tsForMinute(i))],
            target,
            batchSize: 10,
        })

        expect(batches[0].reason).toBe('seek_target')
        expect(store.canPlayAt(tsForMinute(15))).toBe(true)
        // A satisfied target no longer produces seek batches
        expect(planNextBatch(store, { target, loadAll: false })?.reason ?? null).not.toBe('seek_target')
    })

    it('buffer ahead stops at BUFFER_AHEAD_SOURCES limit', () => {
        const store = new SnapshotStore()
        store.setSources(makeSources(100))

        // Start from beginning, no seek
        const batches = runLoadingLoop(store, {
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
        store.setSources(makeSources(100))

        // Load initial buffer at position 0
        runLoadingLoop(store, {
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
        const newBatches = runLoadingLoop(store, {
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
        store.setSources(makeSources(30))

        // Start seeking to minute 10
        const firstBatch = planNextBatch(store, { target: { timestamp: tsForMinute(10) }, loadAll: false }, 10)!
        expect(firstBatch.reason).toBe('seek_target')

        // Load the first seek batch
        for (const idx of firstBatch.sourceIndices) {
            markLoaded(store, idx, [makeSnapshot(tsForMinute(idx))])
        }

        // Before the first seek resolves, user seeks to minute 25 instead
        const secondBatch = planNextBatch(store, { target: { timestamp: tsForMinute(25) }, loadAll: false }, 10)!
        expect(secondBatch.reason).toBe('seek_target')
        expect(secondBatch.sourceIndices.some((i) => i >= 23)).toBe(true)
    })

    it('returns contiguous batches, skipping loaded gaps', () => {
        const store = new SnapshotStore()
        store.setSources(makeSources(20))

        // Pre-load sources 3-6 so the planner skips them
        for (let i = 3; i <= 6; i++) {
            markLoaded(store, i, [makeSnapshot(tsForMinute(i))])
        }

        // First batch: contiguous [0,1,2] — stops at the loaded gap
        const batch = planNextBatch(store, { target: null, loadAll: false, playbackPosition: tsForMinute(0) }, 10)!
        expect(batch.reason).toBe('buffer_ahead')
        expect(batch.sourceIndices).toEqual([0, 1, 2])

        // Load the batch
        for (const idx of batch.sourceIndices) {
            markLoaded(store, idx, [idx === 0 ? makeFullSnapshot(tsForMinute(idx)) : makeSnapshot(tsForMinute(idx))])
        }

        // Next batch picks up from source 7 (first unloaded after the gap)
        const nextBatch = planNextBatch(store, { target: null, loadAll: false, playbackPosition: tsForMinute(0) }, 10)!
        expect(nextBatch.sourceIndices[0]).toBe(7)
    })

    it('seek with backward search converges', () => {
        const store = new SnapshotStore()
        store.setSources(makeSources(55))

        // Seek to middle with FullSnapshot at source 25
        const batches = runLoadingLoop(store, {
            snapshotFactory: (i) =>
                i === 25
                    ? [makeFullSnapshot(tsForMinute(i)), makeSnapshot(tsForMinute(i) + 100)]
                    : [makeSnapshot(tsForMinute(i))],
            target: { timestamp: tsForMinute(30) },
            batchSize: 10,
            playbackPosition: tsForMinute(30),
            maxIterations: 20,
        })

        // Should converge within the iteration limit (not hit maxIterations)
        expect(batches.length).toBeLessThan(20)
    })

    it('live source growth mid-loading preserves progress and continues', () => {
        const store = new SnapshotStore()
        store.setSources(makeSources(5))

        // Load the first 5 sources
        runLoadingLoop(store, {
            snapshotFactory: (i) =>
                i === 0
                    ? [makeFullSnapshot(tsForMinute(i)), makeSnapshot(tsForMinute(i) + 100)]
                    : [makeSnapshot(tsForMinute(i))],
            batchSize: 5,
        })

        expect(store.allLoaded).toBe(true)
        const snapshotCountBefore = allLoadedSnapshots(store).length

        // Live recording adds 3 new sources
        store.setSources(makeSources(8))

        expect(store.sourceCount).toBe(8)
        expect(store.allLoaded).toBe(false)
        // Previously loaded sources still loaded
        for (let i = 0; i < 5; i++) {
            expect(store.getEntry(i)?.state).toBe('loaded')
        }
        // Previously loaded snapshots still present
        expect(allLoadedSnapshots(store).length).toBe(snapshotCountBefore)

        // The planner picks up the new unloaded sources
        const newBatches = runLoadingLoop(store, {
            snapshotFactory: (i) => [makeSnapshot(tsForMinute(i))],
            batchSize: 5,
        })

        expect(newBatches.length).toBeGreaterThan(0)
        expect(newBatches[0].sourceIndices[0]).toBe(5)
        expect(store.allLoaded).toBe(true)
    })

    describe('SnapshotStore + segment kind derivation', () => {
        function makeActiveSnapshot(timestamp: number, windowId: number = 1): RecordingSnapshot {
            return {
                timestamp,
                windowId,
                type: EventType.IncrementalSnapshot,
                data: { source: IncrementalSource.MouseMove },
            } as unknown as RecordingSnapshot
        }

        function buildSegments(store: SnapshotStore, sourceCount: number): RecordingSegment[] {
            const snapshots = allLoadedSnapshots(store)
            const snapshotsByWindowId = mapSnapshotsToWindowId(snapshots)
            const start = { valueOf: () => tsForMinute(0) } as any
            const end = { valueOf: () => tsForMinute(sourceCount) } as any
            return createSegments(snapshots, start, end, undefined, snapshotsByWindowId, (a, b) =>
                store.isRangeLoaded(a, b)
            )
        }

        it('forward seek leaves unloaded region — gaps convert to buffer', () => {
            const store = new SnapshotStore()
            store.setSources(makeSources(50))

            // Seek to minute 30, loading sources around it
            runLoadingLoop(store, {
                snapshotFactory: (i) =>
                    i === 28
                        ? [makeFullSnapshot(tsForMinute(i)), makeActiveSnapshot(tsForMinute(i) + 100)]
                        : [makeActiveSnapshot(tsForMinute(i))],
                target: { timestamp: tsForMinute(30) },
                batchSize: 10,
            })

            const converted = buildSegments(store, 50)

            // Segments covering the unloaded region (minutes 0-27) should be buffer, not gap
            const earlySegments = converted.filter((s) => s.startTimestamp < tsForMinute(27))
            for (const seg of earlySegments) {
                if (seg.kind === 'gap') {
                    // A gap in the unloaded region means the player would skip —
                    // it should have been converted to buffer
                    expect(seg.kind).not.toBe('gap')
                }
            }
            // At least one buffer segment exists in the unloaded region
            expect(earlySegments.some((s) => s.kind === 'buffer')).toBe(true)
        })

        it('all sources loaded — trailing buffer converts to gap', () => {
            const store = new SnapshotStore()
            store.setSources(makeSources(10))

            for (let i = 0; i < 10; i++) {
                markLoaded(store, i, [i === 0 ? makeFullSnapshot(tsForMinute(i)) : makeActiveSnapshot(tsForMinute(i))])
            }

            const converted = buildSegments(store, 10)

            // No buffer segments should remain — everything is loaded
            expect(converted.some((s) => s.kind === 'buffer')).toBe(false)
        })

        it('new sources arrive — new region is buffer, old region unchanged', () => {
            const store = new SnapshotStore()
            store.setSources(makeSources(10))

            // Load all 10 sources
            for (let i = 0; i < 10; i++) {
                markLoaded(store, i, [i === 0 ? makeFullSnapshot(tsForMinute(i)) : makeActiveSnapshot(tsForMinute(i))])
            }

            const beforeGrowth = buildSegments(store, 10)
            expect(beforeGrowth.some((s) => s.kind === 'buffer')).toBe(false)

            // Live growth: 5 new sources arrive
            store.setSources(makeSources(15))
            const afterGrowth = buildSegments(store, 15)

            // The new region (minutes 10-14) should have buffer segments
            const newRegionSegments = afterGrowth.filter((s) => s.endTimestamp > tsForMinute(10))
            expect(newRegionSegments.some((s) => s.kind === 'buffer')).toBe(true)
        })
    })

    describe('getUnloadedIndicesInRange detects gaps for segment conversion', () => {
        it('reports unloaded sources in a region skipped by forward seek', () => {
            const store = new SnapshotStore()
            store.setSources(makeSources(50))

            // Seek forward to minute 30, loading sources 27-49
            runLoadingLoop(store, {
                snapshotFactory: (i) =>
                    i === 28
                        ? [makeFullSnapshot(tsForMinute(i)), makeSnapshot(tsForMinute(i) + 100)]
                        : [makeSnapshot(tsForMinute(i))],
                target: { timestamp: tsForMinute(30) },
                batchSize: 10,
            })

            // Sources 0-26 are still unloaded — this is the gap the user would seek back into
            const startIdx = store.getSourceIndexForTimestamp(tsForMinute(5))!
            const endIdx = store.getSourceIndexForTimestamp(tsForMinute(20))!
            const unloaded = store.getUnloadedIndicesInRange(startIdx, endIdx)
            expect(unloaded.length).toBeGreaterThan(0)

            // The coordinator's segment selector uses this to convert gap → buffer,
            // ensuring the player pauses instead of skipping over unloaded data
        })

        it('reports no unloaded sources in a fully-loaded region', () => {
            const store = new SnapshotStore()
            store.setSources(makeSources(10))

            // Load all sources
            for (let i = 0; i < 10; i++) {
                markLoaded(store, i, [i === 0 ? makeFullSnapshot(tsForMinute(i)) : makeSnapshot(tsForMinute(i))])
            }

            // All loaded — gaps here are real inactivity, not pending data
            const startIdx = store.getSourceIndexForTimestamp(tsForMinute(3))!
            const endIdx = store.getSourceIndexForTimestamp(tsForMinute(7))!
            expect(store.getUnloadedIndicesInRange(startIdx, endIdx).length).toBe(0)
        })
    })
})
