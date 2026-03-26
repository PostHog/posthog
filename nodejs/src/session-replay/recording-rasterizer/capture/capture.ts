import * as fs from 'fs/promises'
import { CDPSession, Page } from 'puppeteer'
import { PuppeteerCaptureFormat, capture as captureVideo } from 'puppeteer-capture'

import { config } from '../config'
import { RasterizationError } from '../errors'
import { type Logger, createLogger } from '../logger'
import { InactivityPeriod, RasterizeRecordingInput, RecordingResult } from '../types'
import { elapsed } from '../utils'
import { AssetProxy } from './asset-proxy'
import { PlayerController } from './player'

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
    }
}

/**
 * Hide grandchild frames from puppeteer-capture so it doesn't call
 * evaluate() on third-party widget iframes whose execution contexts
 * can be destroyed at any time.
 */
function hideGrandchildFrames(page: Page): void {
    const mainFrame = page.mainFrame()
    const originalFrames = page.frames.bind(page)
    ;(page as any).frames = (): ReturnType<Page['frames']> =>
        originalFrames().filter((f) => f === mainFrame || f.parentFrame() === mainFrame)
}

/**
 * Wrap CDP session to override screenshot format and gate beginFrame
 * on pending stylesheet requests. Must be called before captureVideo().
 */
function installCDPGuards(
    page: Page,
    screenshotFormat: 'jpeg' | 'png',
    screenshotQuality: number | undefined,
    waitForRequestsSettled: () => Promise<void>
): void {
    const originalCreateCDPSession = page.createCDPSession.bind(page)
    ;(page as any).createCDPSession = async (): Promise<CDPSession> => {
        const session = await originalCreateCDPSession()
        const originalSend = session.send.bind(session)
        ;(session as any).send = async (method: string, ...args: any[]): Promise<any> => {
            if (method === 'HeadlessExperimental.beginFrame') {
                const params = args[0] ?? {}
                if (screenshotFormat !== 'png') {
                    params.screenshot = { format: screenshotFormat }
                    if (screenshotFormat === 'jpeg' && screenshotQuality != null) {
                        params.screenshot.quality = screenshotQuality
                    }
                }

                await waitForRequestsSettled()

                return originalSend(method as any, params)
            }
            return originalSend(method as any, ...args)
        }
        return session
    }
}

export async function capturePlayback(
    page: Page,
    player: PlayerController,
    assetProxy: AssetProxy,
    captureConfig: CaptureConfig,
    outputPath: string,
    log: Logger = createLogger(),
    onProgress?: () => void
): Promise<
    Pick<RecordingResult, 'capture_duration_s' | 'frame_count' | 'truncated' | 'inactivity_periods' | 'timings'>
> {
    const captureStart = process.hrtime()
    let frameCount = 0

    hideGrandchildFrames(page)
    installCDPGuards(page, config.screenshotFormat, config.screenshotJpegQuality, () => assetProxy.waitForSettled())

    // Start capture first — installs virtual time shims before playback.
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
            ffmpeg.on('stderr', (line: string) => log.debug({ ffmpeg: line }, 'ffmpeg'))
            ffmpeg.on('error', (err: Error) => log.error({ err }, 'ffmpeg error'))
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
