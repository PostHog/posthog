import * as fs from 'fs/promises'
import { PuppeteerCaptureFormat, capture as captureVideo } from 'puppeteer-capture'

import { RasterizationError } from '../errors'
import { type Logger, createLogger } from '../logger'
import { CaptureConfig, InactivityPeriod, RecordingResult } from '../types'
import { elapsed } from '../utils'
import { PlayerController } from './player'

export async function capturePlayback(
    player: PlayerController,
    captureConfig: CaptureConfig,
    outputPath: string,
    log: Logger = createLogger(),
    onProgress?: () => void
): Promise<
    Pick<RecordingResult, 'capture_duration_s' | 'frame_count' | 'truncated' | 'inactivity_periods' | 'timings'>
> {
    const captureStart = process.hrtime()
    const ffmpegStderr: string[] = []
    let frameCount = 0

    // Install CDP guards before captureVideo — it wraps createCDPSession
    // to inject screenshot format and gate beginFrame on pending stylesheets.
    player.prepareBrowserForCapture(captureConfig.screenshotFormat, captureConfig.screenshotQuality)

    const page = player.page

    // Start capture — installs virtual time shims before playback.
    const recorder = await captureVideo(page, {
        fps: captureConfig.captureFps,
        format: PuppeteerCaptureFormat.MP4('veryfast', 'libx264'),
        // eslint-disable-next-line @typescript-eslint/require-await
        customFfmpegConfig: async (ffmpeg: any) => {
            ffmpeg.outputOptions(captureConfig.ffmpegOutputOpts)
            for (const filter of captureConfig.ffmpegVideoFilters) {
                ffmpeg.videoFilters(filter)
            }
            ffmpeg.on('start', (cmd: string) => log.info({ cmd }, 'ffmpeg started'))
            ffmpeg.on('stderr', (line: string) => ffmpegStderr.push(line))
            ffmpeg.on('error', (err: Error) => log.error({ err, stderr: ffmpegStderr.slice(-20) }, 'ffmpeg error'))
        },
        ffmpeg: process.env.FFMPEG_PATH || undefined,
    })

    const progressInterval = Math.max(10, captureConfig.captureFps)
    recorder.on('frameCaptured', () => {
        frameCount++
        if (frameCount % progressInterval === 0) {
            log.info(
                {
                    frame: frameCount,
                    virtual_s: +(frameCount / captureConfig.captureFps).toFixed(1),
                    wall_s: +elapsed(captureStart).toFixed(1),
                },
                'capture progress'
            )
            onProgress?.()
        }
    })

    // When ffmpeg dies, puppeteer-capture stops capturing but waitForTimeout()
    // hangs forever. Listen for captureStopped to break out of the loop.
    let captureAborted: Error | null = null
    let captureAbortReject: ((err: Error) => void) | null = null
    recorder.on('captureStopped', () => {
        log.error({ stderr: ffmpegStderr.slice(-20), frames: frameCount }, 'ffmpeg process exited unexpectedly')
        const err = new RasterizationError('capture stopped unexpectedly (ffmpeg crashed)', true, 'CAPTURE_ABORTED')
        captureAborted = err
        captureAbortReject?.(err)
    })

    let virtualElapsed = 0
    let truncated = false
    try {
        await recorder.start(outputPath)
        const vp = page.viewport()
        log.info({ fps: captureConfig.captureFps, width: vp?.width, height: vp?.height }, 'capture started')

        await player.startPlayback()
        log.info('playback started')

        const checkIntervalMs = 250

        while (virtualElapsed < captureConfig.captureTimeoutMs) {
            if (captureAborted) {
                throw captureAborted
            }
            await Promise.race([
                recorder.waitForTimeout(checkIntervalMs),
                new Promise<never>((_, reject) => {
                    captureAbortReject = reject
                }),
            ])
            captureAbortReject = null
            virtualElapsed += checkIntervalMs

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
            log.warn(
                { timeout_s: captureConfig.captureTimeoutMs / 1000, frames: frameCount },
                'capture timeout reached'
            )
            truncated = true
        }
    } finally {
        captureAbortReject = null
        try {
            await recorder.stop()
        } catch {
            // ffmpeg process may already be dead
        }
    }

    let fileSize = 0
    try {
        const rawStat = await fs.stat(outputPath)
        fileSize = rawStat.size
    } catch {
        log.warn('output file missing after capture — ffmpeg may have failed to start')
    }
    log.info({ file_size_bytes: fileSize }, 'capture stopped')

    const inactivityPeriods: InactivityPeriod[] = player.getInactivityPeriods()

    const rawDurationS = frameCount / captureConfig.outputFps
    const captureDurationS = captureConfig.trim ? Math.min(rawDurationS, captureConfig.trim) : rawDurationS

    return {
        capture_duration_s: captureDurationS,
        frame_count: frameCount,
        truncated,
        inactivity_periods: inactivityPeriods,
        timings: { setup_s: 0, capture_s: elapsed(captureStart) },
    }
}
