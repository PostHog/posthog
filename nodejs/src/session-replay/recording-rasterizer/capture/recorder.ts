import * as fs from 'fs/promises'
import { Page } from 'puppeteer'

import { config as defaultConfig } from '../config'
import { RasterizationError } from '../errors'
import { type Logger, createLogger } from '../logger'
import { RasterizeRecordingInput, RecordingResult } from '../types'
import { elapsed } from '../utils'
import { BrowserPool } from './browser-pool'
import { buildCaptureConfig, capturePlayback } from './capture'
import { PlayerController, buildPlayerConfig } from './player'

export const playerHtmlCache = {
    _html: null as string | null,

    async load(path?: string): Promise<string> {
        const htmlPath = path || defaultConfig.playerHtmlPath
        this._html = await fs.readFile(htmlPath, 'utf-8')
        return this._html
    },

    get(): string {
        if (!this._html) {
            throw new Error('Player HTML not loaded — call playerHtmlCache.load() before recording')
        }
        return this._html
    },

    reset(): void {
        this._html = null
    },
}

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
}

/**
 * Prepare a browser page for capture: disable iframe sandboxing,
 * set the viewport, and optionally wire up browser log forwarding.
 */
async function preparePage(
    page: Page,
    viewport: { width: number; height: number },
    captureLogs: boolean,
    log: Logger
): Promise<void> {
    if (captureLogs) {
        const browserLog = log.child({ source: 'browser' })
        page.on('console', (msg) => {
            const level = msg.type() === 'error' ? 'error' : msg.type() === 'warn' ? 'warn' : 'info'
            browserLog[level](msg.text())
        })
        page.on('pageerror', (err) => browserLog.error({ type: 'pageerror' }, (err as Error).message))
        page.on('requestfailed', (req) =>
            browserLog.error({ type: 'requestfailed', url: req.url() }, req.failure()?.errorText || 'unknown')
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

    await page.setViewport({ width: viewport.width, height: viewport.height, deviceScaleFactor: 1 })
}

export async function rasterizeRecording(
    pool: BrowserPool,
    input: RasterizeRecordingInput,
    outputPath: string,
    cfg: typeof defaultConfig = defaultConfig,
    log: Logger = createLogger({ session_id: input.session_id, team_id: input.team_id }),
    onProgress?: () => void
): Promise<RecordingResult> {
    validateInput(input)

    const setupStart = process.hrtime()
    const baseHtml = playerHtmlCache.get()
    const captureConfig = buildCaptureConfig(input)

    const page = await pool.getPage()
    let player: PlayerController | null = null
    try {
        const viewport = {
            width: input.viewport_width || 1280,
            height: input.viewport_height || 720,
        }
        await preparePage(page, viewport, cfg.captureBrowserLogs, log)

        player = new PlayerController(page, log)
        const playerConfig = buildPlayerConfig(input, captureConfig.playbackSpeed, cfg)

        log.info('loading player')
        await player.load(baseHtml, cfg.siteUrl, playerConfig)
        log.info('player loaded, waiting for recording data')

        await player.waitForStart(playerConfig)
        log.info('recording started')
        onProgress?.()

        const setupS = elapsed(setupStart)

        const captureResult = await capturePlayback(page, player, captureConfig, outputPath, log, onProgress)

        return {
            video_path: outputPath,
            playback_speed: captureConfig.playbackSpeed,
            capture_duration_s: captureResult.capture_duration_s,
            frame_count: captureResult.frame_count,
            truncated: captureResult.truncated,
            inactivity_periods: captureResult.inactivity_periods,
            custom_fps: captureConfig.outputFps,
            timings: { setup_s: setupS, capture_s: captureResult.timings.capture_s },
        }
    } finally {
        player?.dispose()
        await pool.releasePage(page)
    }
}
