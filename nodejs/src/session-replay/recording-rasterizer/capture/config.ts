import type { PlayerConfig } from '@posthog/replay-headless/protocol'

import { config as workerConfig } from '~/session-replay/recording-rasterizer/config'
import { RasterizationError } from '~/session-replay/recording-rasterizer/errors'
import { CaptureConfig, RasterizeRecordingInput } from '~/session-replay/recording-rasterizer/types'

const DEFAULT_PLAYBACK_SPEED = 4
const DEFAULT_FPS = 24
// GIFs at high frame rates are enormous; 12fps is the ceiling worth encoding.
const GIF_MAX_FPS = 12
// Kept in step with SESSION_RECORDING_ID_RE in products/exports/backend/models/exported_asset.py.
// The lookahead drops a dot-only id, which is a relative path segment rather than a session.
const SESSION_ID_RE = /^(?!\.+$)[A-Za-z0-9_.:-]{1,200}$/

// Coerce a value interpolated into an ffmpeg option (`-t`) or filter (`setpts=`, `fps=`) to a
// finite number. ffmpeg is spawned without a shell, but a non-finite/non-numeric value reaching
// here (e.g. from a future caller that skips upstream validation) could still land in the option
// list or filtergraph as a raw string. Throwing keeps interpolation injection-proof regardless of
// the caller: a finite number stringifies to [0-9.eE+-] only, so no spaces or filter metacharacters.
function toFiniteNumber(value: unknown, field: string): number {
    const n = Number(value)
    if (!Number.isFinite(n)) {
        throw new RasterizationError(`${field} must be a finite number, got: ${String(value)}`, false, 'INVALID_INPUT')
    }
    return n
}

export function validateInput(input: RasterizeRecordingInput): void {
    if (!input.session_id) {
        throw new RasterizationError('session_id is required', false, 'INVALID_INPUT')
    }
    // Mirrors the allowlist the Python side enforces: a session id ends up in the internal
    // recording-api paths the block proxy builds, so it must not carry path structure.
    if (!SESSION_ID_RE.test(input.session_id)) {
        throw new RasterizationError('session_id contains illegal characters', false, 'INVALID_INPUT')
    }
    if (!input.team_id || input.team_id <= 0) {
        throw new RasterizationError('team_id must be a positive integer', false, 'INVALID_INPUT')
    }
    // Speeds below 1 would need a slow-motion filter chain the pipeline doesn't have: frames come
    // in at captureFps = outputFps * speed, and without the setpts stretch the file's real duration
    // is 1/speed times what we report downstream (video_duration_s, inactivity mapping, trim).
    if (input.playback_speed !== undefined && input.playback_speed < 1) {
        throw new RasterizationError(
            `playback_speed must be >= 1, got: ${input.playback_speed}`,
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
    const playbackSpeed = input.playback_speed
        ? toFiniteNumber(input.playback_speed, 'playback_speed')
        : DEFAULT_PLAYBACK_SPEED
    let outputFps = input.recording_fps ? toFiniteNumber(input.recording_fps, 'recording_fps') : DEFAULT_FPS
    const outputFormat = input.output_format || 'mp4'
    // Clamp before deriving captureFps so GIF renders don't capture frames the fps filter would
    // discard: every captured frame is a full CDP screenshot round-trip.
    if (outputFormat === 'gif') {
        outputFps = Math.min(outputFps, GIF_MAX_FPS)
    }
    const trim = input.trim ? toFiniteNumber(input.trim, 'trim') : undefined
    // e.g. 3fps output × 8x speed = 24fps capture → setpts stretches 8x → 3fps
    const captureFps = outputFps * playbackSpeed

    const ffmpegOutputOpts: string[] =
        outputFormat === 'webm'
            ? // Default libvpx-vp9 settings (deadline good, cpu-used 0) encode at single-digit fps;
              // realtime deadline with row multithreading keeps encode well ahead of capture.
              ['-f webm', '-c:v libvpx-vp9', '-crf 30', '-b:v 0', '-deadline realtime', '-cpu-used 5', '-row-mt 1']
            : outputFormat === 'gif'
              ? ['-f gif', '-c:v gif', '-loop', '0']
              : ['-f mp4', '-c:v libx264', '-preset veryfast', '-crf 23', '-pix_fmt yuv420p', '-movflags +faststart']
    if (outputFormat !== 'gif') {
        // nproc inside a CFS-limited pod reports host cores, so an uncapped encoder spawns far more
        // threads than the pod can run and throttles the capture loop competing for the same quota.
        ffmpegOutputOpts.push('-threads 2')
    }
    // puppeteer-capture forces the output rate to captureFps (outputFPS in PuppeteerCaptureBase),
    // which resamples the fps-filtered stream back up by duplicating every frame `speed` times.
    // A later -r wins, so pin the container rate to what the filter chain actually produces.
    ffmpegOutputOpts.push(`-r ${outputFps}`)
    if (trim) {
        ffmpegOutputOpts.push(`-t ${trim}`)
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
        // Per-frame palette (stats_mode=single) with Bayer dithering and rectangle diff mode
        // produces better quality and smaller files than ffmpeg's defaults. No fps filter here:
        // the setpts branch already emits fps=outputFps for speeds above 1, and at speed 1 the
        // capture rate equals the clamped output rate.
        ffmpegVideoFilters.push(
            'split[s0][s1];[s0]palettegen=stats_mode=single[p];[s1][p]paletteuse=dither=bayer:bayer_scale=5:diff_mode=rectangle'
        )
    }

    return {
        captureFps,
        outputFps,
        playbackSpeed,
        trim,
        trimFrameLimit: trim ? trim * outputFps : Infinity,
        maxVirtualTimeMs: input.max_virtual_time ? input.max_virtual_time * 1000 : Infinity,
        outputFormat,
        ffmpegOutputOpts,
        ffmpegVideoFilters,
        screenshotFormat: input.screenshot_format || workerConfig.screenshotFormat,
        screenshotQuality: input.screenshot_quality ?? workerConfig.screenshotJpegQuality,
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
