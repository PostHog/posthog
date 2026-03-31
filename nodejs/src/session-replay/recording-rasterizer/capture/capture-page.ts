import * as fs from 'fs/promises'
import { CDPSession, Page } from 'puppeteer'

import { config as defaultConfig } from '../config'
import { type Logger } from '../logger'

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
     * Wrap CDP session to override screenshot format and gate beginFrame
     * on pending stylesheet requests. Must be called before captureVideo().
     */
    installCDPGuards(
        screenshotFormat: 'jpeg' | 'png',
        screenshotQuality: number | undefined,
        waitForRequestsSettled: () => Promise<void>
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

                    return originalSend(method as any, params)
                }
                return originalSend(method as any, ...args)
            }
            return session
        }
    }
}
