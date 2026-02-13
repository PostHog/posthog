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
    describe('sequential mode', () => {
        it('starts in sequential mode', () => {
            const scheduler = new LoadingScheduler()
            expect(scheduler.currentMode).toEqual({ kind: 'sequential' })
        })

        it('returns first unloaded batch from the beginning', () => {
            const store = createLoadedStore(10, [])
            const scheduler = new LoadingScheduler()

            const batch = scheduler.getNextBatch(store, 3)
            expect(batch).toEqual({
                sourceIndices: [0, 1, 2],
                reason: 'sequential',
            })
        })

        it('skips already loaded sources', () => {
            const store = createLoadedStore(10, [0, 1, 2])
            const scheduler = new LoadingScheduler()

            const batch = scheduler.getNextBatch(store, 3)
            expect(batch).toEqual({
                sourceIndices: [3, 4, 5],
                reason: 'sequential',
            })
        })

        it('returns null when all sources are loaded', () => {
            const store = createLoadedStore(3, [0, 1, 2])
            const scheduler = new LoadingScheduler()

            expect(scheduler.getNextBatch(store)).toBeNull()
        })

        it('returns null when store is empty', () => {
            const store = new SnapshotStore()
            const scheduler = new LoadingScheduler()

            expect(scheduler.getNextBatch(store)).toBeNull()
        })
    })

    describe('buffer-ahead throttle', () => {
        it('pauses when loaded data is >1 hour ahead of playback', () => {
            const store = new SnapshotStore()
            // 120 sources = 2 hours
            store.setSources(makeSources(120))
            // Load first 70 sources (just over 1 hour)
            for (let i = 0; i < 70; i++) {
                store.markLoaded(i, [makeSnapshot(tsForMinute(i))])
            }

            const scheduler = new LoadingScheduler()
            const playbackPos = tsForMinute(0) // at the very start

            const batch = scheduler.getNextBatch(store, 10, playbackPos)
            expect(batch).toBeNull()
        })

        it('does not pause when buffer is under 1 hour', () => {
            const store = new SnapshotStore()
            store.setSources(makeSources(120))
            // Load first 50 sources (50 minutes)
            for (let i = 0; i < 50; i++) {
                store.markLoaded(i, [makeSnapshot(tsForMinute(i))])
            }

            const scheduler = new LoadingScheduler()
            const playbackPos = tsForMinute(0)

            const batch = scheduler.getNextBatch(store, 10, playbackPos)
            expect(batch).not.toBeNull()
            expect(batch?.reason).toBe('sequential')
        })

        it('resumes when playback catches up', () => {
            const store = new SnapshotStore()
            store.setSources(makeSources(120))
            for (let i = 0; i < 70; i++) {
                store.markLoaded(i, [makeSnapshot(tsForMinute(i))])
            }

            const scheduler = new LoadingScheduler()

            // Pauses at start
            expect(scheduler.getNextBatch(store, 10, tsForMinute(0))).toBeNull()

            // Resumes when playback is at minute 30 (only 40 min ahead)
            const batch = scheduler.getNextBatch(store, 10, tsForMinute(30))
            expect(batch).not.toBeNull()
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

            const batch = scheduler.getNextBatch(store, 10)
            expect(batch?.reason).toBe('seek_target')
            // Window: [target-2, target+7] = [8, 17]
            expect(batch?.sourceIndices[0]).toBe(8)
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

        it('clears seek and switches to sequential when canPlayAt is true', () => {
            // Load sources 0-12 (covers seek window [3,12]) with FullSnapshot at source 0
            const loaded = Array.from({ length: 13 }, (_, i) => i)
            const store = createLoadedStore(20, loaded, [0])
            const scheduler = new LoadingScheduler()
            scheduler.seekTo(tsForMinute(5))

            const batch = scheduler.getNextBatch(store, 10)
            // Should have cleared seek since we can play at minute 5
            expect(scheduler.currentMode).toEqual({ kind: 'sequential' })
            // And returned a sequential continuation batch
            expect(batch?.reason).toBe('forward_from_seek')
        })

        it('fills gap between FullSnapshot and target', () => {
            // Source 0 has FullSnapshot, sources 0 + 5-17 loaded, gap at 1-4
            const loaded = [0, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15, 16, 17]
            const store = createLoadedStore(20, loaded, [0])
            const scheduler = new LoadingScheduler()
            scheduler.seekTo(tsForMinute(10))

            // Target window [8,17] is fully loaded, but canPlayAt fails due to gap 1-4
            const batch = scheduler.getNextBatch(store, 10)
            expect(batch?.reason).toBe('seek_gap_fill')
            expect(batch?.sourceIndices).toContain(1)
            expect(batch?.sourceIndices).toContain(4)
        })

        it('searches backward when no FullSnapshot found', () => {
            // Sources 8-17 loaded (covers seek window) but no FullSnapshot anywhere
            const loaded = [8, 9, 10, 11, 12, 13, 14, 15, 16, 17]
            const store = createLoadedStore(20, loaded, [])
            const scheduler = new LoadingScheduler()
            scheduler.seekTo(tsForMinute(10))

            // Target window [8,17] is fully loaded, canPlayAt fails (no FullSnapshot)
            const batch = scheduler.getNextBatch(store, 10)
            expect(batch?.reason).toBe('seek_backward')
            expect(batch?.sourceIndices.every((i) => i < 8)).toBe(true)
        })

        it('gives up and falls to sequential when backward search exhausted', () => {
            // All sources loaded but no FullSnapshot
            const allIndices = Array.from({ length: 20 }, (_, i) => i)
            const store = createLoadedStore(20, allIndices, [])
            const scheduler = new LoadingScheduler()
            scheduler.seekTo(tsForMinute(10))

            const batch = scheduler.getNextBatch(store, 10)
            // Should have given up since no FullSnapshot exists
            expect(scheduler.currentMode).toEqual({ kind: 'sequential' })
            // Should return null since all sources are loaded
            expect(batch).toBeNull()
        })
    })

    describe('sequential continuation after seek', () => {
        it('loads forward from seek range end first', () => {
            // Load sources 0-15 (covers seek window [6,15] and FullSnapshot at 0)
            const loaded = Array.from({ length: 16 }, (_, i) => i)
            const store = createLoadedStore(20, loaded, [0])
            const scheduler = new LoadingScheduler()
            scheduler.seekTo(tsForMinute(8))

            // canPlayAt = true (FullSnapshot at 0, continuous to 8), clears seek
            const batch = scheduler.getNextBatch(store, 5)
            expect(scheduler.currentMode).toEqual({ kind: 'sequential' })
            expect(batch?.reason).toBe('forward_from_seek')
            // Loads forward from seek range end (15) + 1
            expect(batch?.sourceIndices).toEqual([16, 17, 18, 19])
        })

        it('then loads backward to start', () => {
            // Sources 3-19 loaded with FullSnapshot at 3, sources 0-2 unloaded
            const loaded = Array.from({ length: 17 }, (_, i) => i + 3)
            const store = createLoadedStore(20, loaded, [3])
            const scheduler = new LoadingScheduler()
            scheduler.seekTo(tsForMinute(8))

            // canPlayAt = true (FullSnapshot at 3, continuous to 8)
            // All forward sources (16-19) loaded, so goes backward
            const batch = scheduler.getNextBatch(store, 10)
            expect(batch?.reason).toBe('backward_to_start')
            expect(batch?.sourceIndices).toEqual([0, 1, 2])
        })
    })

    describe('clearSeek', () => {
        it('switches back to sequential mode', () => {
            const scheduler = new LoadingScheduler()
            scheduler.seekTo(tsForMinute(5))
            scheduler.clearSeek()
            expect(scheduler.currentMode).toEqual({ kind: 'sequential' })
        })
    })

    describe('onBatchLoaded', () => {
        it('does not throw', () => {
            const scheduler = new LoadingScheduler()
            expect(() => scheduler.onBatchLoaded()).not.toThrow()
        })
    })
})
