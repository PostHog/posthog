import type { InactivityPeriod as BaseInactivityPeriod } from '@posthog/replay-headless/protocol'

export interface RasterizeRecordingInput {
    session_id: string
    team_id: number
    max_virtual_time?: number // max virtual-time seconds before stopping capture (default: unlimited)
    playback_speed?: number // 1-360, defaults to 4
    start_timestamp?: number // ms since epoch
    end_timestamp?: number // ms since epoch
    recording_fps?: number // target FPS for final video
    skip_inactivity?: boolean // skip inactive sections during playback (default: true)
    mouse_tail?: boolean // show mouse trail (default: true)
    viewport_events?: Array<{ timestamp: number; width: number; height: number }> // viewport resize events
    show_metadata_footer?: boolean // render URL + timestamp bar at bottom (for AI pipeline)
    trim?: number // optional max output duration in seconds (only trims if video is longer)
    viewport_width?: number // override capture width (default: 1280)
    viewport_height?: number // override capture height (default: 720)
    screenshot_format?: 'jpeg' | 'png' // capture format for each frame (default: jpeg)
    screenshot_quality?: number // JPEG quality 0-100 (default: 80, ignored for png)
    s3_bucket: string
    s3_key_prefix: string // e.g. "exports/mp4/team-123/task-456"
}

/**
 * Extends the base InactivityPeriod from the shared protocol with
 * recording_ts fields that map segment boundaries to post-processed video
 * positions.
 */
export interface InactivityPeriod extends BaseInactivityPeriod {
    recording_ts_from_s?: number
    recording_ts_to_s?: number
}

/**
 * Structured heartbeat payload sent from the rasterizer activity to Temporal.
 * The parent workflow reads this via `describe().pending_activities[].heartbeat_details`
 * to surface fine-grained progress to the frontend during video rendering.
 */
export interface RasterizationProgress {
    phase: 'setup' | 'capture' | 'upload'
    frame: number
    estimatedTotalFrames: number
}

export interface ActivityTimings {
    total_s: number
    setup_s: number // browser setup + player load + data fetch
    capture_s: number // screen recording of playback
    upload_s: number
}

export interface RasterizeRecordingOutput {
    s3_uri: string
    video_duration_s: number // actual playback duration of the output video
    playback_speed: number
    show_metadata_footer: boolean
    truncated: boolean // true when max_virtual_time stopped the recording early
    inactivity_periods: InactivityPeriod[]
    file_size_bytes: number
    timings: ActivityTimings
}

export interface CaptureConfig {
    captureFps: number // recordingFps * playbackSpeed — internal capture rate
    outputFps: number // recordingFps — what the viewer sees after setpts
    playbackSpeed: number
    trim?: number // max output seconds
    trimFrameLimit: number // trim * outputFps — for early loop stop
    maxVirtualTimeMs: number // max virtual time before stopping capture (default: unlimited)
    ffmpegOutputOpts: string[]
    ffmpegVideoFilters: string[]
    screenshotFormat: 'jpeg' | 'png'
    screenshotQuality?: number
}

/** Internal result from the recorder before S3 upload */
export interface RecordingResult {
    video_path: string
    playback_speed: number
    capture_duration_s: number // wall-clock seconds of useful capture (up to RECORDING_ENDED)
    frame_count: number // total frames captured
    truncated: boolean // true when max_virtual_time stopped the recording early
    inactivity_periods: InactivityPeriod[]
    custom_fps: number
    timings: Pick<ActivityTimings, 'setup_s' | 'capture_s'>
}
