export interface ClipDurationOption {
    value: number
    label: string
    'data-attr': string
}

export interface ClipWindow {
    startSeconds: number
    endSeconds: number
}

// Seconds for a moment worth sharing. Anything past a couple of minutes is a different job, and a
// recording long enough to need one is served by the longer options below.
const SHORT_CLIP_SECONDS = [5, 10, 15]
// Minutes, for reviewing part of a recording too long to export whole.
const LONG_CLIP_MINUTES = [1, 5, 15]

export const MIN_CLIP_DURATION_SECONDS = SHORT_CLIP_SECONDS[0]

export function clipDurationOptions(sessionDurationMs: number): ClipDurationOption[] {
    const sessionSeconds = sessionDurationMs / 1000
    const shortOptions = SHORT_CLIP_SECONDS.map((seconds) => ({
        value: seconds,
        label: `${seconds}s`,
        'data-attr': `replay-clip-duration-${seconds}`,
    }))

    // Only offered where there is that much recording to clip, so no option produces an empty tail.
    const longOptions = LONG_CLIP_MINUTES.filter((minutes) => minutes * 60 < sessionSeconds).map((minutes) => ({
        value: minutes * 60,
        label: `${minutes}m`,
        'data-attr': `replay-clip-duration-${minutes}m`,
    }))

    return [...shortOptions, ...longOptions]
}

/**
 * The window a clip covers, centered on the playhead and pulled inside the recording at both ends.
 *
 * Shared by the overlay that shows the range and the export that renders it. Computing it in two
 * places let them disagree near the end of a recording by half the clip length, so the file people
 * got back started later than the range they were shown.
 */
export function clipWindowSeconds(
    currentTimeSeconds: number,
    sessionDurationSeconds: number,
    clipDurationSeconds: number
): ClipWindow {
    let startSeconds = currentTimeSeconds - clipDurationSeconds / 2
    let endSeconds = currentTimeSeconds + clipDurationSeconds / 2

    if (startSeconds < 0) {
        startSeconds = 0
        endSeconds = Math.min(clipDurationSeconds, sessionDurationSeconds)
    }

    if (endSeconds > sessionDurationSeconds) {
        endSeconds = sessionDurationSeconds
        startSeconds = Math.max(0, sessionDurationSeconds - clipDurationSeconds)
    }

    return { startSeconds, endSeconds }
}
