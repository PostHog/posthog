import { Frame, HTTPRequest, Page } from 'puppeteer'

import { fetch } from '../../../utils/request'
import { type Logger } from '../logger'

const PROXY_TIMEOUT_MS = 10_000

/**
 * Routes sub-frame asset requests to prevent beginFrame deadlocks.
 *
 * Stylesheets are proxied with a timeout (pending CSS blocks style-recalc).
 * Media is aborted (decoder init deadlocks the main thread).
 * Everything else is continued normally (uses placeholders during paint).
 *
 * {@link waitForSettled} gates beginFrame until all proxied stylesheets
 * have a response.
 */
export class AssetProxy {
    private tracked = new Set<HTTPRequest>()
    private onSettled: (() => void) | null = null
    private mainFrame: Frame

    constructor(
        page: Page,
        private log: Logger
    ) {
        this.mainFrame = page.mainFrame()
        page.on('requestfinished', (req) => this.remove(req))
        page.on('requestfailed', (req) => this.remove(req))
    }

    handleRequest(request: HTTPRequest): void {
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

    /** Resolves when all tracked stylesheet requests have a response. */
    waitForSettled(): Promise<void> {
        if (this.tracked.size === 0) {
            return Promise.resolve()
        }
        return new Promise<void>((resolve) => {
            this.onSettled = resolve
        })
    }

    private remove(req: HTTPRequest): void {
        if (this.tracked.delete(req) && this.tracked.size === 0 && this.onSettled) {
            this.onSettled()
            this.onSettled = null
        }
    }

    private async proxyStylesheet(request: HTTPRequest): Promise<void> {
        const url = request.url()
        try {
            const headers = request.headers()
            // Remove headers that are hop-by-hop or would conflict with our fetch
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
                this.remove(request)
            }
        }
    }
}
