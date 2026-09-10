import { LoadBatch, SnapshotStore } from '@posthog/replay-shared'

const DEFAULT_BATCH_SIZE = 10
const BUFFER_AHEAD_SOURCES = 30
const SEEK_WINDOW_BEHIND = 3
const SEEK_WINDOW_AHEAD = 7

export interface SeekTarget {
    timestamp: number
    windowId?: number
}

export interface LoadPlanInput {
    // the position the player wants to render but cannot yet — ignored once the store can play it
    target: SeekTarget | null
    loadAll: boolean
    playbackPosition?: number
    playbackWindowId?: number
}

// Pure planner: recomputed from scratch on every call, so it carries no cursors or modes and converges because the store's loaded set only grows.
export function planNextBatch(
    store: SnapshotStore,
    { target, loadAll, playbackPosition, playbackWindowId }: LoadPlanInput,
    batchSize: number = DEFAULT_BATCH_SIZE
): LoadBatch | null {
    if (store.sourceCount === 0) {
        return null
    }

    if (loadAll) {
        const unloaded = store.getUnfetchedIndicesInRange(0, store.sourceCount - 1)
        if (unloaded.length === 0) {
            return null
        }
        return { sourceIndices: truncateToContiguous(unloaded.slice(0, batchSize)), reason: 'load_all' }
    }

    if (target && !store.canPlayAt(target.timestamp, target.windowId)) {
        const seekBatch = planSeekBatch(store, target, batchSize)
        if (seekBatch) {
            return seekBatch
        }
    }

    return planBufferAheadBatch(store, batchSize, playbackPosition ?? target?.timestamp, playbackWindowId)
}

function planSeekBatch(store: SnapshotStore, { timestamp, windowId }: SeekTarget, batchSize: number): LoadBatch | null {
    const targetIndex = store.getSourceIndexForTimestamp(timestamp)
    if (targetIndex === null) {
        return null
    }
    const windowStart = Math.max(0, targetIndex - SEEK_WINDOW_BEHIND)
    const windowEnd = Math.min(store.sourceCount - 1, targetIndex + SEEK_WINDOW_AHEAD)

    // Step 1: load the window around the target.
    const unloadedInWindow = store.getUnfetchedIndicesInRange(windowStart, windowEnd)
    if (unloadedInWindow.length > 0) {
        return { sourceIndices: truncateToContiguous(unloadedInWindow.slice(0, batchSize)), reason: 'seek_target' }
    }

    // Step 2: fill the span between the nearest usable FullSnapshot and the target, closest to the target first.
    const nearestFull = store.findNearestFullSnapshot(timestamp, windowId)
    if (nearestFull) {
        const gapIndices = store.getUnfetchedIndicesInRange(nearestFull.sourceIndex, targetIndex)
        if (gapIndices.length > 0) {
            return { sourceIndices: truncateToContiguous(gapIndices.slice(-batchSize)), reason: 'seek_gap_fill' }
        }
        return null
    }

    // Step 3: no FullSnapshot at or before the target is loaded — hunt backward, closest sources first.
    const backwardIndices = store.getUnfetchedIndicesInRange(0, windowStart - 1)
    if (backwardIndices.length > 0) {
        return { sourceIndices: truncateToContiguous(backwardIndices.slice(-batchSize)), reason: 'seek_backward' }
    }

    // Step 4: nothing before the target can help, so recovery must come from a later FullSnapshot in the target's window — keep loading forward until one is known.
    if (!store.hasFullSnapshotAfter(timestamp, windowId)) {
        const forwardIndices = store.getUnfetchedIndicesInRange(windowEnd + 1, store.sourceCount - 1)
        if (forwardIndices.length > 0) {
            return { sourceIndices: truncateToContiguous(forwardIndices.slice(0, batchSize)), reason: 'seek_forward' }
        }
    }

    return null
}

function planBufferAheadBatch(
    store: SnapshotStore,
    batchSize: number,
    playbackPosition?: number,
    playbackWindowId?: number
): LoadBatch | null {
    let anchorIndex = 0
    if (playbackPosition !== undefined) {
        const index = store.getSourceIndexForTimestamp(playbackPosition)
        if (index === null) {
            return null
        }
        anchorIndex = index
    }

    const bufferEnd = Math.min(store.sourceCount - 1, anchorIndex + BUFFER_AHEAD_SOURCES - 1)
    const aheadIndices = store.getUnfetchedIndicesInRange(anchorIndex, bufferEnd)
    if (aheadIndices.length > 0) {
        return { sourceIndices: truncateToContiguous(aheadIndices.slice(0, batchSize)), reason: 'buffer_ahead' }
    }

    // A playhead with no usable FullSnapshot before it and none loaded after it can't progress to pull the buffer window along, so scan forward until a recovery FullSnapshot is known (with a later one already loaded the player clamps to it, and a paused-at-start playhead parked epsilon-before its window's first FullSnapshot must not sweep the whole recording).
    if (
        playbackPosition !== undefined &&
        store.findNearestFullSnapshot(playbackPosition, playbackWindowId) === null &&
        !store.hasFullSnapshotAfter(playbackPosition, playbackWindowId)
    ) {
        const forwardIndices = store.getUnfetchedIndicesInRange(bufferEnd + 1, store.sourceCount - 1)
        if (forwardIndices.length > 0) {
            return { sourceIndices: truncateToContiguous(forwardIndices.slice(0, batchSize)), reason: 'seek_forward' }
        }
    }

    return null
}

function truncateToContiguous(indices: number[]): number[] {
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
