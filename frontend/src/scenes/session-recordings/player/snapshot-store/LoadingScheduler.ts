import { SnapshotStore } from './SnapshotStore'
import { LoadBatch, Mode } from './types'

const DEFAULT_BATCH_SIZE = 10
const MAX_BUFFER_AHEAD_MS = 60 * 60 * 1000 // 1 hour of recording time

export class LoadingScheduler {
    private mode: Mode = { kind: 'sequential' }
    private seekRangeEnd: number | null = null
    private seekRangeStart: number | null = null

    seekTo(targetTimestamp: number): void {
        this.mode = { kind: 'seek', targetTimestamp }
        this.seekRangeEnd = null
        this.seekRangeStart = null
    }

    clearSeek(): void {
        // Preserve seek range info for sequential continuation
        this.mode = { kind: 'sequential' }
    }

    get currentMode(): Mode {
        return this.mode
    }

    getNextBatch(
        store: SnapshotStore,
        batchSize: number = DEFAULT_BATCH_SIZE,
        playbackPosition?: number
    ): LoadBatch | null {
        if (store.sourceCount === 0) {
            return null
        }

        if (this.mode.kind === 'seek') {
            return this.getSeekBatch(store, batchSize)
        }

        return this.getSequentialBatch(store, batchSize, playbackPosition)
    }

    onBatchLoaded(): void {
        // no-op: reserved for future metric tracking
    }

    private getSeekBatch(store: SnapshotStore, batchSize: number): LoadBatch | null {
        if (this.mode.kind !== 'seek') {
            return null
        }
        const targetTs = this.mode.targetTimestamp

        // Step 1: Load window around target if not loaded
        const targetIndex = store.getSourceIndexForTimestamp(targetTs)
        const windowStart = Math.max(0, targetIndex - 2)
        const windowEnd = Math.min(store.sourceCount - 1, targetIndex + 7)

        const unloadedInWindow = store.getUnloadedIndicesInRange(windowStart, windowEnd)
        if (unloadedInWindow.length > 0) {
            this.seekRangeStart = windowStart
            this.seekRangeEnd = windowEnd
            return {
                sourceIndices: unloadedInWindow.slice(0, batchSize),
                reason: 'seek_target',
            }
        }

        // Ensure range tracking is set
        if (this.seekRangeStart === null) {
            this.seekRangeStart = windowStart
        }
        if (this.seekRangeEnd === null) {
            this.seekRangeEnd = windowEnd
        }

        // Step 2: If can play, clear seek and switch to sequential
        if (store.canPlayAt(targetTs)) {
            this.clearSeek()
            return this.getSequentialBatch(store, batchSize)
        }

        // Step 3: Need FullSnapshot. Find nearest and fill gap.
        const nearestFull = store.findNearestFullSnapshot(targetTs)
        if (nearestFull) {
            // Fill gap between FullSnapshot source and the start of our loaded range
            const gapIndices = store.getUnloadedIndicesInRange(nearestFull.sourceIndex, targetIndex)
            if (gapIndices.length > 0) {
                // Load the unloaded sources closest to target first (from the end of the gap)
                const batch = gapIndices.slice(-batchSize)
                this.seekRangeStart = Math.min(this.seekRangeStart ?? batch[0], batch[0])
                return {
                    sourceIndices: batch,
                    reason: 'seek_gap_fill',
                }
            }
        }

        // Step 4: No FullSnapshot found yet, search backward
        const searchStart = Math.max(0, (this.seekRangeStart ?? targetIndex) - batchSize)
        const searchEnd = (this.seekRangeStart ?? targetIndex) - 1

        if (searchEnd >= 0) {
            const backwardIndices = store.getUnloadedIndicesInRange(searchStart, searchEnd)
            if (backwardIndices.length > 0) {
                this.seekRangeStart = searchStart
                return {
                    sourceIndices: backwardIndices.slice(0, batchSize),
                    reason: 'seek_backward',
                }
            }
        }

        // Step 5: Exhausted backward search without finding a FullSnapshot. Give up.
        this.clearSeek()
        return this.getSequentialBatch(store, batchSize)
    }

    private getSequentialBatch(store: SnapshotStore, batchSize: number, playbackPosition?: number): LoadBatch | null {
        // If we recently did a seek, load forward from seek range end first, then backward to start
        if (this.seekRangeEnd !== null) {
            // Forward from seek range end
            const forwardIndices = store.getUnloadedIndicesInRange(this.seekRangeEnd + 1, store.sourceCount - 1)
            if (forwardIndices.length > 0) {
                return {
                    sourceIndices: forwardIndices.slice(0, batchSize),
                    reason: 'forward_from_seek',
                }
            }

            // Backward to start
            if (this.seekRangeStart !== null && this.seekRangeStart > 0) {
                const backwardIndices = store.getUnloadedIndicesInRange(0, this.seekRangeStart - 1)
                if (backwardIndices.length > 0) {
                    // Load closest to seek range first
                    const batch = backwardIndices.slice(-batchSize)
                    return {
                        sourceIndices: batch,
                        reason: 'backward_to_start',
                    }
                }
            }

            // All done with seek-continuation loading
            this.seekRangeEnd = null
            this.seekRangeStart = null
        }

        // Buffer-ahead throttle: if loaded data is >1 hour ahead of playback, pause
        if (playbackPosition !== undefined) {
            const lastLoadedEnd = this.getLastLoadedEndMs(store)
            if (lastLoadedEnd !== null && lastLoadedEnd - playbackPosition > MAX_BUFFER_AHEAD_MS) {
                return null
            }
        }

        // Load next unloaded sources from the beginning
        const unloaded = store.getUnloadedIndicesInRange(0, store.sourceCount - 1)
        if (unloaded.length > 0) {
            return {
                sourceIndices: unloaded.slice(0, batchSize),
                reason: 'sequential',
            }
        }

        return null
    }

    private getLastLoadedEndMs(store: SnapshotStore): number | null {
        let maxEnd = -1
        for (let i = 0; i < store.sourceCount; i++) {
            const entry = store.getEntry(i)
            if (entry?.state === 'loaded' && entry.endMs > maxEnd) {
                maxEnd = entry.endMs
            }
        }
        return maxEnd === -1 ? null : maxEnd
    }
}
