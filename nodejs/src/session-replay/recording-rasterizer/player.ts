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
        ready: false,
        started: false,
        ended: false,
        error: null as { code: string; message: string; retryable: boolean } | null,
        lastProgressAt: 0,
        inactivityPeriods: [] as InactivityPeriod[],
    }

    constructor(
        private page: Page,
        private log: Logger = createLogger()
    ) {}

    private throwIfError(): void {
        if (this.state.error) {
            throw new RasterizationError(
                `[${this.state.error.code}] ${this.state.error.message}`,
                this.state.error.retryable
            )
        }
    }

    private handleMessage(msg: PlayerMessage): void {
        switch (msg.type) {
            case 'ready':
                this.state.ready = true
                break
            case 'loading_progress':
                this.state.lastProgressAt = Date.now()
                this.log.info({ loaded: msg.loaded, total: msg.total }, 'loading blocks')
                break
            case 'started':
                this.state.started = true
                break
            case 'ended':
                this.state.ended = true
                break
            case 'error':
                this.state.error = { code: msg.code, message: msg.message, retryable: msg.retryable }
                break
            case 'inactivity_periods':
                this.state.inactivityPeriods = msg.periods
                break
        }
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
        // Wait for the player to signal it's ready for config.
        const readyStart = Date.now()
        while (!this.state.ready && !this.state.error) {
            if (Date.now() - readyStart > staleMs) {
                throw new RasterizationError(
                    `Player did not become ready for session ${playerConfig.sessionId} (waited ${staleMs / 1000}s)`,
                    true
                )
            }
            await new Promise((resolve) => setTimeout(resolve, 100))
        }

        this.throwIfError()

        // Send config to the player via CustomEvent.
        await this.page.evaluate(
            (evt, config) => {
                window.dispatchEvent(new CustomEvent(evt, { detail: config }))
            },
            PLAYER_INIT_EVENT,
            playerConfig
        )

        // Wait for the player to finish loading and signal started.
        // Time out if no progress arrives for staleMs (covers both
        // "never got any progress" and "progress stalled" cases).
        const configSentAt = Date.now()
        while (!this.state.started && !this.state.error) {
            const lastActivity = this.state.lastProgressAt || configSentAt
            if (Date.now() - lastActivity > staleMs) {
                break
            }
            await new Promise((resolve) => setTimeout(resolve, 500))
        }

        this.throwIfError()

        if (!this.state.started) {
            throw new RasterizationError(
                `Recording did not start for session ${playerConfig.sessionId} (no progress for ${staleMs / 1000}s)`,
                true
            )
        }

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
        if (!this.state.error) {
            return null
        }
        return new RasterizationError(
            `[${this.state.error.code}] ${this.state.error.message}`,
            this.state.error.retryable
        )
    }

    getInactivityPeriods(): InactivityPeriod[] {
        return this.state.inactivityPeriods
    }
}
