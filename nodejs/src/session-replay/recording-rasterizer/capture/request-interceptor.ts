import { Frame, HTTPRequest } from 'puppeteer'

import { fetch, raiseIfUserProvidedUrlUnsafe } from '../../../utils/request'
import { type Logger, createLogger } from '../logger'
import { RasterizationMetrics } from '../metrics'
import { BLOCK_REQUEST_PREFIX, BlockProxy } from './block-proxy'
import { CapturePage } from './capture-page'

const PROXY_TIMEOUT_MS = 10_000

/**
 * Centralizes all Puppeteer request interception: serves the player HTML,
 * forwards block requests to {@link BlockProxy}, proxies sub-frame
 * stylesheets, and aborts sub-frame media to prevent beginFrame deadlocks.
 *
 * Customer-supplied recordings can drive headless Chrome to fetch
 * attacker-controlled URLs (image src, link href, etc.). Before letting
 * any such request reach the network, we validate the destination through
 * the same SSRF guard used by Node-side outbound fetches — blocking
 * private/link-local IPs in production.
 *
 * {@link waitForSettled} gates beginFrame until proxied stylesheets resolve.
 */
export class RequestInterceptor {
    private tracked = new Set<HTTPRequest>()
    private onSettled: (() => void) | null = null
    private mainFrame: Frame
    private playerOrigin: string

    constructor(
        private capturePage: CapturePage,
        private blockProxy: BlockProxy,
        private log: Logger = createLogger()
    ) {
        this.mainFrame = capturePage.page.mainFrame()
        this.playerOrigin = new URL(capturePage.playerUrl).origin
    }

    async install(): Promise<void> {
        const page = this.capturePage.page
        page.on('requestfinished', (req) => this.removeTracked(req))
        page.on('requestfailed', (req) => this.removeTracked(req))
        await page.setRequestInterception(true)
        page.on('request', (request) => void this.handleRequest(request))
    }

    /** Resolves when all tracked stylesheet requests have a response. */
    waitForSettled(): Promise<void> {
        if (this.tracked.size === 0) {
            return Promise.resolve()
        }
        return new Promise<void>((resolve) => {
            this.onSettled = resolve
        })
    }

    private async handleRequest(request: HTTPRequest): Promise<void> {
        const url = request.url()

        if (url === this.capturePage.playerUrl) {
            void request.respond({ status: 200, contentType: 'text/html', body: this.capturePage.playerHtml })
            return
        }

        let parsed: URL
        try {
            parsed = new URL(url)
        } catch {
            void request.continue()
            return
        }
        // Block-proxy responses carry recording bytes — only serve them on
        // the player's own origin. Customer-recorded DOM could otherwise
        // request `https://attacker.example/__blocks/N` and receive block
        // data scoped to that attacker origin in Chrome's view.
        if (parsed.origin === this.playerOrigin && parsed.pathname.startsWith(BLOCK_REQUEST_PREFIX)) {
            void this.blockProxy.handleRequest(request, parsed.pathname)
            return
        }

        if (request.frame() !== this.mainFrame) {
            const type = request.resourceType()
            if (type === 'stylesheet') {
                this.tracked.add(request)
                void this.proxyStylesheet(request)
                return
            }
            if (type === 'media') {
                void request.abort()
                return
            }
        }

        // Main-frame and sub-frame fallthrough requests go to Chrome's
        // network stack directly. Customer-controlled recordings can put
        // arbitrary URLs in the rebuilt DOM, so SSRF-guard http(s) targets
        // before letting them out. data:/blob: have no hostname; the guard
        // would reject them, so skip on protocol.
        if (parsed.protocol === 'http:' || parsed.protocol === 'https:') {
            try {
                await raiseIfUserProvidedUrlUnsafe(url)
            } catch (err) {
                this.log.warn({ url, err: (err as Error)?.message }, 'blocking unsafe egress')
                RasterizationMetrics.egressBlocked()
                try {
                    await request.abort('blockedbyclient')
                } catch {
                    // Page may have already navigated away; nothing to do.
                }
                return
            }
        }

        void request.continue()
    }

    private removeTracked(req: HTTPRequest): void {
        if (this.tracked.delete(req) && this.tracked.size === 0 && this.onSettled) {
            this.onSettled()
            this.onSettled = null
        }
    }

    private async proxyStylesheet(request: HTTPRequest): Promise<void> {
        const url = request.url()
        try {
            const headers = request.headers()
            delete headers['host']
            delete headers['connection']
            delete headers['content-length']
            const resp = await fetch(url, { headers, timeoutMs: PROXY_TIMEOUT_MS })
            const body = await resp.text()
            await request.respond({
                status: resp.status,
                contentType: resp.headers['content-type'] || 'text/css',
                body,
            })
        } catch (err) {
            this.log.warn({ url, err: (err as Error)?.message }, 'stylesheet proxy failed, responding empty')
            try {
                await request.respond({ status: 200, contentType: 'text/css', body: '' })
            } catch {
                this.removeTracked(request)
            }
        }
    }
}
