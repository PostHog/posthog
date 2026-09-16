import { InactivityPeriod, SegmentVideoStart } from './types'

/**
 * Compute video-time positions for each inactivity period.
 *
 * Active periods occupy real time in the video (their session duration maps
 * 1:1 to video duration after slowdown). Inactive periods are skipped by the
 * player and occupy zero video time — their recording_ts values point to the
 * position where the video resumes.
 *
 * `segmentVideoStarts` says where capture really put each segment, so a cut
 * that costs a frame cannot push the rest of the map out of step with the
 * file. Segment math only fills the gaps between those measurements.
 * `videoDurationS` is the length of the file, which the map has to end on.
 */
export function computeVideoTimestamps(
    periods: InactivityPeriod[],
    segmentVideoStarts: SegmentVideoStart[] = [],
    videoDurationS?: number
): InactivityPeriod[] {
    const measured = new Map(segmentVideoStarts.map((start) => [start.index, start.video_s]))
    const end = videoDurationS ?? Infinity

    // Lay the periods on the video axis, restarting from a measured position wherever capture
    // recorded one. Nothing may point past the end of the file.
    let videoTime = 0
    let tail = -1
    const results: InactivityPeriod[] = periods.map((period, index) => {
        videoTime = measured.get(index) ?? videoTime
        const recordingTsFromS = Math.min(videoTime, end)
        if (period.active) {
            videoTime += period.ts_to_s != null ? period.ts_to_s - period.ts_from_s : 0
            if (videoDurationS != null && recordingTsFromS < end) {
                tail = index
            }
        }
        return { ...period, recording_ts_from_s: recordingTsFromS, recording_ts_to_s: Math.min(videoTime, end) }
    })

    const nextActive: number[] = []
    for (let i = results.length - 1, seen = -1; i >= 0; i--) {
        seen = results[i].active ? i : seen
        nextActive[i] = seen
    }

    let lastActiveEnd: number | null = null
    for (let i = 0; i < results.length; i++) {
        const after = nextActive[i + 1] ?? -1
        const resumesAt = after === -1 ? null : results[after].recording_ts_from_s!
        if (results[i].active) {
            // A stretch stops where the next one starts, except the last one the video reached:
            // the frames a cut or the capture ramp added still show it, so it runs to the end.
            const to = i === tail ? end : Math.min(results[i].recording_ts_to_s!, resumesAt ?? end)
            results[i] = { ...results[i], recording_ts_to_s: to }
            lastActiveEnd = to
            continue
        }
        // A cut takes no video time, so it collapses onto the frame the video resumes on, or
        // onto the end of the last stretch when nothing follows it.
        const at = resumesAt ?? lastActiveEnd
        if (at != null) {
            results[i] = { ...results[i], recording_ts_from_s: at, recording_ts_to_s: at }
        }
    }

    return results
}
