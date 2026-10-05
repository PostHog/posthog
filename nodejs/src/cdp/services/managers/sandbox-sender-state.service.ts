import { PostgresRouter, PostgresUse } from '~/common/utils/db/postgres'
import { LazyLoader } from '~/common/utils/lazy-loader'
import { PubSub } from '~/common/utils/pubsub'

type SandboxSenderState = { sendingStatus: string }

export class SandboxSenderStateService {
    private lazyLoader: LazyLoader<SandboxSenderState>

    constructor(
        private postgres: PostgresRouter,
        pubSub: PubSub
    ) {
        this.lazyLoader = new LazyLoader({
            name: 'sandbox_sender_state',
            refreshAgeMs: 30_000,
            refreshJitterMs: 5_000,
            loader: async (tenantNames) => await this.fetchStates(tenantNames),
        })
        pubSub.on<{ tenantName: string }>('reload-sandbox-sender-state', ({ tenantName }): void => {
            this.lazyLoader.markForRefresh(tenantName)
        })
    }

    public async isPaused(tenantName: string): Promise<boolean> {
        // No row means never synced; SES stays the final word.
        return (await this.lazyLoader.get(tenantName))?.sendingStatus === 'DISABLED'
    }

    private async fetchStates(tenantNames: string[]): Promise<Record<string, SandboxSenderState>> {
        const { rows } = await this.postgres.query<{ tenant_name: string; sending_status: string }>(
            // The reload message fires right after the commit, so a lagging replica would cache the old state again.
            PostgresUse.COMMON_WRITE,
            'SELECT tenant_name, sending_status FROM workflows_sandboxsendertenantstate WHERE tenant_name = ANY($1)',
            [tenantNames],
            'fetch-sandbox-sender-state'
        )
        return Object.fromEntries(rows.map((row) => [row.tenant_name, { sendingStatus: row.sending_status }]))
    }
}
