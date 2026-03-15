import * as fs from 'fs/promises'
import { Page } from 'puppeteer'
import { PuppeteerCaptureFormat, capture as captureVideo } from 'puppeteer-capture'

import { BrowserPool } from './browser-pool'
import { config as defaultConfig } from './config'
import { RasterizationError } from './errors'
import { RasterizeRecordingInput, RecordingResult } from './types'
import { elapsed } from './utils'

const DEFAULT_PLAYBACK_SPEED = 4
const DEFAULT_FPS = 24

let cachedPlayerHtml: string | null = null

export async function loadPlayerHtml(path?: string): Promise<string> {
    const htmlPath = path || defaultConfig.playerHtmlPath
    cachedPlayerHtml = await fs.readFile(htmlPath, 'utf-8')
    return cachedPlayerHtml
}

export function getPlayerHtml(): string {
    if (!cachedPlayerHtml) {
        throw new Error('Player HTML not loaded — call loadPlayerHtml() before recording')
    }
    return cachedPlayerHtml
}

export function validateInput(input: RasterizeRecordingInput): void {
    if (!input.session_id) {
        throw new RasterizationError('session_id is required', false)
    }
    if (!input.team_id || input.team_id <= 0) {
        throw new RasterizationError('team_id must be a positive integer', false)
    }
    if (input.playback_speed !== undefined && input.playback_speed <= 0) {
        throw new RasterizationError(`playback_speed must be positive, got: ${input.playback_speed}`, false)
    }
    if (input.capture_timeout != null && input.capture_timeout <= 0) {
        throw new RasterizationError(`capture_timeout must be positive, got: ${input.capture_timeout}`, false)
    }
    if (input.recording_fps !== undefined && input.recording_fps <= 0) {
        throw new RasterizationError(`recording_fps must be positive, got: ${input.recording_fps}`, false)
    }
}

async function fetchPlayerError(page: Page): Promise<RasterizationError | null> {
    const error = await page.evaluate(() => (window as any).__POSTHOG_PLAYER_ERROR__)
    if (!error) {
        return null
    }
    return new RasterizationError(`[${error.code}] ${error.message}`, error.retryable)
}

export function buildPlayerHtml(
    baseHtml: string,
    input: RasterizeRecordingInput,
    playbackSpeed: number,
    cfg: typeof defaultConfig
): string {
    const playerConfig = {
        recordingApiBaseUrl: cfg.recordingApiBaseUrl,
        recordingApiSecret: cfg.recordingApiSecret,
        teamId: input.team_id,
        sessionId: input.session_id,
        playbackSpeed,
        skipInactivity: input.skip_inactivity !== false,
        mouseTail: input.mouse_tail !== false,
        showMetadataFooter: input.show_metadata_footer,
        startTimestamp: input.start_timestamp,
        endTimestamp: input.end_timestamp,
        viewportEvents: input.viewport_events || [],
    }

    const configScript = `<script>window.__POSTHOG_PLAYER_CONFIG__ = ${JSON.stringify(playerConfig)};</script>`
    return baseHtml.replace('</head>', `${configScript}\n</head>`)
}

export async function setupAndLoadPlayer(
    page: Page,
    input: RasterizeRecordingInput,
    playerHtml: string,
    playbackSpeed: number,
    cfg: typeof defaultConfig = defaultConfig
): Promise<void> {
    const html = buildPlayerHtml(playerHtml, input, playbackSpeed, cfg)
    const playerUrl = `${cfg.siteUrl}/player`

    await page.setRequestInterception(true)
    page.on('request', (request) => {
        const url = request.url()
        if (url === playerUrl) {
            void request.respond({
                status: 200,
                contentType: 'text/html',
                body: html,
            })
        } else {
            void request.continue()
        }
    })

    await page.goto(playerUrl, { waitUntil: 'load', timeout: 30000 })
}

export async function waitForRecordingStarted(page: Page, sessionId: string): Promise<void> {
    // The JS bundle may not have registered its event listener yet when we
    // dispatch posthog-player-init. Poll with re-dispatches until the player
    // signals it has started (or errored).
    const deadline = Date.now() + 30000
    const redispatchInterval = 500

    while (Date.now() < deadline) {
        const state = await page.evaluate(() => ({
            started: (window as any).__POSTHOG_RECORDING_STARTED__,
            error: (window as any).__POSTHOG_PLAYER_ERROR__,
        }))

        if (state.started || state.error) {
            break
        }

        // Re-dispatch init in case the listener wasn't registered yet
        await page.evaluate(() => {
            window.dispatchEvent(new Event('posthog-player-init'))
        })

        await new Promise((resolve) => setTimeout(resolve, redispatchInterval))
    }

    const playerError = await fetchPlayerError(page)
    if (playerError) {
        throw playerError
    }

    const started = await page.evaluate(() => (window as any).__POSTHOG_RECORDING_STARTED__)
    if (!started) {
        throw new RasterizationError(`Recording did not start within 30s for session ${sessionId}`, true)
    }
}

async function fetchInactivityPeriods(
    page: Page
): Promise<Array<{ ts_from_s: number; ts_to_s: number | null; active: boolean }>> {
    return page.evaluate(() => {
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
}

export async function rasterizeRecording(
    pool: BrowserPool,
    input: RasterizeRecordingInput,
    outputPath: string,
    cfg: typeof defaultConfig = defaultConfig
): Promise<RecordingResult> {
    validateInput(input)

    const setupStart = process.hrtime()
    const playerHtml = getPlayerHtml()
    const playbackSpeed = input.playback_speed || DEFAULT_PLAYBACK_SPEED
    const recordingFps = input.recording_fps || DEFAULT_FPS

    const page = await pool.getPage()
    try {
        if (cfg.captureBrowserLogs) {
            page.on('console', (msg) => console.log(`[browser:${msg.type()}]`, msg.text()))
            page.on('pageerror', (err) => console.error('[browser:error]', (err as Error).message))
            page.on('requestfailed', (req) =>
                console.error('[browser:requestfailed]', req.url(), req.failure()?.errorText)
            )
        }

        // Prevent rrweb's replay iframe from being sandboxed.
        // rrweb sets sandbox="allow-same-origin" which blocks script execution.
        // puppeteer-capture needs to evaluate() in all frames to inject virtual
        // time shims — without this, frame.evaluate() hangs on sandboxed iframes.
        await page.evaluateOnNewDocument(() => {
            const origSetAttribute = Element.prototype.setAttribute
            Element.prototype.setAttribute = function (name: string, value: string) {
                if (this.tagName === 'IFRAME' && name === 'sandbox') {
                    return
                }
                return origSetAttribute.call(this, name, value)
            }
        })

        const vpWidth = input._viewport_width || 1920
        const vpHeight = input._viewport_height || 1080
        await page.setViewport({ width: vpWidth, height: vpHeight, deviceScaleFactor: 1 })

        console.log('[rasterizer] loading player...')
        await setupAndLoadPlayer(page, input, playerHtml, playbackSpeed, cfg)
        console.log('[rasterizer] player loaded, waiting for recording data...')

        // waitForRecordingStarted dispatches posthog-player-init repeatedly until
        // the JS bundle registers its listener and signals recording started
        await waitForRecordingStarted(page, input.session_id)
        console.log('[rasterizer] recording started')

        const setupS = elapsed(setupStart)
        const captureStart = process.hrtime()

        // Capture at recordingFps * playbackSpeed so that after setpts
        // stretches timestamps by playbackSpeed, the output plays at
        // recordingFps in real-time.
        // e.g. 3fps output × 8x speed = 24fps capture → stretched 8x → 3fps.
        const captureFps = recordingFps * playbackSpeed

        // Start capture FIRST — this installs virtual time shims (Date.now,
        // setTimeout, rAF). Then dispatch player-start so all playback happens
        // under deterministic virtual time control. rrweb's rAF-based rendering
        // fires naturally as we advance virtual time in the loop below.
        let frameCount = 0
        const recorder = await captureVideo(page, {
            fps: captureFps,
            format: PuppeteerCaptureFormat.MP4('veryfast', 'libx264'),
            // eslint-disable-next-line @typescript-eslint/require-await
            customFfmpegConfig: async (ffmpeg: any) => {
                const opts = ['-crf 23', '-pix_fmt yuv420p', '-movflags +faststart']
                if (input.trim) {
                    opts.push(`-t ${input.trim}`)
                }
                ffmpeg.outputOptions(opts)
                // Stretch timestamps so capture at Nx speed outputs real-time video.
                // This eliminates the need for a separate post-processing encode pass.
                if (playbackSpeed > 1) {
                    ffmpeg.videoFilters(`setpts=${playbackSpeed}*PTS`)
                }
            },
            ffmpeg: process.env.FFMPEG_PATH || undefined,
        })
        const logInterval = Math.max(10, captureFps) // log roughly once per second of capture
        recorder.on('frameCaptured', () => {
            frameCount++
            if (frameCount % logInterval === 0) {
                const virtualS = (frameCount / captureFps).toFixed(1)
                const realS = elapsed(captureStart).toFixed(1)
                console.log(`[rasterizer] frame ${frameCount} (virtual=${virtualS}s, wall=${realS}s)`)
            }
        })

        let virtualElapsed = 0
        try {
            await recorder.start(outputPath)
            const vp = page.viewport()
            console.log(`[rasterizer] capture started (${captureFps}fps, ${vp?.width}x${vp?.height})`)

            await page.evaluate(() => {
                window.dispatchEvent(new Event('posthog-player-start'))
            })
            console.log('[rasterizer] playback started, advancing virtual time...')

            // Advance virtual time until the recording ends or we hit the timeout.
            // puppeteer-capture's waitForTimeout advances the virtual clock; rrweb's
            // shimmed timers fire deterministically within that virtual time.
            const captureTimeoutMs = input.capture_timeout ? input.capture_timeout * 1000 : Infinity
            // Stop the capture loop early when we've captured enough frames
            // for the trim duration. ffmpeg -t handles the precise cut, but
            // without this the loop would keep advancing virtual time wastefully.
            const trimFrameLimit = input.trim ? input.trim * recordingFps : Infinity
            const checkIntervalMs = 1000

            while (virtualElapsed < captureTimeoutMs) {
                await recorder.waitForTimeout(checkIntervalMs)
                virtualElapsed += checkIntervalMs

                if (frameCount >= trimFrameLimit) {
                    console.log(`[rasterizer] trim limit reached (${input.trim}s, ${frameCount} frames)`)
                    break
                }

                const ended = await page.evaluate(() => (window as any).__POSTHOG_RECORDING_ENDED__)
                if (ended) {
                    console.log(
                        `[rasterizer] recording ended at virtual=${virtualElapsed / 1000}s, frames=${frameCount}`
                    )
                    break
                }
            }

            if (virtualElapsed >= captureTimeoutMs) {
                console.log(`[rasterizer] capture timeout reached (${captureTimeoutMs / 1000}s)`)
            }
        } finally {
            try {
                await recorder.stop()
            } catch {
                // ffmpeg process may already be dead
            }
        }

        const rawStat = await fs.stat(outputPath)
        console.log(`[rasterizer] capture stopped, raw file: ${rawStat.size} bytes`)

        const inactivityPeriods = await fetchInactivityPeriods(page)
        // frameCount / recordingFps = total frames expressed as video seconds.
        // When trim is set, ffmpeg -t caps the actual output — use that as
        // the authoritative duration since ffmpeg may discard trailing frames.
        const rawDurationS = frameCount / recordingFps
        const captureDurationS = input.trim ? Math.min(rawDurationS, input.trim) : rawDurationS

        return {
            video_path: outputPath,
            playback_speed: playbackSpeed,
            capture_duration_s: captureDurationS,
            inactivity_periods: inactivityPeriods,
            custom_fps: recordingFps,
            timings: { setup_s: setupS, capture_s: elapsed(captureStart) },
        }
    } finally {
        await pool.releasePage(page)
    }
}
