import { Frame, HTTPRequest } from 'puppeteer'

import { fetch } from '../../../utils/request'
import { type Logger, createLogger } from '../logger'
import { BLOCK_REQUEST_PREFIX, BlockProxy } from './block-proxy'
import { CapturePage } from './capture-page'

const PROXY_TIMEOUT_MS = 10_000

/**
 * Centralizes all Puppeteer request interception: serves the player HTML,
 * forwards block requests to {@link BlockProxy}, proxies sub-frame
 * stylesheets, and aborts sub-frame media to prevent beginFrame deadlocks.
 *
 * {@link waitForSettled} gates beginFrame until proxied stylesheets resolve.
 */
export class RequestInterceptor {
    private tracked = new Set<HTTPRequest>()
    private onSettled: (() => void) | null = null
    private mainFrame: Frame

    constructor(
        private capturePage: CapturePage,
        private blockProxy: BlockProxy,
        private log: Logger = createLogger()
    ) {
        this.mainFrame = capturePage.page.mainFrame()
    }

    async install(): Promise<void> {
        const page = this.capturePage.page
        page.on('requestfinished', (req) => this.removeTracked(req))
        page.on('requestfailed', (req) => this.removeTracked(req))
        await page.setRequestInterception(true)
        page.on('request', (request) => this.handleRequest(request))
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

    private handleRequest(request: HTTPRequest): void {
        const url = request.url()

        if (url === this.capturePage.playerUrl) {
            void request.respond({ status: 200, contentType: 'text/html', body: this.capturePage.playerHtml })
            return
        }

        let path: string
        try {
            path = new URL(url).pathname
        } catch {
            void request.continue()
            return
        }
        if (path.startsWith(BLOCK_REQUEST_PREFIX)) {
            void this.blockProxy.handleRequest(request, path)
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
