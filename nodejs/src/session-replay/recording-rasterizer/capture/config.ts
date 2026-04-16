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
    if (input.max_virtual_time != null && input.max_virtual_time <= 0) {
        throw new RasterizationError(
            `max_virtual_time must be positive, got: ${input.max_virtual_time}`,
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
    const outputFormat = input.output_format || 'mp4'

    const ffmpegOutputOpts: string[] =
        outputFormat === 'webm'
            ? ['-f webm', '-c:v libvpx-vp9', '-crf 30', '-b:v 0']
            : outputFormat === 'gif'
              ? ['-f gif', '-c:v gif', '-loop', '0']
              : ['-crf 23', '-pix_fmt yuv420p', '-movflags +faststart']
    if (input.trim) {
        ffmpegOutputOpts.push(`-t ${input.trim}`)
    }

    const ffmpegVideoFilters: string[] = []
    // libx264 and libvpx-vp9 require even dimensions (yuv420p chroma subsampling).
    // Pad by at most 1 pixel if the viewport has an odd width or height.
    if (outputFormat !== 'gif') {
        ffmpegVideoFilters.push('pad=ceil(iw/2)*2:ceil(ih/2)*2')
    }
    // Stretch timestamps so capture at Nx speed outputs real-time video.
    // This eliminates the need for a separate post-processing encode pass.
    if (playbackSpeed > 1) {
        ffmpegVideoFilters.push(`setpts=${playbackSpeed}*PTS`)
        ffmpegVideoFilters.push(`fps=${outputFps}`)
    }
    if (outputFormat === 'gif') {
        // Scale down to 800px wide — GIFs at full viewport size are enormous.
        // -2 ensures even height; lanczos gives sharp downscaling.
        ffmpegVideoFilters.push('scale=800:-2:flags=lanczos')
        // 12fps keeps file size reasonable. Per-frame palette (stats_mode=single)
        // with Bayer dithering and rectangle diff mode produces better quality
        // and smaller files than ffmpeg's defaults.
        ffmpegVideoFilters.push('fps=12')
        ffmpegVideoFilters.push(
            'split[s0][s1];[s0]palettegen=stats_mode=single[p];[s1][p]paletteuse=dither=bayer:bayer_scale=5:diff_mode=rectangle'
        )
    }

    return {
        captureFps,
        outputFps,
        playbackSpeed,
        trim: input.trim,
        trimFrameLimit: input.trim ? input.trim * outputFps : Infinity,
        maxVirtualTimeMs: input.max_virtual_time ? input.max_virtual_time * 1000 : Infinity,
        outputFormat,
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
        startOffsetS: input.start_offset_s,
        endOffsetS: input.end_offset_s,
        viewportEvents: input.viewport_events || [],
    }
}
