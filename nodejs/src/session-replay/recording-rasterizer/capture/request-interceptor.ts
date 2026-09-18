import { randomBytes } from 'node:crypto'
import { Frame, HTTPRequest } from 'puppeteer'

import { fetch } from '~/common/utils/request'
import { config } from '~/session-replay/recording-rasterizer/config'
import { type Logger, createLogger } from '~/session-replay/recording-rasterizer/logger'

import { BLOCK_REQUEST_PREFIX, BlockProxy } from './block-proxy'
import { CapturePage } from './capture-page'

const PROXY_TIMEOUT_MS = 10_000

// The replay-headless build stamps this placeholder as the player script's nonce attribute
// (see common/replay-headless/build.mjs). It is swapped for a per-request nonce when the CSP is on
// and stripped when it is off. Keep in sync with the build.
const NONCE_PLACEHOLDER = '__CSP_NONCE__'

/**
 * Centralizes all Puppeteer request interception: serves the player HTML,
 * forwards block requests to {@link BlockProxy}, proxies sub-frame
 * stylesheets, and aborts sub-frame media to prevent beginFrame deadlocks.
 *
 * {@link waitForSettled} gates beginFrame until proxied stylesheets resolve.
 * {@link stylesheetFailures} counts the page stylesheets that never arrived, because a render that
 * lost them paints an unstyled page that downstream consumers must not read as the real product.
 */
export class RequestInterceptor {
    private tracked = new Set<HTTPRequest>()
    private onSettled: (() => void) | null = null
    private mainFrame: Frame
    private failedStylesheets = 0

    constructor(
        private capturePage: CapturePage,
        private blockProxy: BlockProxy,
        private log: Logger = createLogger(),
        private enablePlayerCsp: boolean = config.enablePlayerCsp
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

    /** Page stylesheets that resolved to an empty body, so the replay painted without them. */
    get stylesheetFailures(): number {
        return this.failedStylesheets
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
            this.servePlayer(request)
            return
        }

        let parsed: URL
        try {
            parsed = new URL(url)
        } catch {
            void request.continue()
            return
        }
        if (parsed.pathname.startsWith(BLOCK_REQUEST_PREFIX)) {
            void this.blockProxy.handleRequest(request, parsed.pathname)
            return
        }

        if (request.frame() !== this.mainFrame) {
            const type = request.resourceType()
            if (type === 'stylesheet') {
                // Only http(s) stylesheets belong to the recorded page. A chrome-extension URL comes
                // from an extension the visitor had installed, is unreachable from the pod, and would
                // otherwise fail on every render and make the failure count meaningless.
                if (parsed.protocol !== 'http:' && parsed.protocol !== 'https:') {
                    void request.abort()
                    return
                }
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

    /**
     * Serve the player document. When {@link enablePlayerCsp} is set, it goes out under a
     * Content-Security-Policy that confines script execution to our own bundle via a per-response
     * nonce. Recordings are untrusted, so this stops a malicious snapshot from running an inline
     * event handler (e.g. a copied `onerror`) in the player origin — defense in depth behind
     * sanitizing the DOM itself.
     *
     * Only script execution is locked down. Resource directives (img/style/font/media/
     * connect/frame) are intentionally left unset so recorded pages keep loading assets from
     * arbitrary third-party hosts, which is the whole point of the replay. `worker-src blob:`
     * keeps hls.js's transmux worker alive; the replay iframe is scriptless (`allow-same-origin`
     * sandbox with no `allow-scripts`), so inheriting this policy costs it nothing.
     *
     * The CSP is opt-in (ENABLE_PLAYER_CSP) so it can be verified in dev before production; when
     * off, the placeholder is stripped and the player is served as it was before this feature.
     */
    private servePlayer(request: HTTPRequest): void {
        const playerHtml = this.capturePage.playerHtml

        if (!this.enablePlayerCsp) {
            void request.respond({
                status: 200,
                contentType: 'text/html',
                body: playerHtml.replace(` nonce="${NONCE_PLACEHOLDER}"`, ''),
            })
            return
        }

        const nonce = randomBytes(16).toString('base64')
        // Replace the single build-stamped placeholder (function replacer avoids $-pattern parsing).
        const body = playerHtml.replace(NONCE_PLACEHOLDER, () => nonce)

        // The build stamps exactly one placeholder. If it is gone (build changed) or a second one
        // slipped through, our bundle would load without a valid nonce and the CSP would blank the
        // page. Fail loudly instead of silently serving a broken player.
        if (!body.includes(nonce) || body.includes(NONCE_PLACEHOLDER)) {
            this.log.error(
                { playerUrl: this.capturePage.playerUrl },
                'player HTML nonce placeholder missing or duplicated; refusing to serve without a working CSP nonce'
            )
            void request.respond({ status: 500, contentType: 'text/plain', body: 'player nonce injection failed' })
            return
        }

        void request.respond({
            status: 200,
            contentType: 'text/html',
            headers: {
                'Content-Security-Policy': `script-src 'nonce-${nonce}'; worker-src blob:; object-src 'none'`,
            },
            body,
        })
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
            // Forward an allowlist rather than the browser's full header set: the URL is
            // attacker-controlled (a <link href> in a recorded sub-frame), and the browser's
            // Referer would disclose the internal player URL to arbitrary third-party hosts.
            const browserHeaders = request.headers()
            const headers: Record<string, string> = {}
            for (const name of ['accept', 'accept-language', 'user-agent']) {
                if (browserHeaders[name]) {
                    headers[name] = browserHeaders[name]
                }
            }
            const resp = await fetch(url, { headers, timeoutMs: PROXY_TIMEOUT_MS })
            if (resp.status >= 400) {
                // An error response body is an HTML page or a JSON blob, never CSS, so forwarding it
                // verbatim leaves the browser with nothing to apply anyway.
                this.log.warn({ url, status: resp.status }, 'stylesheet proxy got an error status, responding empty')
                await this.respondEmpty(request)
                return
            }
            await request.respond({
                status: resp.status,
                contentType: resp.headers['content-type'] || 'text/css',
                body: await resp.text(),
            })
        } catch (err) {
            this.log.warn({ url, err: (err as Error)?.message }, 'stylesheet proxy failed, responding empty')
            await this.respondEmpty(request)
        }
    }

    private async respondEmpty(request: HTTPRequest): Promise<void> {
        this.failedStylesheets++
        try {
            await request.respond({ status: 200, contentType: 'text/css', body: '' })
        } catch {
            this.removeTracked(request)
        }
    }
}
