export interface RasterizeRecordingInput {
    recording_url: string
    wait_for_css_selector: string
    recording_duration: number // seconds
    playback_speed: number // 1-360
    screenshot_width?: number
    screenshot_height?: number
    recording_fps?: number // target FPS for final video
    skip_postprocessing?: boolean // skip ffmpeg post-processing (for AI pipeline)
    s3_bucket: string
    s3_key_prefix: string // e.g. "exports/mp4/team-123/task-456"
}

export interface InactivityPeriod {
    ts_from_s: number
    ts_to_s: number | null
    active: boolean
    recording_ts_from_s?: number
    recording_ts_to_s?: number
}

export interface RasterizeRecordingOutput {
    s3_key: string
    pre_roll: number
    playback_speed: number
    measured_width: number | null
    inactivity_periods: InactivityPeriod[]
    segment_start_timestamps: Record<string, number>
    custom_fps: number | null
    file_size_bytes: number
}

/** Internal result from the recorder before S3 upload */
export interface RecordingResult {
    video_path: string
    pre_roll: number
    playback_speed: number
    measured_width: number | null
    inactivity_periods: InactivityPeriod[]
    segment_start_timestamps: Record<string, number>
    custom_fps: number | null
}
