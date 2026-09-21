import { RecordingSegment } from '~/types'

// rrweb sometimes stops advancing the playhead. The player recovers by nudging the playhead past
// the blockage, but a nudge of one animation frame only clears a blockage shorter than a frame, so
// a longer one re-arms the stall detector at once and the player crawls instead of playing. Each
// consecutive nudge is therefore larger than the last, and the burst ends after a bounded number
// of them.
export const MAX_STALL_RECOVERY_ATTEMPTS = 5
const MIN_STALL_SKIP_MS = 250
const MAX_STALL_SKIP_MS = 10_000
// Attempts inside one burst land a few frames apart. A longer gap means playback ran again, so the
// next stall is a new burst and starts from the smallest skip.
const STALL_BURST_GAP_MS = 3000

export type StallRecovery =
    | { kind: 'skip'; skipMs: number }
    | { kind: 'seekToSegment'; timestamp: number }
    | { kind: 'giveUp' }

export function resolveStallRecovery(
    attempt: number,
    roughAnimationFPS: number,
    currentTimestamp: number | undefined,
    segments: RecordingSegment[]
): StallRecovery {
    if (attempt < MAX_STALL_RECOVERY_ATTEMPTS) {
        const base = Math.max(roughAnimationFPS, MIN_STALL_SKIP_MS)
        return { kind: 'skip', skipMs: Math.min(base * 2 ** attempt, MAX_STALL_SKIP_MS) }
    }

    const nextSegment =
        currentTimestamp === undefined
            ? undefined
            : segments.find((segment) => segment.startTimestamp > currentTimestamp)

    return nextSegment ? { kind: 'seekToSegment', timestamp: nextSegment.startTimestamp } : { kind: 'giveUp' }
}

export function continuesStallBurst(lastAttemptAt: number | null, at: number): boolean {
    return lastAttemptAt !== null && at - lastAttemptAt < STALL_BURST_GAP_MS
}
