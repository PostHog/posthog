import { InactivityPeriod } from './types'

/**
 * Place each period on the video clock from the timeline measured during capture.
 *
 * `frameSessionMs[i]` is where playback was on captured frame `i`, and one captured frame is one
 * frame of the rendered video, so a period's video position is the frame range whose session times
 * fall inside it. Measuring beats deriving: a skip costs the frame it happens on, and any frame
 * spent elsewhere counts too, neither of which segment durations can predict.
 */
export function videoTimestampsFromFrames(
    periods: InactivityPeriod[],
    frameSessionMs: number[],
    fps: number,
    preRollFrames = 0
): InactivityPeriod[] {
    if (frameSessionMs.length === 0 || fps <= 0) {
        return computeVideoTimestamps(periods)
    }
    // Sample `i` is the frame `preRollFrames + i` of the file: capture runs while the player is still
    // starting, and those frames carry no sample.
    const videoTimeOf = (sample: number): number => (preRollFrames + sample) / fps
    const lastPeriod = periods.length - 1
    // A render can start or stop partway through a stretch, via start_offset_s, a trim, or a timeout.
    // The stretch then spans session time the file never shows, and a consumer interpolating across it
    // reads every moment inside as later than it is. Hold those two edges to what was captured.
    const firstSampleS = frameSessionMs[0] / 1000
    const lastSampleS = frameSessionMs[frameSessionMs.length - 1] / 1000
    return periods.map((period, index) => {
        const fromMs = period.ts_from_s * 1000
        const toMs = period.ts_to_s != null ? period.ts_to_s * 1000 : Number.POSITIVE_INFINITY
        // Half-open, so a frame sitting exactly on a boundary belongs to the period it starts, not the
        // one it ends. The last period takes its own end, or the final frame would belong to nothing.
        const owns = (t: number): boolean => t >= fromMs && (t < toMs || (index === lastPeriod && t <= toMs))
        let first = -1
        let last = -1
        for (let i = 0; i < frameSessionMs.length; i++) {
            if (owns(frameSessionMs[i])) {
                if (first === -1) {
                    first = i
                }
                last = i
            } else if (first !== -1) {
                break
            }
        }
        if (first === -1) {
            // Never on screen: sit at the frame where playback resumed. The predicate matches ownership
            // above, so the frame landing exactly on the period's end is found rather than stepped over.
            const resumed = frameSessionMs.findIndex((t) => t >= toMs)
            const at = videoTimeOf(resumed === -1 ? frameSessionMs.length : resumed)
            return { ...period, recording_ts_from_s: at, recording_ts_to_s: at }
        }
        // Only the stretch the capture began in, and the one it ended in, can be cut by it.
        const startsMidPeriod =
            firstSampleS > period.ts_from_s && (period.ts_to_s == null || firstSampleS < period.ts_to_s)
        const endsMidPeriod = period.ts_to_s != null && lastSampleS < period.ts_to_s && lastSampleS >= period.ts_from_s
        return {
            ...period,
            ts_from_s: startsMidPeriod ? firstSampleS : period.ts_from_s,
            ts_to_s: endsMidPeriod ? lastSampleS : period.ts_to_s,
            recording_ts_from_s: videoTimeOf(first),
            recording_ts_to_s: videoTimeOf(last + 1),
        }
    })
}

/**
 * Predicted video-time positions, used when no measured timeline is available.
 *
 * Assumes an inactive period costs no video time, which understates the real video by about a frame
 * per skip. Prefer `videoTimestampsFromFrames`.
 */
export function computeVideoTimestamps(periods: InactivityPeriod[]): InactivityPeriod[] {
    // Pass 1: compute raw video timestamps
    let videoTime = 0
    const results: InactivityPeriod[] = periods.map((period) => {
        if (period.active) {
            const recordingTsFromS = videoTime
            const duration = period.ts_to_s != null ? period.ts_to_s - period.ts_from_s : 0
            videoTime += duration
            return { ...period, recording_ts_from_s: recordingTsFromS, recording_ts_to_s: videoTime }
        } else {
            return { ...period, recording_ts_from_s: videoTime, recording_ts_to_s: videoTime }
        }
    })

    // Pass 2: clamp active periods so they don't overlap the next active period's start
    for (let i = 0; i < results.length; i++) {
        if (!results[i].active) {
            continue
        }
        // Find the next active period
        for (let j = i + 1; j < results.length; j++) {
            if (results[j].active) {
                if (results[i].recording_ts_to_s! > results[j].recording_ts_from_s!) {
                    results[i] = { ...results[i], recording_ts_to_s: results[j].recording_ts_from_s }
                }
                break
            }
        }
    }

    return results
}
