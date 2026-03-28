import type { PlayerConfig } from '@posthog/replay-headless/protocol'

import { RasterizationError } from '../errors'
import { CaptureConfig, RasterizeRecordingInput } from '../types'

const DEFAULT_PLAYBACK_SPEED = 4
const DEFAULT_FPS = 24

export function validateInput(input: RasterizeRecordingInput): void {
    if (!input.session_id) {
        throw new RasterizationError('session_id is required', false, 'INVALID_INPUT')
    }
    if (!input.team_id || input.team_id <= 0) {
        throw new RasterizationError('team_id must be a positive integer', false, 'INVALID_INPUT')
    }
    if (input.playback_speed !== undefined && input.playback_speed <= 0) {
        throw new RasterizationError(
            `playback_speed must be positive, got: ${input.playback_speed}`,
            false,
            'INVALID_INPUT'
        )
    }
    if (input.capture_timeout != null && input.capture_timeout <= 0) {
        throw new RasterizationError(
            `capture_timeout must be positive, got: ${input.capture_timeout}`,
            false,
            'INVALID_INPUT'
        )
    }
    if (input.recording_fps !== undefined && input.recording_fps <= 0) {
        throw new RasterizationError(
            `recording_fps must be positive, got: ${input.recording_fps}`,
            false,
            'INVALID_INPUT'
        )
    }
    if (input.trim != null && input.trim <= 0) {
        throw new RasterizationError(`trim must be positive, got: ${input.trim}`, false, 'INVALID_INPUT')
    }
    if (input.screenshot_quality != null && (input.screenshot_quality < 1 || input.screenshot_quality > 100)) {
        throw new RasterizationError(
            `screenshot_quality must be between 1 and 100, got: ${input.screenshot_quality}`,
            false,
            'INVALID_INPUT'
        )
    }
}

export function buildCaptureConfig(input: RasterizeRecordingInput): CaptureConfig {
    const playbackSpeed = input.playback_speed || DEFAULT_PLAYBACK_SPEED
    const outputFps = input.recording_fps || DEFAULT_FPS
    // e.g. 3fps output × 8x speed = 24fps capture → setpts stretches 8x → 3fps
    const captureFps = outputFps * playbackSpeed

    const ffmpegOutputOpts = ['-crf 23', '-pix_fmt yuv420p', '-movflags +faststart']
    if (input.trim) {
        ffmpegOutputOpts.push(`-t ${input.trim}`)
    }

    const ffmpegVideoFilters: string[] = []
    // Stretch timestamps so capture at Nx speed outputs real-time video.
    // This eliminates the need for a separate post-processing encode pass.
    if (playbackSpeed > 1) {
        ffmpegVideoFilters.push(`setpts=${playbackSpeed}*PTS`)
        ffmpegVideoFilters.push(`fps=${outputFps}`)
    }

    return {
        captureFps,
        outputFps,
        playbackSpeed,
        trim: input.trim,
        trimFrameLimit: input.trim ? input.trim * outputFps : Infinity,
        captureTimeoutMs: input.capture_timeout ? input.capture_timeout * 1000 : Infinity,
        ffmpegOutputOpts,
        ffmpegVideoFilters,
        screenshotFormat: input.screenshot_format || 'jpeg',
        screenshotQuality: input.screenshot_quality ?? 80,
    }
}

export function buildPlayerConfig(
    input: RasterizeRecordingInput,
    playbackSpeed: number,
    blockCount: number
): PlayerConfig {
    return {
        teamId: input.team_id,
        sessionId: input.session_id,
        playbackSpeed,
        blockCount,
        skipInactivity: input.skip_inactivity !== false,
        mouseTail: input.mouse_tail !== false,
        showMetadataFooter: input.show_metadata_footer,
        startTimestamp: input.start_timestamp,
        endTimestamp: input.end_timestamp,
        viewportEvents: input.viewport_events || [],
    }
}
