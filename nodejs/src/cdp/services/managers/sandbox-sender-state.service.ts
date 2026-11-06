import { PostgresRouter } from '~/common/utils/db/postgres'
import { DEFAULT_LOADER_RETRY } from '~/common/utils/lazy-loader'
import { logger } from '~/common/utils/logger'
import { PubSub } from '~/common/utils/pubsub'
import { sleep } from '~/common/utils/utils'

import { BoundedPrimaryLookup } from '../../utils/bounded-primary-lookup'

const LOOKUP_TIMEOUT_MS = 3_000
const MAX_OPEN_LOOKUPS = 5
const REFRESH_AGE_MS = 30_000
const REFRESH_JITTER_MS = 5_000

type CachedRead = { paused: Promise<boolean>; expiresAt: number; number: number }

export class SandboxSenderStateService {
    private lookup: BoundedPrimaryLookup
    private cached: CachedRead | undefined
    private lastGood: CachedRead | undefined
    private reloads = 0
    private readsStarted = 0

    constructor(
        private postgres: PostgresRouter,
        private tenantName: string,
        pubSub: PubSub
    ) {
        this.lookup = new BoundedPrimaryLookup(postgres, {
            name: 'sandbox sender state',
            timeoutMs: LOOKUP_TIMEOUT_MS,
            maxOpen: MAX_OPEN_LOOKUPS,
        })
        pubSub.on<{ tenantName: string }>('reload-sandbox-sender-state', ({ tenantName }): void => {
            if (tenantName === this.tenantName) {
                this.reloads++
                this.cached = undefined
                this.lastGood = undefined
            }
        })
    }

    public async isPaused({ fresh = false }: { fresh?: boolean } = {}): Promise<boolean> {
        const giveUpAt = performance.now() + DEFAULT_LOADER_RETRY.maxElapsedMs
        for (;;) {
            const reloads = this.reloads
            const paused = await this.currentRead(fresh, giveUpAt)
            if (reloads === this.reloads) {
                return paused
            }
            fresh = true
        }
    }

    private currentRead(fresh: boolean, giveUpAt: number): Promise<boolean> {
        if (!fresh && this.cached && Date.now() < this.cached.expiresAt) {
            return this.cached.paused
        }
        const reloads = this.reloads
        const read: CachedRead = {
            paused: this.readWithRetry(giveUpAt),
            expiresAt: Date.now() + REFRESH_AGE_MS + Math.random() * REFRESH_JITTER_MS,
            number: ++this.readsStarted,
        }
        this.cached = read
        read.paused.then(
            () => {
                // Overlapping reads can finish out of order.
                if (reloads === this.reloads && read.number > (this.lastGood?.number ?? 0)) {
                    this.lastGood = read
                    if (!this.cached || this.cached.number < read.number) {
                        this.cached = read
                    }
                }
            },
            () => {
                if (this.cached === read) {
                    const lastGood = this.lastGood
                    this.cached = lastGood && Date.now() < lastGood.expiresAt ? lastGood : undefined
                }
            }
        )
        return read.paused
    }

    private async readWithRetry(giveUpAt: number): Promise<boolean> {
        const { retryIntervalMs, retryJitterMs = 0 } = DEFAULT_LOADER_RETRY
        for (let attempt = 1; ; attempt++) {
            if (giveUpAt - performance.now() < retryIntervalMs) {
                throw new Error('The sandbox sender state check ran out of time')
            }
            try {
                return await this.read(Math.min(LOOKUP_TIMEOUT_MS, Math.ceil(giveUpAt - performance.now())))
            } catch (error) {
                const delayMs = retryIntervalMs + Math.floor(Math.random() * retryJitterMs)
                if (error?.isRetriable !== true || performance.now() + delayMs + retryIntervalMs > giveUpAt) {
                    logger.warn('Sandbox sender state read failed', { attempt, error: String(error) })
                    throw error
                }
                logger.warn('Sandbox sender state read failed, retrying', { attempt, error: String(error) })
                await sleep(delayMs)
            }
        }
    }

    private async read(timeoutMs: number): Promise<boolean> {
        const tag = 'fetch-sandbox-sender-state'
        return await this.lookup.run(
            tag,
            async (tx) => {
                const result = await this.postgres.query<{ paused: boolean }>(
                    tx,
                    `SELECT sending_status = 'DISABLED' AS paused FROM workflows_sandboxsendertenantstate WHERE tenant_name = $1`,
                    [this.tenantName],
                    tag
                )
                return result.rows[0]?.paused === true
            },
            { timeoutMs }
        )
    }
}
