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

type CachedRead = { paused: Promise<boolean>; expiresAt: number }

export class SandboxSenderStateService {
    private lookup: BoundedPrimaryLookup
    private cached: CachedRead | undefined

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
                this.cached = undefined
            }
        })
    }

    // Every call after a reload message starts a new read. A caller already waiting gets the read it joined,
    // which ran at the same time as the change.
    public isPaused({ fresh = false }: { fresh?: boolean } = {}): Promise<boolean> {
        if (!fresh && this.cached && performance.now() < this.cached.expiresAt) {
            return this.cached.paused
        }
        const read: CachedRead = {
            paused: this.readWithRetry(),
            expiresAt: performance.now() + REFRESH_AGE_MS + Math.random() * REFRESH_JITTER_MS,
        }
        this.cached = read
        read.paused.catch(() => {
            if (this.cached === read) {
                this.cached = undefined
            }
        })
        return read.paused
    }

    private async readWithRetry(): Promise<boolean> {
        const { retryIntervalMs, retryJitterMs = 0, maxElapsedMs } = DEFAULT_LOADER_RETRY
        const giveUpAt = performance.now() + maxElapsedMs
        for (let attempt = 1; ; attempt++) {
            try {
                return await this.read(Math.min(LOOKUP_TIMEOUT_MS, Math.ceil(giveUpAt - performance.now())))
            } catch (error) {
                const delayMs = retryIntervalMs + Math.floor(Math.random() * retryJitterMs)
                // An attempt with less than one interval left would only time out while holding a connection.
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
