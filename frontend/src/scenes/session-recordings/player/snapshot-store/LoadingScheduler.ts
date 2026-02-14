import { SnapshotStore } from './SnapshotStore'
import { LoadBatch, Mode } from './types'

const DEFAULT_BATCH_SIZE = 10
const BUFFER_AHEAD_SOURCES = 30

export class LoadingScheduler {
    private mode: Mode = { kind: 'buffer_ahead' }
    private seekRangeEnd: number | null = null
    private seekRangeStart: number | null = null

    seekTo(targetTimestamp: number): void {
        this.mode = { kind: 'seek', targetTimestamp }
        this.seekRangeEnd = null
        this.seekRangeStart = null
    }

    clearSeek(): void {
        this.mode = { kind: 'buffer_ahead' }
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

        return this.getBufferAheadBatch(store, batchSize, playbackPosition)
    }

    get isSeeking(): boolean {
        return this.mode.kind === 'seek'
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
                sourceIndices: this.truncateToContiguous(unloadedInWindow.slice(0, batchSize)),
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

        // Step 2: If can play, clear seek and switch to buffer_ahead
        if (store.canPlayAt(targetTs)) {
            this.clearSeek()
            return this.getBufferAheadBatch(store, batchSize)
        }

        // Step 3: Need FullSnapshot. Find nearest and fill gap.
        const nearestFull = store.findNearestFullSnapshot(targetTs)
        if (nearestFull) {
            // Fill gap between FullSnapshot source and the start of our loaded range
            const gapIndices = store.getUnloadedIndicesInRange(nearestFull.sourceIndex, targetIndex)
            if (gapIndices.length > 0) {
                // Load the unloaded sources closest to target first (from the end of the gap)
                const batch = this.truncateToContiguous(gapIndices.slice(-batchSize))
                this.seekRangeStart = Math.min(this.seekRangeStart ?? batch[0], batch[0])
                return {
                    sourceIndices: batch,
                    reason: 'seek_gap_fill',
                }
            }
        }

        // Step 4: No FullSnapshot found yet, search backward.
        // Loop through ranges to skip over already-loaded sections.
        let currentStart = this.seekRangeStart ?? targetIndex
        while (currentStart > 0) {
            const searchStart = Math.max(0, currentStart - batchSize)
            const searchEnd = currentStart - 1

            const backwardIndices = store.getUnloadedIndicesInRange(searchStart, searchEnd)
            if (backwardIndices.length > 0) {
                this.seekRangeStart = searchStart
                return {
                    sourceIndices: this.truncateToContiguous(backwardIndices.slice(0, batchSize)),
                    reason: 'seek_backward',
                }
            }
            // All sources in this range are loaded — advance past them
            currentStart = searchStart
        }
        this.seekRangeStart = 0

        // Step 5: Exhausted backward search without finding a FullSnapshot. Give up.
        this.clearSeek()
        return this.getBufferAheadBatch(store, batchSize)
    }

    private getBufferAheadBatch(store: SnapshotStore, batchSize: number, playbackPosition?: number): LoadBatch | null {
        const anchorIndex =
            playbackPosition !== undefined
                ? store.getSourceIndexForTimestamp(playbackPosition)
                : (this.seekRangeEnd ?? 0)

        const bufferEnd = Math.min(store.sourceCount - 1, anchorIndex + BUFFER_AHEAD_SOURCES)
        const aheadIndices = store.getUnloadedIndicesInRange(anchorIndex, bufferEnd)
        if (aheadIndices.length > 0) {
            return {
                sourceIndices: this.truncateToContiguous(aheadIndices.slice(0, batchSize)),
                reason: 'buffer_ahead',
            }
        }

        return null
    }

    private truncateToContiguous(indices: number[]): number[] {
        if (indices.length <= 1) {
            return indices
        }
        const result = [indices[0]]
        for (let i = 1; i < indices.length; i++) {
            if (indices[i] !== indices[i - 1] + 1) {
                break
            }
            result.push(indices[i])
        }
        return result
    }
}
