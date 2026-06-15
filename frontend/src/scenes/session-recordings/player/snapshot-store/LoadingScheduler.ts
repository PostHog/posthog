import { LoadBatch, Mode, SnapshotStore } from '@posthog/replay-shared'

const DEFAULT_BATCH_SIZE = 10
const BUFFER_AHEAD_SOURCES = 30
const SEEK_WINDOW_BEHIND = 3
const SEEK_WINDOW_AHEAD = 7

export class LoadingScheduler {
    private mode: Mode = { kind: 'buffer_ahead' }
    private seekRangeEnd: number | null = null
    private seekRangeStart: number | null = null

    seekTo(targetTimestamp: number, targetWindowId?: number): void {
        this.mode = { kind: 'seek', targetTimestamp, targetWindowId }
        this.seekRangeEnd = null
        this.seekRangeStart = null
    }

    clearSeek(): void {
        this.mode = { kind: 'buffer_ahead' }
    }

    loadAll(): void {
        this.mode = { kind: 'load_all' }
    }

    get currentMode(): Mode {
        return this.mode
    }

    getNextBatch(
        store: SnapshotStore,
        batchSize: number = DEFAULT_BATCH_SIZE,
        playbackPosition?: number,
        playbackWindowId?: number
    ): LoadBatch | null {
        if (store.sourceCount === 0) {
            return null
        }

        if (this.mode.kind === 'seek') {
            return this.getSeekBatch(store, batchSize)
        }

        if (this.mode.kind === 'load_all') {
            return this.getLoadAllBatch(store, batchSize)
        }

        return this.getBufferAheadBatch(store, batchSize, playbackPosition, playbackWindowId)
    }

    get isSeeking(): boolean {
        return this.mode.kind === 'seek'
    }

    private getSeekBatch(store: SnapshotStore, batchSize: number): LoadBatch | null {
        if (this.mode.kind !== 'seek') {
            return null
        }
        const targetTs = this.mode.targetTimestamp
        const targetWindowId = this.mode.targetWindowId

        // Step 1: Load window around target if not loaded.
        const targetIndex = store.getSourceIndexForTimestamp(targetTs)
        if (targetIndex === null) {
            return null
        }
        const windowStart = Math.max(0, targetIndex - SEEK_WINDOW_BEHIND)
        const windowEnd = Math.min(store.sourceCount - 1, targetIndex + SEEK_WINDOW_AHEAD)

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
        if (store.canPlayAt(targetTs, targetWindowId)) {
            this.clearSeek()
            return this.getBufferAheadBatch(store, batchSize)
        }

        // Step 3: Need FullSnapshot. Find nearest and fill gap.
        const nearestFull = store.findNearestFullSnapshot(targetTs, targetWindowId)
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

        // Step 5: Backward search exhausted — no FullSnapshot exists at or before
        // the target, so playback there can only start from one after it (the
        // player clamps the seek to it once known). Keep loading forward until a
        // FullSnapshot for the target's window is found or everything is loaded —
        // another window's FullSnapshot can't render the target.
        const hasRecoveryCandidate = store
            .fullSnapshotsAfter(targetTs)
            .some((fs) => targetWindowId === undefined || fs.windowId === targetWindowId)
        if (!hasRecoveryCandidate) {
            const forwardIndices = store.getUnloadedIndicesInRange(
                (this.seekRangeEnd ?? targetIndex) + 1,
                store.sourceCount - 1
            )
            if (forwardIndices.length > 0) {
                const batch = this.truncateToContiguous(forwardIndices.slice(0, batchSize))
                this.seekRangeEnd = Math.max(this.seekRangeEnd ?? 0, batch[batch.length - 1])
                return {
                    sourceIndices: batch,
                    reason: 'seek_forward',
                }
            }
        }

        // Step 6: Nothing left to load that could satisfy this seek. Give up.
        this.clearSeek()
        return this.getBufferAheadBatch(store, batchSize)
    }

    private getBufferAheadBatch(
        store: SnapshotStore,
        batchSize: number,
        playbackPosition?: number,
        playbackWindowId?: number
    ): LoadBatch | null {
        let anchorIndex: number
        if (playbackPosition !== undefined) {
            const idx = store.getSourceIndexForTimestamp(playbackPosition)
            if (idx === null) {
                return null
            }
            anchorIndex = idx
        } else {
            anchorIndex = this.seekRangeEnd ?? 0
        }

        const bufferEnd = Math.min(store.sourceCount - 1, anchorIndex + BUFFER_AHEAD_SOURCES - 1)
        const aheadIndices = store.getUnloadedIndicesInRange(anchorIndex, bufferEnd)
        if (aheadIndices.length > 0) {
            return {
                sourceIndices: this.truncateToContiguous(aheadIndices.slice(0, batchSize)),
                reason: 'buffer_ahead',
            }
        }

        // The playhead has nothing to render from (no FullSnapshot at or before it
        // for its window, e.g. lost at capture time) — the player can't progress to
        // pull the buffer window along, so keep scanning forward beyond it until
        // everything is loaded. The player clamps to a recovery FullSnapshot (moving
        // the playhead and ending the scan) as soon as one it can use appears.
        if (
            playbackPosition !== undefined &&
            store.findNearestFullSnapshot(playbackPosition, playbackWindowId) === null
        ) {
            const forwardIndices = store.getUnloadedIndicesInRange(bufferEnd + 1, store.sourceCount - 1)
            if (forwardIndices.length > 0) {
                return {
                    sourceIndices: this.truncateToContiguous(forwardIndices.slice(0, batchSize)),
                    reason: 'seek_forward',
                }
            }
        }

        return null
    }

    private getLoadAllBatch(store: SnapshotStore, batchSize: number): LoadBatch | null {
        const unloaded = store.getUnloadedIndicesInRange(0, store.sourceCount - 1)
        if (unloaded.length === 0) {
            return null
        }
        return {
            sourceIndices: this.truncateToContiguous(unloaded.slice(0, batchSize)),
            reason: 'load_all',
        }
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
