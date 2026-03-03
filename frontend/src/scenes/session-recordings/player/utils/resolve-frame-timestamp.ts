export const STUCK_FRAME_THRESHOLD = 10

export interface FrameState {
    stuckFrames: number
    lastAnimTimestamp: number | undefined
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
    previousState: FrameState
): FrameResult {
    let stuckFrames: number
    if (rrwebTimestamp !== undefined && rrwebTimestamp === previousState.lastAnimTimestamp) {
        stuckFrames = previousState.stuckFrames + 1
    } else {
        stuckFrames = 0
    }

    const newState: FrameState = {
        stuckFrames,
        lastAnimTimestamp: rrwebTimestamp,
    }

    const isStuck = stuckFrames >= STUCK_FRAME_THRESHOLD
    const shouldManuallyAdvance = (rrwebTimestamp === undefined && segmentKind === 'gap') || isStuck

    let resolvedTimestamp = rrwebTimestamp
    if (shouldManuallyAdvance && currentTimestamp) {
        resolvedTimestamp = currentTimestamp + roughAnimationFPS
    }

    return { resolvedTimestamp, newState, shouldManuallyAdvance }
}

export function initialFrameState(): FrameState {
    return { stuckFrames: 0, lastAnimTimestamp: undefined }
}
