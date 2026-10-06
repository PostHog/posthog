import { Browser, Page } from 'puppeteer'
import { launch as launchForCapture } from 'puppeteer-capture'

import { config } from '~/session-replay/recording-rasterizer/config'
import { resolveEgressProxyUrl } from '~/session-replay/recording-rasterizer/egress-proxy'
import { createLogger } from '~/session-replay/recording-rasterizer/logger'
import { RasterizationMetrics } from '~/session-replay/recording-rasterizer/metrics'

const log = createLogger()

function resolveProxyArgs(): string[] {
    const upstream = resolveEgressProxyUrl()
    if (!upstream) {
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

// Chrome renders recording content the customer's visitors produced, so it must not hold the
// worker's secrets in its address space. puppeteer-core defaults the browser environment to this
// process's own, which carries SECRET_KEY, INTERNAL_API_SECRET and the pod's AWS credentials, so the
// launch names what Chrome gets instead.
const CHROME_ENV_ALLOWLIST = [
    // Chrome resolves its helper binaries through PATH.
    'PATH',
    // Chrome puts its profile, cache and crash state below HOME, or below the XDG paths when set.
    'HOME',
    'XDG_CONFIG_HOME',
    'XDG_CACHE_HOME',
    'XDG_RUNTIME_DIR',
    // The container root filesystem is read-only, so temporary files must go where TMPDIR points.
    'TMPDIR',
    // The locale decides text shaping, and the timezone decides the timestamps the player draws.
    'LANG',
    'LANGUAGE',
    'LC_ALL',
    'LC_CTYPE',
    'TZ',
    // fontconfig reads these when an image keeps its font configuration outside /etc/fonts. Without
    // the fonts, the rendered frames fall back to boxes.
    'FONTCONFIG_PATH',
    'FONTCONFIG_FILE',
]

function chromeEnv(): NodeJS.ProcessEnv {
    const env: NodeJS.ProcessEnv = {}
    for (const name of CHROME_ENV_ALLOWLIST) {
        const value = process.env[name]
        if (value !== undefined) {
            env[name] = value
        }
    }
    return env
}

interface BrowserSlot {
    browser: Browser
    usageCount: number
    closing?: boolean
}

export class BrowserPool {
    private slots = new Map<Page, BrowserSlot>()
    private idle: BrowserSlot[] = []
    private proxyArgs = resolveProxyArgs()
    private shuttingDown = false

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
            env: chromeEnv(),
        })
        RasterizationMetrics.browserLaunched()
        const slot: BrowserSlot = { browser, usageCount: 0 }
        browser.on('disconnected', () => this.handleDisconnect(slot))
        return slot
    }

    // A crashed browser must not be handed out again: evict it from the idle pool
    // and drop any page entries still pointing at it.
    private handleDisconnect(slot: BrowserSlot): void {
        // During pod shutdown Chrome can die before closeBrowser marks the slot; don't count that as a crash.
        if (slot.closing || this.shuttingDown) {
            return
        }
        const idleIdx = this.idle.indexOf(slot)
        if (idleIdx !== -1) {
            this.idle.splice(idleIdx, 1)
        }
        for (const [page, s] of this.slots) {
            if (s === slot) {
                this.slots.delete(page)
            }
        }
        RasterizationMetrics.browserCrashed()
        log.warn({ usage_count: slot.usageCount }, 'browser disconnected unexpectedly, evicted from pool')
        RasterizationMetrics.setBrowserCounts(this.slots.size, this.idle.length)
    }

    private async closeBrowser(slot: BrowserSlot): Promise<void> {
        slot.closing = true
        try {
            await slot.browser.close()
        } catch (err) {
            log.debug({ err }, 'browser close failed, may already be dead')
        }
    }

    // puppeteer-capture only rejects a non-chrome-headless-shell binary when a capture attaches. This check
    // runs before the worker reports ready, so a bad PUPPETEER_EXECUTABLE_PATH fails the pod instead of every render.
    async launch(): Promise<void> {
        if (this.idle.length > 0) {
            return
        }
        const slot = await this.launchBrowser()
        const spawnfile = slot.browser.process()?.spawnfile
        if (!spawnfile?.includes('chrome-headless-shell')) {
            await this.closeBrowser(slot)
            throw new Error(
                `Browser is not chrome-headless-shell: "${spawnfile ?? 'unknown'}". Set PUPPETEER_EXECUTABLE_PATH to a chrome-headless-shell binary`
            )
        }
        this.idle.push(slot)
    }

    async getPage(): Promise<Page> {
        let slot: BrowserSlot
        if (this.idle.length > 0) {
            slot = this.idle.pop()!
        } else {
            slot = await this.launchBrowser()
        }
        let page: Page
        try {
            page = await slot.browser.newPage()
        } catch (err) {
            // The slot is already out of the idle list, so a live-but-unresponsive browser would
            // otherwise be orphaned as a zombie Chrome process (`disconnected` only fires when the
            // process actually dies).
            await this.closeBrowser(slot)
            throw err
        }
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
        } else if (this.idle.length >= config.maxIdleBrowsers) {
            // Beyond the warm-pool cap, an idle Chromium is pure RSS: close it instead of keeping
            // the pod's memory footprint at its all-time concurrency high-water mark.
            log.info({ idle: this.idle.length }, 'idle pool full, closing browser')
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
        this.shuttingDown = true
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
