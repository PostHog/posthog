import * as fs from 'fs/promises'
import { PuppeteerCaptureFormat, capture as captureVideo } from 'puppeteer-capture'

import { RasterizationError } from '../errors'
import { type Logger, createLogger } from '../logger'
import { CaptureConfig, InactivityPeriod, RasterizationProgress, RecordingResult } from '../types'
import { elapsed } from '../utils'
import { PlayerController } from './player'

export async function capturePlayback(
    player: PlayerController,
    captureConfig: CaptureConfig,
    outputPath: string,
    onProgress: () => void,
    progress: RasterizationProgress | null = null,
    log: Logger = createLogger()
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
        if (progress) {
            progress.frame = frameCount
        }
        if (frameCount % progressInterval === 0) {
            log.info(
                {
                    frame: frameCount,
                    virtual_s: +(frameCount / captureConfig.captureFps).toFixed(1),
                    wall_s: +elapsed(captureStart).toFixed(1),
                },
                'capture progress'
            )
            onProgress()
        }
    })

    // Log the actual rejection reason when a frame capture fails. This fires
    // with the original error from frame.evaluate() or beginFrame before
    // captureStopped is emitted.
    recorder.on('frameCaptureFailed', (reason: unknown) => {
        log.error({ err: reason, frames: frameCount }, 'frame capture failed')
    })

    // Monitor page lifecycle events that can terminate capture.
    // Named functions so we can remove them in the finally block — the page
    // is pooled and reused, so anonymous listeners would accumulate.
    let captureDone = false
    const onPageClose = (): void => {
        if (!captureDone) {
            log.error({ frames: frameCount }, 'page closed during capture')
        }
    }
    const onPageError = (err: Error): void => {
        if (!captureDone) {
            log.error({ err, frames: frameCount }, 'page error during capture')
        }
    }
    page.on('close', onPageClose)
    page.on('error', onPageError)

    // When ffmpeg dies, puppeteer-capture stops capturing but waitForTimeout()
    // hangs forever. Listen for captureStopped to break out of the loop.
    let captureAborted: Error | null = null
    let captureAbortReject: ((err: Error) => void) | null = null
    const onCaptureStopped = (): void => {
        if (captureDone || player.isEnded()) {
            // Playback finished naturally — ffmpeg exiting is expected.
            log.info({ frames: frameCount }, 'capture stopped after playback ended')
            return
        }
        log.error({ stderr: ffmpegStderr.slice(-20), frames: frameCount }, 'capture stopped unexpectedly')
        const err = new RasterizationError('capture stopped unexpectedly', true, 'CAPTURE_ABORTED')
        captureAborted = err
        captureAbortReject?.(err)
    }
    recorder.on('captureStopped', onCaptureStopped)

    let virtualElapsed = 0
    let truncated = false
    try {
        await recorder.start(outputPath)
        const vp = page.viewport()
        log.info({ fps: captureConfig.captureFps, width: vp?.width, height: vp?.height }, 'capture started')

        // Install after recorder.start() — puppeteer-capture overrides rAF/setTimeout/setInterval
        // during start(), and this wraps those overrides with try/catch so individual player JS
        // errors are swallowed instead of killing the entire capture.
        await player.installCallbackErrorGuards()

        await player.startPlayback()
        log.info('playback started')

        const checkIntervalMs = 250

        while (virtualElapsed < captureConfig.maxVirtualTimeMs) {
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

        if (virtualElapsed >= captureConfig.maxVirtualTimeMs) {
            log.warn(
                { max_virtual_s: captureConfig.maxVirtualTimeMs / 1000, frames: frameCount },
                'max virtual time reached, truncating'
            )
            truncated = true
        }
    } finally {
        captureDone = true
        captureAbortReject = null
        page.off('close', onPageClose)
        page.off('error', onPageError)
        // puppeteer-capture's PuppeteerCapture extends EventEmitter but only
        // declares `on` in its type — `off` exists at runtime.
        ;(recorder as any).off('captureStopped', onCaptureStopped)
        try {
            await recorder.stop()
        } catch (stopErr) {
            if (stopErr instanceof Error && stopErr.message === 'Capture is not in progress') {
                // Recorder already stopped (ffmpeg exited before we called stop) — harmless.
                log.info({ frames: frameCount }, 'recorder already stopped')
            } else {
                // recorder.stop() throws the stored _error when capture was
                // terminated by page close, session disconnect, or ffmpeg crash.
                // Log it so we can see the actual root cause.
                log.error({ err: stopErr, frames: frameCount }, 'recorder.stop() error (root cause)')
            }
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
