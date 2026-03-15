export interface RasterizeRecordingInput {
    session_id: string
    team_id: number
    capture_timeout?: number // max seconds to wait for recording playback to complete (default: 300)
    playback_speed?: number // 1-360, defaults to 4
    start_timestamp?: number // ms since epoch
    end_timestamp?: number // ms since epoch
    recording_fps?: number // target FPS for final video
    skip_inactivity?: boolean // skip inactive sections during playback (default: true)
    mouse_tail?: boolean // show mouse trail (default: true)
    viewport_events?: Array<{ timestamp: number; width: number; height: number }> // viewport resize events
    skip_postprocessing?: boolean // skip ffmpeg post-processing (for AI pipeline)
    show_metadata_footer?: boolean // render URL + timestamp bar at bottom (for AI pipeline)
    trim?: number // optional max output duration in seconds (only trims if video is longer)
    s3_bucket: string
    s3_key_prefix: string // e.g. "exports/mp4/team-123/task-456"
    // Internal: override viewport for benchmarking (not exposed via Temporal)
    _viewport_width?: number
    _viewport_height?: number
}

/**
 * Extends the base InactivityPeriod from @posthog/replay-headless with
 * recording_ts fields that map segment boundaries to post-processed video
 * positions. Keep the base fields in sync with common/replay-headless/src/types.ts.
 */
export interface InactivityPeriod {
    ts_from_s: number
    ts_to_s: number | null
    active: boolean
    recording_ts_from_s?: number
    recording_ts_to_s?: number
}

export interface ActivityTimings {
    total_s: number
    setup_s: number // browser setup + player load + data fetch
    capture_s: number // screen recording of playback
    postprocess_s: number | null
    upload_s: number
}

export interface RasterizeRecordingOutput {
    s3_uri: string
    video_duration_s: number // actual playback duration of the output video
    playback_speed: number
    show_metadata_footer: boolean
    inactivity_periods: InactivityPeriod[]
    file_size_bytes: number
    timings: ActivityTimings
}

/** Internal result from the recorder before S3 upload */
export interface RecordingResult {
    video_path: string
    playback_speed: number
    capture_duration_s: number // wall-clock seconds of useful capture (up to RECORDING_ENDED)
    inactivity_periods: InactivityPeriod[]
    custom_fps: number
    timings: Pick<ActivityTimings, 'setup_s' | 'capture_s'>
}
