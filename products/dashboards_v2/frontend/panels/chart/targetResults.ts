import type { ChartTarget } from './chartSpec'
import type { QueryFrames } from './useQueryFrames'
import type { DataFrame } from './vizTypes'

export interface TargetFailure {
    refId: string
    message: string
}

export type ChartResult =
    | { status: 'loading' }
    | { status: 'error'; message: string }
    | { status: 'ready'; refreshing: boolean; frames: DataFrame[]; failures: TargetFailure[] }

/**
 * Puts the results of a chart's targets into one. The chart draws as soon as one target has frames, and a target that
 * fails is listed in `failures` while the others still draw. Only when every target fails does the chart show an
 * error. With `tagFrames`, each frame carries its target's `refId`, so series from different targets stay apart.
 */
export function combineTargetResults(targets: ChartTarget[], results: QueryFrames[], tagFrames: boolean): ChartResult {
    const frames: DataFrame[] = []
    const failures: TargetFailure[] = []
    let ready = false
    let waiting = false
    targets.forEach((target, index) => {
        const result = results[index] ?? { status: 'loading' }
        if (result.status === 'loading') {
            waiting = true
        } else if (result.status === 'error') {
            failures.push({ refId: target.refId, message: result.message })
        } else {
            ready = true
            waiting ||= result.refreshing
            frames.push(
                ...(tagFrames ? result.frames.map((frame) => ({ ...frame, refId: target.refId })) : result.frames)
            )
        }
    })
    if (ready) {
        return { status: 'ready', refreshing: waiting, frames, failures }
    }
    if (waiting || targets.length === 0) {
        return { status: 'loading' }
    }
    return {
        status: 'error',
        message:
            failures.length === 1
                ? failures[0].message
                : failures.map((failure) => `${failure.refId}: ${failure.message}`).join(' '),
    }
}
