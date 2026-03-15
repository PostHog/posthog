import { Browser, Page } from 'puppeteer'
import { launch as launchForCapture } from 'puppeteer-capture'

import { config } from './config'

const LAUNCH_ARGS = [
    '--no-sandbox',
    '--disable-dev-shm-usage',
    '--mute-audio',
    ...(process.env.CHROME_HOST_RESOLVER_RULES
        ? [`--host-resolver-rules=${process.env.CHROME_HOST_RESOLVER_RULES}`]
        : []),
]

export class BrowserPool {
    private browser: Browser | null = null
    private usageCount = 0
    private pages = new Set<Page>()
    private recycling: Promise<void> | null = null

    constructor(private recycleAfter: number = config.browserRecycleAfter) {}

    private launching: Promise<void> | null = null

    async launch(): Promise<void> {
        if (this.browser) {
            return
        }
        if (this.launching) {
            return this.launching
        }
        this.launching = (async () => {
            const args = config.disableBrowserSecurity ? [...LAUNCH_ARGS, '--disable-web-security'] : LAUNCH_ARGS
            this.browser = await launchForCapture({
                executablePath: process.env.PUPPETEER_EXECUTABLE_PATH || undefined,
                args,
            })
            this.usageCount = 0
        })()
        try {
            await this.launching
        } finally {
            this.launching = null
        }
    }

    async getPage(): Promise<Page> {
        if (this.recycling) {
            await this.recycling
        }

        if (!this.browser) {
            await this.launch()
        }

        const page = await this.browser!.newPage()
        this.pages.add(page)
        this.usageCount++
        return page
    }

    async releasePage(page: Page): Promise<void> {
        this.pages.delete(page)
        try {
            await page.close()
        } catch {
            // Page may already be closed
        }

        if (this.usageCount >= this.recycleAfter && this.pages.size === 0) {
            try {
                await this.recycle()
            } catch (err) {
                console.error('Browser recycle failed:', err)
            }
        }
    }

    /** Close all tracked pages without shutting down the browser. */
    async releaseAllPages(): Promise<void> {
        const pages = [...this.pages]
        this.pages.clear()
        await Promise.all(
            pages.map((p) =>
                p.close().catch(() => {
                    /* already closed */
                })
            )
        )
    }

    async recycle(): Promise<void> {
        if (this.recycling) {
            return this.recycling
        }
        this.recycling = this._doRecycle()
        try {
            await this.recycling
        } finally {
            this.recycling = null
        }
    }

    private async _doRecycle(): Promise<void> {
        await this.shutdown()
        await this.launch()
    }

    async shutdown(): Promise<void> {
        this.pages.clear()
        if (this.browser) {
            try {
                await this.browser.close()
            } catch {
                // Ignore cleanup errors
            }
            this.browser = null
        }
    }

    get stats(): { usageCount: number; activePages: number } {
        return { usageCount: this.usageCount, activePages: this.pages.size }
    }
}
