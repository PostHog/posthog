import { PostgresRouter } from '~/common/utils/db/postgres'
import { DEFAULT_LOADER_RETRY, LazyLoader } from '~/common/utils/lazy-loader'
import { PubSub } from '~/common/utils/pubsub'
import { sleep } from '~/common/utils/utils'

import { BoundedPrimaryLookup } from '../../utils/bounded-primary-lookup'

type SandboxSenderState = { sendingStatus: string | undefined; generation: number }

const LOOKUP_TIMEOUT_MS = 3_000
const MAX_OPEN_LOOKUPS = 5

function isDisabled(state: SandboxSenderState | undefined): boolean {
    // No row means never synced; SES stays the final word.
    return state?.sendingStatus === 'DISABLED'
}

export class SandboxSenderStateService {
    private lazyLoader: LazyLoader<SandboxSenderState>
    private lookup: BoundedPrimaryLookup
    private generation = 0

    constructor(
        private postgres: PostgresRouter,
        pubSub: PubSub
    ) {
        this.lookup = new BoundedPrimaryLookup(postgres, {
            name: 'sandbox sender state',
            timeoutMs: LOOKUP_TIMEOUT_MS,
            maxOpen: MAX_OPEN_LOOKUPS,
        })
        this.lazyLoader = new LazyLoader({
            name: 'sandbox_sender_state',
            refreshAgeMs: 30_000,
            refreshJitterMs: 5_000,
            loader: async (tenantNames) => await this.fetchStatesWithRetry(tenantNames),
        })
        pubSub.on<{ tenantName: string }>('reload-sandbox-sender-state', ({ tenantName }): void => {
            this.generation++
            this.lazyLoader.markForRefresh(tenantName)
        })
    }

    // `fresh` reads the row itself, for the check right before delivery: a worker that missed the
    // reload message would otherwise answer from a cached state until the next refresh.
    public async isPaused(tenantName: string, { fresh = false }: { fresh?: boolean } = {}): Promise<boolean> {
        if (fresh) {
            return isDisabled((await this.fetchStatesWithRetry([tenantName]))[tenantName])
        }
        for (let attempt = 0; attempt < 2; attempt++) {
            const state = await this.lazyLoader.get(tenantName)
            if (state?.generation === this.generation) {
                return isDisabled(state)
            }
            this.lazyLoader.markForRefresh(tenantName)
        }
        throw new Error('Sandbox sender state changed during lookup')
    }

    // Both the cached and the fresh check retry here, so a database blip right before delivery does not skip the send.
    private async fetchStatesWithRetry(tenantNames: string[]): Promise<Record<string, SandboxSenderState>> {
        const { retryIntervalMs, retryJitterMs = 0, maxElapsedMs } = DEFAULT_LOADER_RETRY
        const giveUpAt = performance.now() + maxElapsedMs
        for (;;) {
            try {
                return await this.fetchStates(tenantNames)
            } catch (error) {
                if (error?.isRetriable !== true || performance.now() >= giveUpAt) {
                    throw error
                }
                await sleep(retryIntervalMs + Math.floor(Math.random() * retryJitterMs))
            }
        }
    }

    private async fetchStates(tenantNames: string[]): Promise<Record<string, SandboxSenderState>> {
        const generation = this.generation
        const tag = 'fetch-sandbox-sender-state'
        // The reload message fires right after the commit, so a lagging replica would cache the old state again.
        const rows = await this.lookup.run(tag, async (tx) => {
            const result = await this.postgres.query<{ tenant_name: string; sending_status: string }>(
                tx,
                'SELECT tenant_name, sending_status FROM workflows_sandboxsendertenantstate WHERE tenant_name = ANY($1)',
                [tenantNames],
                tag
            )
            return result.rows
        })
        const statuses = new Map(rows.map((row) => [row.tenant_name, row.sending_status]))
        return Object.fromEntries(tenantNames.map((name) => [name, { sendingStatus: statuses.get(name), generation }]))
    }
}
