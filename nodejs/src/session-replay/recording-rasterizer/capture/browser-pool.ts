import { Browser, Page } from 'puppeteer'
import { launch as launchForCapture } from 'puppeteer-capture'

import { config } from '~/session-replay/recording-rasterizer/config'
import { createLogger } from '~/session-replay/recording-rasterizer/logger'
import { RasterizationMetrics } from '~/session-replay/recording-rasterizer/metrics'

const log = createLogger()

function resolveProxyArgs(): string[] {
    const killed = ['false', '0', 'no', 'off'].includes((process.env.RASTERIZER_USE_PROXY ?? '').trim().toLowerCase())
    const upstream =
        process.env.HTTPS_PROXY || process.env.HTTP_PROXY || process.env.https_proxy || process.env.http_proxy
    if (!upstream) {
        return []
    }
    if (killed) {
        log.warn(
            { RASTERIZER_USE_PROXY: process.env.RASTERIZER_USE_PROXY },
            'RASTERIZER_USE_PROXY disables egress proxy — chrome will dial direct'
        )
        return []
    }
    // Chrome's --proxy-server takes scheme://host:port — drop userinfo / path.
    // `new URL("smokescreen:4750")` parses as scheme-only with empty host; fail
    // fast rather than silently rendering --proxy-server=smokescreen:// (which
    // would bypass the proxy and break egress containment).
    const u = new URL(upstream)
    if (!u.host) {
        throw new Error(
            `Egress proxy URL has no host — pass a fully-qualified URL like http://smokescreen:4750, not "${upstream}"`
        )
    }
    const proxyServer = `${u.protocol}//${u.host}`
    log.info({ proxy_server: proxyServer }, 'chrome routing egress through proxy')
    return [
        `--proxy-server=${proxyServer}`,
        // Override Chrome's implicit loopback/link-local bypass so customer
        // DOM pointing at localhost / 127.0.0.1 / 169.254.169.254 (IMDS)
        // still goes through the proxy.
        '--proxy-bypass-list=<-loopback>',
    ]
}

interface BrowserSlot {
    browser: Browser
    usageCount: number
}

export class BrowserPool {
    private slots = new Map<Page, BrowserSlot>()
    private idle: BrowserSlot[] = []
    private proxyArgs = resolveProxyArgs()

    constructor(private recycleAfter: number = config.browserRecycleAfter) {}

    private launchArgs(): string[] {
        return [
            '--disable-dev-shm-usage',
            // Pin crashpad to /tmp — the container root filesystem is read-only.
            '--crash-dumps-dir=/tmp/chrome-crash-dumps',
            '--mute-audio',
            ...this.proxyArgs,
            ...(config.disableBrowserSecurity ? ['--disable-web-security'] : []),
            ...(process.env.CHROME_HOST_RESOLVER_RULES
                ? [`--host-resolver-rules=${process.env.CHROME_HOST_RESOLVER_RULES}`]
                : []),
        ]
    }

    private async launchBrowser(): Promise<BrowserSlot> {
        const browser = await launchForCapture({
            executablePath: process.env.PUPPETEER_EXECUTABLE_PATH || undefined,
            args: this.launchArgs(),
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
        if (this.idle.length === 0) {
            this.idle.push(await this.launchBrowser())
        }
    }

    // Fail fast at startup if the configured browser isn't chrome-headless-shell.
    // puppeteer-capture drives deterministic frame capture through the CDP
    // HeadlessExperimental.beginFrame command, which only exists in Linux
    // chrome-headless-shell — not stock Chromium/Chrome. When the wrong binary is
    // launched, puppeteer-capture rejects it mid-render with a bare
    // "Not chrome-headless-shell: <path>", which surfaces deep inside a child
    // workflow where it's hard to recognize. This reproduces puppeteer-capture's own
    // spawnfile check (it matches on the `chrome-headless-shell` substring) at launch
    // and raises an actionable error pointing at the fix.
    async assertHeadlessShell(): Promise<void> {
        await this.launch()
        const spawnfile = this.idle[0]?.browser.process()?.spawnfile
        if (!spawnfile || !spawnfile.includes('chrome-headless-shell')) {
            const configured = process.env.PUPPETEER_EXECUTABLE_PATH
            throw new Error(
                `Rasterizer browser is not chrome-headless-shell (launched: ${spawnfile ?? 'unknown'}). ` +
                    `Deterministic frame capture needs Linux chrome-headless-shell, which supports the ` +
                    `HeadlessExperimental.beginFrame CDP command; stock Chromium/Chrome does not. ` +
                    (configured
                        ? `PUPPETEER_EXECUTABLE_PATH is set to "${configured}" — point it at a chrome-headless-shell binary. `
                        : `Set PUPPETEER_EXECUTABLE_PATH to a chrome-headless-shell binary. `) +
                    `Run the worker via the canonical image (Dockerfile.recording-rasterizer) or ` +
                    `bin/temporal-recording-rasterizer-worker, which install and pin it.`
            )
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
