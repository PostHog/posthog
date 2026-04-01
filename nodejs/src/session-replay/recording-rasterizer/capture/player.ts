import type { Page } from 'puppeteer'

import { PLAYER_CONFIG_KEY, PLAYER_EMIT_FN, PLAYER_START_EVENT } from '@posthog/replay-headless/protocol'
import type { InactivityPeriod, PlayerConfig, PlayerMessage } from '@posthog/replay-headless/protocol'

import { RasterizationError } from '../errors'
import { type Logger, createLogger } from '../logger'
import { BlockProxy } from './block-proxy'
import { CapturePage } from './capture-page'
import { RequestInterceptor } from './request-interceptor'

/**
 * Controls communication with the in-browser replay player.
 *
 * The player sends messages via {@link PLAYER_EMIT_FN} and receives
 * commands via custom DOM events. This class accumulates player state
 * so the capture loop can poll it without touching browser globals.
 */
export class PlayerController {
    private interceptor: RequestInterceptor

    private state = {
        ended: false,
        inactivityPeriods: [] as InactivityPeriod[],
    }

    private startedResolve: (() => void) | null = null
    private errorReject: ((err: RasterizationError) => void) | null = null
    private playbackError: RasterizationError | null = null
    private resetStaleTimer: (() => void) | null = null

    constructor(
        private capturePage: CapturePage,
        blockProxy: BlockProxy,
        private log: Logger = createLogger()
    ) {
        this.interceptor = new RequestInterceptor(capturePage, blockProxy, log)
    }

    get page(): Page {
        return this.capturePage.page
    }

    private toError(err: { code: string; message: string; retryable: boolean }): RasterizationError {
        return new RasterizationError(`[${err.code}] ${err.message}`, err.retryable, err.code)
    }

    private rejectWithError(err: { code: string; message: string; retryable: boolean }): void {
        const rasterErr = this.toError(err)
        if (this.errorReject) {
            this.errorReject(rasterErr)
            this.errorReject = null
        } else {
            // No active promise to reject — store for polling during capture.
            this.playbackError = rasterErr
        }
    }

    private handleMessage(msg: PlayerMessage): void {
        switch (msg.type) {
            case 'loading_progress':
                this.resetStaleTimer?.()
                this.log.info({ loaded: msg.loaded, total: msg.total }, 'loading blocks')
                break
            case 'started':
                this.startedResolve?.()
                this.startedResolve = null
                break
            case 'ended':
                this.state.ended = true
                break
            case 'error':
                this.rejectWithError(msg)
                break
            case 'inactivity_periods':
                this.state.inactivityPeriods = msg.periods
                break
        }
    }

    /**
     * Wait for `promise` to resolve, but reject if `ms` elapses or the
     * player sends an error. When `resetOnProgress` is true the timer
     * resets on each loading_progress message — so we only time out when
     * progress stalls, not when loading takes a long time overall.
     */
    private awaitWithTimeout(
        promise: Promise<void>,
        ms: number,
        timeoutMsg: string,
        resetOnProgress = false
    ): Promise<void> {
        return new Promise<void>((resolve, reject) => {
            const onTimeout = (): void => {
                this.startedResolve = null
                this.errorReject = null
                this.resetStaleTimer = null
                reject(new RasterizationError(timeoutMsg, true, 'TIMEOUT'))
            }

            const cleanup = (): void => {
                clearTimeout(timer)
                this.startedResolve = null
                this.errorReject = null
                this.resetStaleTimer = null
            }

            let timer = setTimeout(onTimeout, ms)
            this.errorReject = (err) => {
                cleanup()
                reject(err)
            }

            if (resetOnProgress) {
                this.resetStaleTimer = () => {
                    clearTimeout(timer)
                    timer = setTimeout(onTimeout, ms)
                }
            }

            void promise
                .then(() => {
                    cleanup()
                    resolve()
                })
                .catch((err) => {
                    // Outer promise already settled (timeout or error). Log for debugging.
                    this.log.debug({ error: (err as Error)?.message }, 'secondary rejection after settlement')
                })
        })
    }

    /** Resolves when all tracked stylesheet requests have a response. */
    waitForSettled(): Promise<void> {
        return this.interceptor.waitForSettled()
    }

    /**
     * Install CDP guards that override screenshot format and gate
     * beginFrame on pending stylesheet requests. Must be called
     * after the player is loaded and before captureVideo().
     */
    prepareBrowserForCapture(screenshotFormat: 'jpeg' | 'png', screenshotQuality: number | undefined): void {
        this.capturePage.installCDPGuards(screenshotFormat, screenshotQuality, () => this.waitForSettled())
    }

    /** Install request interception, set up the message bridge, and navigate. */
    async load(playerConfig: PlayerConfig): Promise<void> {
        const page = this.capturePage.page
        await this.interceptor.install()

        await page.exposeFunction(PLAYER_EMIT_FN, (msg: PlayerMessage) => {
            this.handleMessage(msg)
        })

        // Inject config as a window global before the page loads — the
        // browser-side HostBridge reads it synchronously on startup.
        await page.evaluateOnNewDocument(
            (key, config) => {
                ;(window as any)[key] = config
            },
            PLAYER_CONFIG_KEY,
            playerConfig
        )

        await page.goto(this.capturePage.playerUrl, { waitUntil: 'load', timeout: 30000 })
        this.log.info({ origin: this.capturePage.playerUrl }, 'player loaded')
    }

    /**
     * Wait for the player to finish loading and signal started.
     * Times out if no loading_progress arrives within `staleMs`.
     */
    async waitForStart(playerConfig: PlayerConfig, staleMs = 30000): Promise<void> {
        const startedPromise = new Promise<void>((resolve) => {
            this.startedResolve = resolve
        })
        await this.awaitWithTimeout(
            startedPromise,
            staleMs,
            `Recording did not start for session ${playerConfig.sessionId} (no progress for ${staleMs / 1000}s)`,
            true
        )

        this.log.info('loading complete')
    }

    async startPlayback(): Promise<void> {
        const startEvent = PLAYER_START_EVENT
        await this.capturePage.page.evaluate((evt) => {
            window.dispatchEvent(new Event(evt))
        }, startEvent)
    }

    isEnded(): boolean {
        return this.state.ended
    }

    getError(): RasterizationError | null {
        return this.playbackError
    }

    getInactivityPeriods(): InactivityPeriod[] {
        return this.state.inactivityPeriods
    }

    dispose(): void {
        this.startedResolve = null
        this.errorReject = null
        this.playbackError = null
        this.resetStaleTimer = null
    }
}
