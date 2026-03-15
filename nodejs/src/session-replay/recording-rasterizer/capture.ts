import * as fs from 'fs/promises'
import { Page } from 'puppeteer'
import { PuppeteerCaptureFormat, capture as captureVideo } from 'puppeteer-capture'

import { type Logger, createLogger } from './logger'
import { PlayerController } from './player'
import { InactivityPeriod, RasterizeRecordingInput, RecordingResult } from './types'
import { elapsed } from './utils'

const DEFAULT_PLAYBACK_SPEED = 4
const DEFAULT_FPS = 24

export interface CaptureConfig {
    captureFps: number // recordingFps * playbackSpeed — internal capture rate
    outputFps: number // recordingFps — what the viewer sees after setpts
    playbackSpeed: number
    trim?: number // max output seconds
    trimFrameLimit: number // trim * outputFps — for early loop stop
    captureTimeoutMs: number // virtual-time timeout for the capture loop
    ffmpegOutputOpts: string[]
    ffmpegVideoFilters: string[]
}

export function buildCaptureConfig(input: RasterizeRecordingInput): CaptureConfig {
    const playbackSpeed = input.playback_speed || DEFAULT_PLAYBACK_SPEED
    const outputFps = input.recording_fps || DEFAULT_FPS
    // Capture at outputFps * playbackSpeed so that after setpts stretches
    // timestamps by playbackSpeed, the output plays at outputFps in real-time.
    // e.g. 3fps output × 8x speed = 24fps capture → stretched 8x → 3fps.
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
    }
}

export async function capturePlayback(
    page: Page,
    player: PlayerController,
    captureConfig: CaptureConfig,
    outputPath: string,
    log: Logger = createLogger()
): Promise<Pick<RecordingResult, 'capture_duration_s' | 'inactivity_periods' | 'timings'>> {
    const captureStart = process.hrtime()
    let frameCount = 0

    // Start capture FIRST — this installs virtual time shims (Date.now,
    // setTimeout, rAF). Then dispatch player-start so all playback happens
    // under deterministic virtual time control. rrweb's rAF-based rendering
    // fires naturally as we advance virtual time in the loop below.
    const recorder = await captureVideo(page, {
        fps: captureConfig.captureFps,
        format: PuppeteerCaptureFormat.MP4('veryfast', 'libx264'),
        // eslint-disable-next-line @typescript-eslint/require-await
        customFfmpegConfig: async (ffmpeg: any) => {
            ffmpeg.outputOptions(captureConfig.ffmpegOutputOpts)
            for (const filter of captureConfig.ffmpegVideoFilters) {
                ffmpeg.videoFilters(filter)
            }
        },
        ffmpeg: process.env.FFMPEG_PATH || undefined,
    })

    const logInterval = Math.max(10, captureConfig.captureFps)
    recorder.on('frameCaptured', () => {
        frameCount++
        if (frameCount % logInterval === 0) {
            log.info(
                {
                    frame: frameCount,
                    virtual_s: +(frameCount / captureConfig.captureFps).toFixed(1),
                    wall_s: +elapsed(captureStart).toFixed(1),
                },
                'frame captured'
            )
        }
    })

    let virtualElapsed = 0
    try {
        await recorder.start(outputPath)
        const vp = page.viewport()
        log.info({ fps: captureConfig.captureFps, width: vp?.width, height: vp?.height }, 'capture started')

        await player.startPlayback()
        log.info('playback started')

        // Advance virtual time until the recording ends or we hit a limit.
        // puppeteer-capture's waitForTimeout advances the virtual clock; rrweb's
        // shimmed timers fire deterministically within that virtual time.
        const checkIntervalMs = 1000

        while (virtualElapsed < captureConfig.captureTimeoutMs) {
            await recorder.waitForTimeout(checkIntervalMs)
            virtualElapsed += checkIntervalMs

            // Stop early when we've captured enough frames for the trim duration.
            // ffmpeg -t handles the precise cut, but without this the loop would
            // keep advancing virtual time wastefully.
            if (frameCount >= captureConfig.trimFrameLimit) {
                log.info({ trim_s: captureConfig.trim, frames: frameCount }, 'trim limit reached')
                break
            }

            const playerError = player.getError()
            if (playerError) {
                throw playerError
            }

            if (player.isEnded()) {
                log.info({ virtual_s: virtualElapsed / 1000, frames: frameCount }, 'recording ended')
                break
            }
        }

        if (virtualElapsed >= captureConfig.captureTimeoutMs) {
            log.warn({ timeout_s: captureConfig.captureTimeoutMs / 1000 }, 'capture timeout reached')
        }
    } finally {
        try {
            await recorder.stop()
        } catch {
            // ffmpeg process may already be dead
        }
    }

    const rawStat = await fs.stat(outputPath)
    log.info({ file_size_bytes: rawStat.size }, 'capture stopped')

    const inactivityPeriods: InactivityPeriod[] = player.getInactivityPeriods()

    // frameCount / outputFps = total frames expressed as video seconds.
    // When trim is set, ffmpeg -t caps the actual output — use that as
    // the authoritative duration since ffmpeg may discard trailing frames.
    const rawDurationS = frameCount / captureConfig.outputFps
    const captureDurationS = captureConfig.trim ? Math.min(rawDurationS, captureConfig.trim) : rawDurationS

    return {
        capture_duration_s: captureDurationS,
        inactivity_periods: inactivityPeriods,
        timings: { setup_s: 0, capture_s: elapsed(captureStart) },
    }
}
