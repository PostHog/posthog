import { PostgresRouter, PostgresUse } from '~/common/utils/db/postgres'
import { DEFAULT_LOADER_RETRY, LazyLoader } from '~/common/utils/lazy-loader'
import { PubSub } from '~/common/utils/pubsub'

type SandboxSenderState = { sendingStatus: string | undefined; generation: number }

function isDisabled(state: SandboxSenderState | undefined): boolean {
    // No row means never synced; SES stays the final word.
    return state?.sendingStatus === 'DISABLED'
}

export class SandboxSenderStateService {
    private lazyLoader: LazyLoader<SandboxSenderState>
    private generation = 0

    constructor(
        private postgres: PostgresRouter,
        pubSub: PubSub
    ) {
        this.lazyLoader = new LazyLoader({
            name: 'sandbox_sender_state',
            refreshAgeMs: 30_000,
            refreshJitterMs: 5_000,
            loader: async (tenantNames) => await this.fetchStates(tenantNames),
            loaderRetry: DEFAULT_LOADER_RETRY,
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
            return isDisabled((await this.fetchStates([tenantName]))[tenantName])
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

    private async fetchStates(tenantNames: string[]): Promise<Record<string, SandboxSenderState>> {
        const generation = this.generation
        const { rows } = await this.postgres.query<{ tenant_name: string; sending_status: string }>(
            // The reload message fires right after the commit, so a lagging replica would cache the old state again.
            PostgresUse.COMMON_WRITE,
            'SELECT tenant_name, sending_status FROM workflows_sandboxsendertenantstate WHERE tenant_name = ANY($1)',
            [tenantNames],
            'fetch-sandbox-sender-state'
        )
        const statuses = new Map(rows.map((row) => [row.tenant_name, row.sending_status]))
        return Object.fromEntries(tenantNames.map((name) => [name, { sendingStatus: statuses.get(name), generation }]))
    }
}
