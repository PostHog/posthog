// How long the rrweb clock can fail to progress before we nudge the playhead forward.
// Time-based, not frame-based: an rrweb clock that jitters around a fixed point changes
// value every frame without advancing, so a "same value N times" counter never trips.
export const STUCK_TIME_THRESHOLD_MS = 1000

export interface FrameState {
    lastProgressTimestamp: number | undefined
    lastProgressAt: number | undefined
}

export interface FrameResult {
    resolvedTimestamp: number | undefined
    newState: FrameState
    shouldManuallyAdvance: boolean
}

export function resolveFrameTimestamp(
    rrwebTimestamp: number | undefined,
    currentTimestamp: number | undefined,
    segmentKind: 'window' | 'gap' | 'buffer' | undefined,
    roughAnimationFPS: number,
    previousState: FrameState,
    now: number
): FrameResult {
    // A frame counts as progress only when the rrweb clock moves past the highest point we saw.
    // Jitter below that point is not progress, so the stuck timer keeps running.
    const hasProgressed =
        rrwebTimestamp !== undefined &&
        (previousState.lastProgressTimestamp === undefined || rrwebTimestamp > previousState.lastProgressTimestamp)

    let newState: FrameState
    if (hasProgressed) {
        newState = { lastProgressTimestamp: rrwebTimestamp, lastProgressAt: now }
    } else if (previousState.lastProgressAt === undefined) {
        // Start the stuck timer on the first frame that does not progress (e.g. an undefined rrweb time).
        newState = { lastProgressTimestamp: previousState.lastProgressTimestamp, lastProgressAt: now }
    } else {
        newState = previousState
    }

    const isStuck = now - (newState.lastProgressAt ?? now) >= STUCK_TIME_THRESHOLD_MS
    const shouldManuallyAdvance = (rrwebTimestamp === undefined && segmentKind === 'gap') || isStuck

    let resolvedTimestamp = rrwebTimestamp
    if (shouldManuallyAdvance && currentTimestamp) {
        resolvedTimestamp = currentTimestamp + roughAnimationFPS
    }

    return { resolvedTimestamp, newState, shouldManuallyAdvance }
}

export function initialFrameState(): FrameState {
    return { lastProgressTimestamp: undefined, lastProgressAt: undefined }
}
