import { Page } from 'puppeteer'
import { PuppeteerScreenRecorder } from 'puppeteer-screen-recorder'

import { BrowserPool } from './browser-pool'
import { InactivityPeriod, RasterizeRecordingInput, RecordingResult } from './types'

const MAX_DIMENSION = 1920
const DEFAULT_WIDTH = 1920
const DEFAULT_HEIGHT = 1080
const RECORDING_BUFFER_SECONDS = 120
const DEFAULT_PLAYBACK_SPEED = 4
const DEFAULT_FPS = 24
const ALLOWED_SCHEMES = ['http:', 'https:']
const REQUIRED_PATH_PREFIX = '/exporter'

export function validateRecordingUrl(url: string): void {
    const parsed = new URL(url)
    if (!ALLOWED_SCHEMES.includes(parsed.protocol)) {
        throw new Error(`Disallowed URL scheme: ${parsed.protocol}`)
    }
    if (!parsed.pathname.startsWith(REQUIRED_PATH_PREFIX)) {
        throw new Error(`Recording URL must point to ${REQUIRED_PATH_PREFIX}, got: ${parsed.pathname}`)
    }
}

export function validateInput(input: RasterizeRecordingInput): void {
    validateRecordingUrl(input.recording_url)

    if (input.playback_speed !== undefined && input.playback_speed <= 0) {
        throw new Error(`playback_speed must be positive, got: ${input.playback_speed}`)
    }
    if (input.recording_duration <= 0) {
        throw new Error(`recording_duration must be positive, got: ${input.recording_duration}`)
    }
    if (input.recording_fps !== undefined && input.recording_fps <= 0) {
        throw new Error(`recording_fps must be positive, got: ${input.recording_fps}`)
    }
}

export function scaleDimensionsIfNeeded(
    width: number,
    height: number,
    maxSize: number = MAX_DIMENSION
): { width: number; height: number } {
    if (width <= maxSize && height <= maxSize) {
        return { width, height }
    }
    if (width > height) {
        const scaleFactor = maxSize / width
        return { width: maxSize, height: Math.floor(height * scaleFactor) }
    }
    const scaleFactor = maxSize / height
    return { width: Math.floor(width * scaleFactor), height: maxSize }
}

export function setupUrlForPlaybackSpeed(recordingUrl: string, playbackSpeed: number): string {
    const url = new URL(recordingUrl)
    url.searchParams.set('playerSpeed', String(playbackSpeed))
    return url.toString()
}

export async function waitForPageReady(page: Page, recordingUrl: string, waitForCssSelector: string): Promise<void> {
    await page.goto(recordingUrl, { waitUntil: 'load', timeout: 30000 })
    try {
        await page.waitForSelector(waitForCssSelector, { visible: true, timeout: 20000 })
    } catch {
        // Selector wait timeout, continue
    }
    try {
        await page.waitForSelector('.Spinner', { hidden: true, timeout: 20000 })
    } catch {
        // Spinner wait timeout, continue
    }
}

export async function verifyInactivityPeriodsAvailable(page: Page): Promise<void> {
    try {
        await page.waitForFunction(
            () => {
                const periods = (window as any).__POSTHOG_INACTIVITY_PERIODS__
                return Array.isArray(periods) && periods.length > 0
            },
            { timeout: 20000 }
        )
    } catch {
        throw new Error(
            'Inactivity periods were not available within 20s after page load. ' +
                'The recording may not have rendered properly.'
        )
    }
}

export async function waitForRecordingWithSegments(
    page: Page,
    maxWaitMs: number,
    playbackStarted: number
): Promise<Record<string, number>> {
    const segmentStartTimestamps: Record<string, number> = {}
    let lastCounter = 0

    while (true) {
        const elapsedMs = Date.now() - playbackStarted
        const remainingMs = maxWaitMs - elapsedMs
        if (remainingMs <= 0) {
            break
        }
        try {
            const handle = await page.waitForFunction(
                (lastCounterVal: number) => {
                    if ((window as any).__POSTHOG_RECORDING_ENDED__) {
                        return { ended: true }
                    }
                    const counter = (window as any).__POSTHOG_SEGMENT_COUNTER__ || 0
                    if (counter > lastCounterVal) {
                        return {
                            counter,
                            segment_start_ts: (window as any).__POSTHOG_CURRENT_SEGMENT_START_TS__,
                        }
                    }
                    return false
                },
                { timeout: remainingMs, polling: 'raf' },
                lastCounter
            )
            const result = (await handle.jsonValue()) as any
            if (result.ended) {
                break
            }
            const segmentStartTs = result.segment_start_ts
            const newCounter = result.counter || 0
            if (segmentStartTs !== undefined && newCounter > lastCounter) {
                const videoTime = (Date.now() - playbackStarted) / 1000
                segmentStartTimestamps[segmentStartTs] = videoTime
                lastCounter = newCounter
            }
        } catch (err) {
            if (!(err instanceof Error && err.name === 'TimeoutError')) {
                console.error('Unexpected error during segment recording:', err)
            }
            break
        }
    }
    return segmentStartTimestamps
}

export async function detectInactivityPeriods(
    page: Page,
    playbackSpeed: number,
    segmentStartTimestamps: Record<string, number>
): Promise<InactivityPeriod[]> {
    const inactivityPeriodsRaw: any[] = await page.evaluate(() => {
        const r = (window as any).__POSTHOG_INACTIVITY_PERIODS__
        if (!r) {
            return []
        }
        return r.map((p: any) => ({
            ts_from_s: Number(p.ts_from_s),
            ts_to_s: Number.isFinite(p.ts_to_s) ? p.ts_to_s : null,
            active: Boolean(p.active),
        }))
    })

    if (segmentStartTimestamps && Object.keys(segmentStartTimestamps).length > 0) {
        let prevPeriodWithRecording: any = null
        for (const period of inactivityPeriodsRaw) {
            const tsFromS = period.ts_from_s
            if (tsFromS !== undefined && segmentStartTimestamps[tsFromS] !== undefined) {
                const rawTimestamp = segmentStartTimestamps[tsFromS]
                period.recording_ts_from_s = rawTimestamp * playbackSpeed
                const tsToS = period.ts_to_s
                if (tsToS !== undefined) {
                    const segmentDuration = tsToS - tsFromS
                    period.recording_ts_to_s = period.recording_ts_from_s + segmentDuration
                }
                if (prevPeriodWithRecording) {
                    prevPeriodWithRecording.recording_ts_to_s = Math.min(
                        prevPeriodWithRecording.recording_ts_to_s,
                        period.recording_ts_from_s
                    )
                }
                prevPeriodWithRecording = period
            }
        }
    }

    return inactivityPeriodsRaw as InactivityPeriod[]
}

export async function rasterizeRecording(
    pool: BrowserPool,
    input: RasterizeRecordingInput,
    outputPath: string
): Promise<RecordingResult> {
    validateInput(input)

    const playbackSpeed = input.playback_speed || DEFAULT_PLAYBACK_SPEED
    const recordingFps = input.recording_fps || DEFAULT_FPS
    const urlWithSpeed = setupUrlForPlaybackSpeed(input.recording_url, playbackSpeed)

    let width = input.screenshot_width || DEFAULT_WIDTH
    let height = input.screenshot_height || DEFAULT_HEIGHT
    const scaled = scaleDimensionsIfNeeded(width, height)
    width = scaled.width
    height = scaled.height

    const customFps = recordingFps * playbackSpeed

    const page = await pool.getPage()
    try {
        await page.setViewport({ width, height, deviceScaleFactor: 1 })

        // Resize the browser window to match the viewport. Page.startScreencast
        // captures at the outer window size, not the CSS viewport. In headless mode
        // the default window can be much smaller than the viewport we set.
        const cdp = await (page as any).target().createCDPSession()
        const { windowId } = await cdp.send('Browser.getWindowForTarget')
        await cdp.send('Browser.setWindowBounds', {
            windowId,
            bounds: { width, height },
        })
        await cdp.detach()

        const recorderConfig = {
            followNewTab: false,
            fps: customFps,
            ffmpeg_Path: process.env.FFMPEG_PATH || undefined,
            videoFrame: { width, height },
            videoCrf: 23,
            videoCodec: 'libx264',
            videoPreset: 'veryfast',
            videoBitrate: 1000 * (0.5 * playbackSpeed),
            autopad: { color: 'black' },
            aspectRatio: '16:9',
        }

        const recorder = new PuppeteerScreenRecorder(page, recorderConfig)
        const recordStarted = Date.now()

        await recorder.start(outputPath)
        try {
            await waitForPageReady(page, urlWithSpeed, input.wait_for_css_selector)

            const readyAt = Date.now()
            await new Promise((r) => setTimeout(r, 500))
            await verifyInactivityPeriodsAvailable(page)

            const maxWaitMs =
                Math.floor((input.recording_duration / playbackSpeed) * 1000) + RECORDING_BUFFER_SECONDS * 1000
            const segmentStartTimestamps = await waitForRecordingWithSegments(page, maxWaitMs, readyAt)
            const inactivityPeriods = await detectInactivityPeriods(page, playbackSpeed, segmentStartTimestamps)

            await recorder.stop()

            const preRoll = Math.max(0, (readyAt - recordStarted) / 1000)

            return {
                video_path: outputPath,
                pre_roll: preRoll,
                playback_speed: playbackSpeed,
                measured_width: width,
                inactivity_periods: inactivityPeriods,
                segment_start_timestamps: segmentStartTimestamps,
                custom_fps: customFps,
            }
        } catch (err) {
            await recorder.stop().catch(() => {})
            throw err
        }
    } finally {
        await pool.releasePage(page)
    }
}
