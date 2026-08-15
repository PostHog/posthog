import * as fs from 'fs/promises'
import { CDPSession, Page } from 'puppeteer'

import { config as defaultConfig } from '~/session-replay/recording-rasterizer/config'
import { RasterizationError } from '~/session-replay/recording-rasterizer/errors'
import { type Logger, createLogger } from '~/session-replay/recording-rasterizer/logger'
import { RasterizationMetrics } from '~/session-replay/recording-rasterizer/metrics'

const BEGINFRAME_WARN_AFTER_MS = 15_000

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

/**
 * A browser page prepared for video capture.
 *
 * Holds the Puppeteer page along with the player URL and HTML content
 * needed by request interception and navigation. Handles viewport setup,
 * optional log forwarding, and frame filtering for puppeteer-capture.
 */
export class CapturePage {
    // Set at the site that detects a fatal cause (e.g. the beginFrame compositor deadlock)
    // so the generic captureStopped handler can attribute the abort instead of guessing.
    fatalError: RasterizationError | null = null

    private readonly beginFrameTimeoutMs = defaultConfig.beginFrameTimeoutMs

    private constructor(
        readonly page: Page,
        readonly playerUrl: string,
        readonly playerHtml: string
    ) {}

    /**
     * Prepare a pooled page for capture: set the viewport, optionally
     * wire up browser log forwarding, and hide grandchild frames.
     */
    static async prepare(
        page: Page,
        viewport: { width: number; height: number },
        playerUrl: string,
        playerHtml: string,
        captureLogs: boolean,
        log: Logger
    ): Promise<CapturePage> {
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

        await page.setViewport({ width: viewport.width, height: viewport.height, deviceScaleFactor: 1 })

        // Hide grandchild frames from puppeteer-capture so it doesn't call
        // evaluate() on third-party widget iframes whose execution contexts
        // can be destroyed at any time.
        const mainFrame = page.mainFrame()
        const originalFrames = page.frames.bind(page)
        ;(page as any).frames = (): ReturnType<Page['frames']> =>
            originalFrames().filter((f) => f === mainFrame || f.parentFrame() === mainFrame)

        return new CapturePage(page, playerUrl, playerHtml)
    }

    /**
     * Wrap timer and rAF APIs so that individual callback errors are
     * caught instead of crashing the entire capture. Must be called
     * AFTER recorder.start() — puppeteer-capture installs virtual-time
     * overrides on rAF/setTimeout/setInterval during start(), and this
     * wraps those overrides with try/catch.
     */
    async installCallbackErrorGuards(): Promise<void> {
        await this.page.evaluate(() => {
            function wrapTimerApi(name: string): void {
                const original = (window as any)[name]
                ;(window as any)[name] = (callback: any, ...rest: any[]) => {
                    if (typeof callback !== 'function') {
                        return original(callback, ...rest)
                    }
                    return original(
                        (...args: any[]) => {
                            try {
                                return callback(...args)
                            } catch (e) {
                                console.error(`[rasterizer] ${name} callback error (swallowed):`, e)
                            }
                        },
                        ...rest
                    )
                }
            }
            wrapTimerApi('requestAnimationFrame')
            wrapTimerApi('setTimeout')
            wrapTimerApi('setInterval')
        })
    }

    /**
     * Wrap CDP session to override screenshot format and gate beginFrame
     * on pending stylesheet requests. Must be called before captureVideo().
     */
    installCDPGuards(
        screenshotFormat: 'jpeg' | 'png',
        screenshotQuality: number | undefined,
        waitForRequestsSettled: () => Promise<void>,
        log: Logger = createLogger()
    ): void {
        const page = this.page
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

                    // A frame can legitimately stall for tens of seconds: content that reveals many
                    // huge images at once (e.g. resuming from an inactivity skip onto a gallery)
                    // forces every software image decode to finish inside this one beginFrame under
                    // --run-all-compositor-stages-before-draw. Warn at the soft threshold so slow
                    // frames are visible, and only abort at the hard cap.
                    let timedOut = false
                    let timeoutHandle: ReturnType<typeof setTimeout>
                    let warnHandle: ReturnType<typeof setTimeout>
                    const sendStart = process.hrtime.bigint()
                    const elapsedS = (): number => Number(process.hrtime.bigint() - sendStart) / 1e9
                    const timeout = new Promise<never>((_, reject) => {
                        warnHandle = setTimeout(() => {
                            log.warn({ params }, `beginFrame slow (>${BEGINFRAME_WARN_AFTER_MS / 1000}s), waiting`)
                        }, BEGINFRAME_WARN_AFTER_MS)
                        timeoutHandle = setTimeout(() => {
                            timedOut = true
                            reject(new Error(`beginFrame timeout (${this.beginFrameTimeoutMs / 1000}s)`))
                        }, this.beginFrameTimeoutMs)
                    })
                    try {
                        const result = await Promise.race([originalSend(method as any, params), timeout])
                        const stallS = elapsedS()
                        if (stallS * 1000 >= BEGINFRAME_WARN_AFTER_MS) {
                            RasterizationMetrics.observeBeginFrameStall(stallS)
                            log.warn({ stall_s: +stallS.toFixed(1) }, 'beginFrame recovered after stall')
                        }
                        return result
                    } catch (err) {
                        if (timedOut) {
                            this.fatalError = new RasterizationError(
                                `beginFrame timeout (${this.beginFrameTimeoutMs / 1000}s) — compositor deadlock`,
                                true,
                                'BEGINFRAME_DEADLOCK'
                            )
                            log.error({ params }, 'beginFrame timed out, detaching CDP session')
                            try {
                                await session.detach()
                            } catch {
                                // session may already be disconnected
                            }
                            // Throw the typed error so this path classifies as BEGINFRAME_DEADLOCK even
                            // when the rejection propagates via waitForTimeout instead of captureStopped.
                            throw this.fatalError
                        }
                        throw err
                    } finally {
                        clearTimeout(timeoutHandle!)
                        clearTimeout(warnHandle!)
                    }
                }
                return originalSend(method as any, ...args)
            }
            return session
        }
    }
}
