import puppeteer, { Browser, Page } from 'puppeteer'

import { config } from './config'

const LAUNCH_ARGS = ['--no-sandbox', '--disable-dev-shm-usage', '--use-gl=swiftshader', '--disable-software-rasterizer']

export class BrowserPool {
    private browser: Browser | null = null
    private usageCount = 0
    private activePages = 0
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
            this.browser = await puppeteer.launch({
                headless: config.headless,
                executablePath: process.env.PUPPETEER_EXECUTABLE_PATH || undefined,
                args: LAUNCH_ARGS,
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
        // Wait if a recycle is in progress
        if (this.recycling) {
            await this.recycling
        }

        if (!this.browser) {
            await this.launch()
        }

        const page = await this.browser!.newPage()
        this.activePages++
        this.usageCount++
        return page
    }

    async releasePage(page: Page): Promise<void> {
        try {
            await page.close()
        } catch {
            // Page may already be closed
        }
        if (this.activePages > 0) {
            this.activePages--
        }

        if (this.usageCount >= this.recycleAfter && this.activePages === 0) {
            try {
                await this.recycle()
            } catch (err) {
                console.error('Browser recycle failed:', err)
            }
        }
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
        return { usageCount: this.usageCount, activePages: this.activePages }
    }
}
