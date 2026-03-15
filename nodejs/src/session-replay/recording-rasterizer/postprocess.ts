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
    let videoTime = 0
    let prevActive: InactivityPeriod | null = null

    return periods.map((period) => {
        if (period.active) {
            const recordingTsFromS = videoTime
            const duration = period.ts_to_s != null ? period.ts_to_s - period.ts_from_s : 0
            videoTime += duration

            const result: InactivityPeriod = {
                ...period,
                recording_ts_from_s: recordingTsFromS,
                recording_ts_to_s: videoTime,
            }

            // Clamp previous active period's end to not overlap
            if (prevActive && prevActive.recording_ts_to_s! > recordingTsFromS) {
                prevActive.recording_ts_to_s = recordingTsFromS
            }
            prevActive = result
            return result
        } else {
            // Inactive periods have zero video duration
            return {
                ...period,
                recording_ts_from_s: videoTime,
                recording_ts_to_s: videoTime,
            }
        }
    })
}
