import { Page } from 'puppeteer'

import { PLAYER_EMIT_FN, PLAYER_INIT_EVENT, PLAYER_START_EVENT } from '@posthog/replay-headless/protocol'
import type { InactivityPeriod, PlayerConfig, PlayerMessage } from '@posthog/replay-headless/protocol'

import { config as defaultConfig } from './config'
import { RasterizationError } from './errors'
import { type Logger, createLogger } from './logger'
import { RasterizeRecordingInput } from './types'

export function buildPlayerConfig(
    input: RasterizeRecordingInput,
    playbackSpeed: number,
    cfg: typeof defaultConfig
): PlayerConfig {
    return {
        recordingApiBaseUrl: cfg.recordingApiBaseUrl,
        recordingApiSecret: cfg.recordingApiSecret,
        teamId: input.team_id,
        sessionId: input.session_id,
        playbackSpeed,
        skipInactivity: input.skip_inactivity !== false,
        mouseTail: input.mouse_tail !== false,
        showMetadataFooter: input.show_metadata_footer,
        startTimestamp: input.start_timestamp,
        endTimestamp: input.end_timestamp,
        viewportEvents: input.viewport_events || [],
    }
}

/**
 * Controls communication with the in-browser replay player.
 *
 * The player sends messages via an exposed function callback
 * ({@link PLAYER_EMIT_FN}), and receives commands via custom DOM events.
 * This class accumulates player state from incoming messages so the rest
 * of the codebase doesn't need to poll browser globals.
 *
 * The protocol types are defined in @posthog/replay-headless/protocol,
 * shared with the player-side HostBridge.
 */
export class PlayerController {
    private state = {
        ended: false,
        inactivityPeriods: [] as InactivityPeriod[],
    }

    // Resolved by handleMessage when the corresponding state transition occurs.
    // readyPromise is created eagerly so 'ready' messages arriving between
    // load() and waitForStart() are not lost.
    private readyResolve: (() => void) | null = null
    private readyPromise: Promise<void>
    private startedResolve: (() => void) | null = null
    private errorReject: ((err: RasterizationError) => void) | null = null
    private playbackError: RasterizationError | null = null
    private resetStaleTimer: (() => void) | null = null

    constructor(
        private page: Page,
        private log: Logger = createLogger()
    ) {
        this.readyPromise = new Promise<void>((resolve) => {
            this.readyResolve = resolve
        })
    }

    private toError(err: { code: string; message: string; retryable: boolean }): RasterizationError {
        return new RasterizationError(`[${err.code}] ${err.message}`, err.retryable)
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
            case 'ready':
                this.readyResolve?.()
                this.readyResolve = null
                break
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
                this.errorReject = null
                this.resetStaleTimer = null
                reject(new RasterizationError(timeoutMsg, true))
            }

            const cleanup = (): void => {
                clearTimeout(timer)
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

            void promise.then(() => {
                cleanup()
                resolve()
            })
        })
    }

    async load(html: string, siteUrl: string): Promise<void> {
        const playerUrl = `${siteUrl}/player`

        await this.page.exposeFunction(PLAYER_EMIT_FN, (msg: PlayerMessage) => {
            this.handleMessage(msg)
        })

        await this.page.setRequestInterception(true)
        this.page.on('request', (request) => {
            const url = request.url()
            if (url === playerUrl) {
                void request.respond({
                    status: 200,
                    contentType: 'text/html',
                    body: html,
                })
            } else {
                void request.continue()
            }
        })

        await this.page.goto(playerUrl, { waitUntil: 'load', timeout: 30000 })
        this.log.info({ origin: playerUrl }, 'player loaded')
    }

    /**
     * Wait for the player to load and signal readiness, send it the config,
     * then wait for it to finish loading recording data and signal started.
     *
     * Flow: player sends 'ready' → rasterizer dispatches config via
     * CustomEvent → player loads data (sending progress messages) →
     * player sends 'started'.
     */
    async waitForStart(playerConfig: PlayerConfig, staleMs = 30000): Promise<void> {
        await this.awaitWithTimeout(
            this.readyPromise,
            staleMs,
            `Player did not become ready for session ${playerConfig.sessionId} (waited ${staleMs / 1000}s)`
        )

        await this.page.evaluate(
            (evt, config) => {
                window.dispatchEvent(new CustomEvent(evt, { detail: config }))
            },
            PLAYER_INIT_EVENT,
            playerConfig
        )

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
        await this.page.evaluate((evt) => {
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
}
