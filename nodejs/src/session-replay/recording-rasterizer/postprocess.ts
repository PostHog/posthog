import { InactivityPeriod } from './types'

/**
 * Compute video-time positions for each inactivity period.
 *
 * Active periods occupy real time in the video (their session duration maps
 * 1:1 to video duration after slowdown). Inactive periods are skipped by the
 * player and occupy zero video time — their recording_ts values point to the
 * same position where the previous active period ended.
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
