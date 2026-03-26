import { HTTPRequest, Page } from 'puppeteer'

import {
    BLOCK_REQUEST_PREFIX,
    PLAYER_CONFIG_KEY,
    PLAYER_EMIT_FN,
    PLAYER_START_EVENT,
} from '@posthog/replay-headless/protocol'
import type { InactivityPeriod, PlayerConfig, PlayerMessage } from '@posthog/replay-headless/protocol'

import { internalFetch } from '../../../utils/request'
import { type RecordingBlock as FullRecordingBlock } from '../../recording-api/types'
import { config as defaultConfig } from '../config'
import { RasterizationError } from '../errors'
import { type Logger, createLogger } from '../logger'
import { RasterizeRecordingInput } from '../types'

type RecordingBlock = Pick<FullRecordingBlock, 'key' | 'start_byte' | 'end_byte'>

export async function fetchBlockList(
    input: RasterizeRecordingInput,
    cfg: typeof defaultConfig
): Promise<RecordingBlock[]> {
    const url = `${cfg.recordingApiBaseUrl}/api/projects/${input.team_id}/recordings/${input.session_id}/blocks`
    const resp = await internalFetch(url, {
        headers: { 'X-Internal-Api-Secret': cfg.recordingApiSecret },
    })
    if (resp.status < 200 || resp.status >= 300) {
        const body = await resp.text()
        throw new RasterizationError(
            `Failed to fetch block listing: ${resp.status} - ${body}`,
            resp.status >= 500,
            'BLOCK_LISTING_FAILED'
        )
    }
    const data = await resp.json()
    if (!Array.isArray(data.blocks)) {
        throw new RasterizationError(
            `Invalid block listing response: expected blocks array, got ${typeof data.blocks}`,
            false,
            'BLOCK_LISTING_FAILED'
        )
    }
    return data.blocks as RecordingBlock[]
}

export function buildPlayerConfig(
    input: RasterizeRecordingInput,
    playbackSpeed: number,
    blockCount: number
): PlayerConfig {
    return {
        teamId: input.team_id,
        sessionId: input.session_id,
        playbackSpeed,
        blockCount,
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

    private startedResolve: (() => void) | null = null
    private errorReject: ((err: RasterizationError) => void) | null = null
    private playbackError: RasterizationError | null = null
    private resetStaleTimer: (() => void) | null = null
    private blockList: RecordingBlock[] | null = null

    private readonly playerUrl: string
    private readonly apiBase: string

    constructor(
        private page: Page,
        private html: string,
        private cfg: { siteUrl: string; recordingApiBaseUrl: string; recordingApiSecret: string },
        private log: Logger = createLogger()
    ) {
        this.playerUrl = `${cfg.siteUrl}/player`
        this.apiBase = `${cfg.recordingApiBaseUrl}/api/projects`
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

    async load(playerConfig: PlayerConfig, blocks: RecordingBlock[]): Promise<void> {
        this.blockList = blocks

        await this.page.exposeFunction(PLAYER_EMIT_FN, (msg: PlayerMessage) => {
            this.handleMessage(msg)
        })

        // Inject config as a window global before the page loads — the
        // browser-side HostBridge reads it synchronously on startup.
        await this.page.evaluateOnNewDocument(
            (key, config) => {
                ;(window as any)[key] = config
            },
            PLAYER_CONFIG_KEY,
            playerConfig
        )

        await this.page.setRequestInterception(true)
        this.page.on('request', (request) => {
            const url = request.url()
            const path = new URL(url).pathname
            if (url === this.playerUrl) {
                void request.respond({
                    status: 200,
                    contentType: 'text/html',
                    body: this.html,
                })
            } else if (path.startsWith(BLOCK_REQUEST_PREFIX)) {
                void this.handleBlockRequest(request, path, playerConfig)
            } else {
                void request.continue()
            }
        })

        await this.page.goto(this.playerUrl, { waitUntil: 'load', timeout: 30000 })
        this.log.info({ origin: this.playerUrl }, 'player loaded')
    }

    /**
     * Handle /__blocks/:index requests from the in-browser data-loader.
     * Proxies to the real recording-api with auth headers and implementation
     * details (S3 key, byte range, decompress) the player doesn't know about.
     */
    private async handleBlockRequest(request: HTTPRequest, path: string, playerConfig: PlayerConfig): Promise<void> {
        try {
            const index = parseInt(path.slice(BLOCK_REQUEST_PREFIX.length), 10)
            if (!this.blockList || isNaN(index) || index < 0 || index >= this.blockList.length) {
                this.log.warn({ path, index, blockCount: this.blockList?.length ?? 0 }, 'block not found')
                await request.respond({ status: 404, body: 'block not found' })
                return
            }
            const block = this.blockList[index]
            const params = new URLSearchParams({
                key: block.key,
                start_byte: String(block.start_byte),
                end_byte: String(block.end_byte),
                decompress: 'true',
            })
            const url = `${this.apiBase}/${playerConfig.teamId}/recordings/${playerConfig.sessionId}/block?${params}`
            const resp = await internalFetch(url, {
                headers: { 'X-Internal-Api-Secret': this.cfg.recordingApiSecret },
            })
            if (resp.status < 200 || resp.status >= 300) {
                const text = await resp.text()
                this.log.warn({ index, status: resp.status, body: text }, 'upstream block fetch failed')
                await request.respond({ status: resp.status, body: text })
                return
            }
            const contentType = resp.headers['content-type'] || 'application/octet-stream'
            const body = Buffer.from(await resp.text(), 'utf-8')
            await request.respond({
                status: resp.status,
                contentType,
                body,
            })
        } catch (err) {
            this.log.error({ path, err }, 'block proxy failed')
            try {
                await request.respond({ status: 502, body: 'block proxy error' })
            } catch (respondErr) {
                this.log.debug({ path, respondErr }, 'could not send 502 response, page likely closed')
            }
        }
    }

    /**
     * Wait for the player to finish loading recording data and signal started.
     *
     * The player reads its config synchronously from a window global
     * (injected by {@link load} via evaluateOnNewDocument), so there's
     * no config handshake — we just wait for the 'started' message.
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

    dispose(): void {
        this.startedResolve = null
        this.errorReject = null
        this.playbackError = null
        this.resetStaleTimer = null
        this.blockList = null
    }
}
