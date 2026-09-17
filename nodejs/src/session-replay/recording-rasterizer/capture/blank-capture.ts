import { spawn } from 'child_process'

import { METADATA_FOOTER_HEIGHT_PX } from '@posthog/replay-headless/protocol'

import { config as workerConfig } from '~/session-replay/recording-rasterizer/config'
import { RasterizationError } from '~/session-replay/recording-rasterizer/errors'
import { type Logger, createLogger } from '~/session-replay/recording-rasterizer/logger'

// Frames are probed as a small grayscale grid. A blank capture is uniform at any scale, and the
// averaging stops a cursor or a lone spinner from reading as a painted page.
const PROBE_WIDTH = 64
const PROBE_HEIGHT = 36
const PROBE_PIXELS = PROBE_WIDTH * PROBE_HEIGHT
// Spread over the whole file, so a capture that paints late is judged on more than its first second.
const PROBE_FRAME_COUNT = 12
// Luma spread (0-255) under which a frame holds no visible structure. A solid frame measures under 4
// once encoder ringing is counted, and the flattest real page measures far above this.
const UNIFORM_LUMA_RANGE = 12
const PROBE_TIMEOUT_MS = 30_000

/** Count how many of the probed frames hold a single flat tone, over raw PROBE_WIDTH x PROBE_HEIGHT gray frames. */
export function countUniformFrames(frames: Buffer): { sampledFrames: number; uniformFrames: number } {
    let sampledFrames = 0
    let uniformFrames = 0
    // A trailing partial frame is dropped: its missing pixels would narrow the range and read as blank.
    for (let offset = 0; offset + PROBE_PIXELS <= frames.length; offset += PROBE_PIXELS) {
        let min = 255
        let max = 0
        for (let i = offset; i < offset + PROBE_PIXELS; i++) {
            const luma = frames[i]
            if (luma < min) {
                min = luma
            }
            if (luma > max) {
                max = luma
            }
        }
        sampledFrames++
        if (max - min <= UNIFORM_LUMA_RANGE) {
            uniformFrames++
        }
    }
    return { sampledFrames, uniformFrames }
}

export function buildProbeArgs(outputPath: string, durationS: number, hasFooter: boolean): string[] {
    const filters: string[] = []
    // Sample across the file rather than take the first frames, which at 24fps all come from the
    // same half second. A non-finite duration leaves the filter out and probes the opening frames.
    const sampleFps = durationS > 0 ? PROBE_FRAME_COUNT / durationS : 0
    if (Number.isFinite(sampleFps) && sampleFps > 0) {
        filters.push(`fps=${sampleFps.toFixed(4)}`)
    }
    if (hasFooter) {
        // The metadata footer paints from the host page, so it is on screen even when the replay
        // surface is not. Left in frame it would make every blank capture measure as painted.
        // max() keeps the crop legal for a viewport shorter than the footer.
        filters.push(`crop=iw:max(ih-${METADATA_FOOTER_HEIGHT_PX}\\,2):0:0`)
    }
    filters.push(`scale=${PROBE_WIDTH}:${PROBE_HEIGHT}`, 'format=gray')
    return [
        '-nostdin',
        '-v',
        'error',
        '-i',
        outputPath,
        '-vf',
        filters.join(','),
        '-frames:v',
        String(PROBE_FRAME_COUNT),
        '-f',
        'rawvideo',
        '-',
    ]
}

/** Decode the probe frames, or null when the probe reached no verdict — the caller then ships the capture. */
async function decodeProbeFrames(args: string[], log: Logger): Promise<Buffer | null> {
    return new Promise((resolve) => {
        const child = spawn(process.env.FFMPEG_PATH || 'ffmpeg', args, { stdio: ['ignore', 'pipe', 'pipe'] })
        const chunks: Buffer[] = []
        const stderr: string[] = []
        const timer = setTimeout(() => {
            log.warn('blank frame probe timed out')
            child.kill('SIGKILL')
        }, PROBE_TIMEOUT_MS)
        child.stdout.on('data', (chunk: Buffer) => chunks.push(chunk))
        child.stderr.on('data', (chunk: Buffer) => stderr.push(chunk.toString()))
        child.on('error', (err) => {
            clearTimeout(timer)
            log.warn({ err }, 'blank frame probe could not start')
            resolve(null)
        })
        child.on('close', (code) => {
            clearTimeout(timer)
            const frames = Buffer.concat(chunks)
            if (code === 0 && frames.length >= PROBE_PIXELS) {
                resolve(frames)
                return
            }
            log.warn({ code, bytes: frames.length, stderr: stderr.slice(-5) }, 'blank frame probe failed')
            resolve(null)
        })
    })
}

/**
 * Reject a capture whose every probed frame is one flat tone.
 *
 * The player signalling progress only proves it ran, not that it drew anything: a capture can hold
 * a whole session of solid dark or white frames. Downstream those read as a broken page, so the
 * render fails here instead of shipping a video with nothing in it.
 *
 * Retryable, and inconclusive on purpose when the probe cannot run: a compositor that never painted
 * this attempt can paint on the next, and no render is worth discarding over a missing ffmpeg.
 */
export async function assertCaptureIsNotBlank(
    outputPath: string,
    durationS: number,
    hasFooter: boolean,
    log: Logger = createLogger()
): Promise<void> {
    if (!workerConfig.blankCaptureCheck) {
        return
    }
    const frames = await decodeProbeFrames(buildProbeArgs(outputPath, durationS, hasFooter), log)
    if (!frames) {
        return
    }
    const { sampledFrames, uniformFrames } = countUniformFrames(frames)
    if (uniformFrames < sampledFrames) {
        log.info({ sampled_frames: sampledFrames, uniform_frames: uniformFrames }, 'blank frame check passed')
        return
    }
    throw new RasterizationError(
        `Capture is blank: all ${sampledFrames} probed frames hold a single flat tone`,
        true,
        'BLANK_CAPTURE'
    )
}
