import { Browser, Page } from 'puppeteer'
import { launch as launchForCapture } from 'puppeteer-capture'

import { config } from '../config'
import { createLogger } from '../logger'
import { RasterizationMetrics } from '../metrics'

const log = createLogger()

const LAUNCH_ARGS = [
    '--no-sandbox',
    '--disable-dev-shm-usage',
    '--mute-audio',
    ...(process.env.CHROME_HOST_RESOLVER_RULES
        ? [`--host-resolver-rules=${process.env.CHROME_HOST_RESOLVER_RULES}`]
        : []),
]

interface BrowserSlot {
    browser: Browser
    usageCount: number
}

export class BrowserPool {
    private slots = new Map<Page, BrowserSlot>()
    private idle: BrowserSlot[] = []

    constructor(private recycleAfter: number = config.browserRecycleAfter) {}

    private async launchBrowser(): Promise<BrowserSlot> {
        const args = config.disableBrowserSecurity ? [...LAUNCH_ARGS, '--disable-web-security'] : LAUNCH_ARGS
        const browser = await launchForCapture({
            executablePath: process.env.PUPPETEER_EXECUTABLE_PATH || undefined,
            args,
        })
        RasterizationMetrics.browserLaunched()
        return { browser, usageCount: 0 }
    }

    private async closeBrowser(slot: BrowserSlot): Promise<void> {
        try {
            await slot.browser.close()
        } catch (err) {
            log.debug({ err }, 'browser close failed, may already be dead')
        }
    }

    async launch(): Promise<void> {
        // Pre-warm one browser so the first getPage() is fast
        if (this.idle.length === 0) {
            this.idle.push(await this.launchBrowser())
        }
    }

    async getPage(): Promise<Page> {
        let slot: BrowserSlot
        if (this.idle.length > 0) {
            slot = this.idle.pop()!
        } else {
            slot = await this.launchBrowser()
        }

        const page = await slot.browser.newPage()
        slot.usageCount++
        this.slots.set(page, slot)
        RasterizationMetrics.setBrowserCounts(this.slots.size, this.idle.length)
        return page
    }

    async releasePage(page: Page): Promise<void> {
        const slot = this.slots.get(page)
        this.slots.delete(page)

        try {
            await page.close()
        } catch (err) {
            log.debug({ err }, 'page close failed, may already be closed')
        }

        if (!slot) {
            return
        }

        if (slot.usageCount >= this.recycleAfter) {
            log.info({ usage_count: slot.usageCount }, 'recycling browser')
            RasterizationMetrics.browserRecycled()
            await this.closeBrowser(slot)
        } else {
            this.idle.push(slot)
        }
        RasterizationMetrics.setBrowserCounts(this.slots.size, this.idle.length)
    }

    async releaseAllPages(): Promise<void> {
        const pages = [...this.slots.keys()]
        await Promise.all(pages.map((p) => this.releasePage(p)))
    }

    async shutdown(): Promise<void> {
        await this.releaseAllPages()
        await Promise.all(this.idle.map((slot) => this.closeBrowser(slot)))
        this.idle = []
    }

    get stats(): { usageCount: number; activePages: number } {
        let totalUsage = 0
        for (const slot of this.slots.values()) {
            totalUsage += slot.usageCount
        }
        for (const slot of this.idle) {
            totalUsage += slot.usageCount
        }
        return { usageCount: totalUsage, activePages: this.slots.size }
    }
}
