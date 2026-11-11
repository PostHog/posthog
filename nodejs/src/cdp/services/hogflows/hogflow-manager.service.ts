import { Counter } from 'prom-client'

import { HogFlow } from '~/cdp/schema/hogflow'
import { PostgresRouter, PostgresUse } from '~/common/utils/db/postgres'
import { parseJSON } from '~/common/utils/json-parse'
import { DEFAULT_LOADER_RETRY, LazyLoader } from '~/common/utils/lazy-loader'
import { logger } from '~/common/utils/logger'
import { captureException } from '~/common/utils/posthog'
import { PubSub } from '~/common/utils/pubsub'
import { validTeamIds } from '~/common/utils/team-manager'
import { Team } from '~/types'

import { EncryptedFields } from '../../utils/encryption-utils'

// Nonzero means a flow's encrypted secret inputs couldn't be decrypted (most likely Fernet key skew
// between Django and the workers, or a corrupt blob). The flow still runs, but its secret-input steps
// run without their credentials, so this is worth alerting on.
const counterEncryptedInputsDecryptFailed = new Counter({
    name: 'cdp_hogflow_encrypted_inputs_decrypt_failed',
    help: 'A hog flow encrypted_inputs blob could not be decrypted; the flow runs without its secrets',
})

// TODO: Make sure we only have fields we truly need
const HOG_FLOW_FIELDS = [
    'id',
    'team_id',
    'name',
    'description',
    'version',
    'status',
    'created_at',
    'updated_at',
    'trigger',
    'trigger_masking',
    'conversion',
    'exit_condition',
    'email_sending_rate_limit',
    'email_sending_paused_at',
    'email_sending_paused_reason',
    'email_sending_paused_by',
    'edges',
    'actions',
    'encrypted_inputs',
    'abort_action',
    'billable_action_types',
    'variables',
    'action_redirects',
]

export type HogFlowTeamInfo = Pick<HogFlow, 'id' | 'team_id' | 'version'>

const PRIMARY_RESULT_TTL_MS = 60 * 1000
const PRIMARY_RESULT_MAX_SIZE = 10_000

export class HogFlowManagerService {
    private lazyLoader: LazyLoader<HogFlow>
    private lazyLoaderByTeam: LazyLoader<HogFlowTeamInfo[]>
    private primaryReads = new Map<HogFlow['id'], Promise<HogFlow | null>>()
    private primaryResults = new Map<HogFlow['id'], { flow: HogFlow | null; until: number }>()

    constructor(
        private postgres: PostgresRouter,
        private pubSub: PubSub,
        private encryptedFields: EncryptedFields
    ) {
        // The reload-hog-flows pub/sub below is the primary invalidation; these ages bound how
        // stale a worker can run when it misses the publish (pod restart, Redis blip). Live edits
        // are expected to reach in-flight runs, so a hot flow self-heals within ~30s via a
        // non-blocking background refresh, with a 2 minute hard cap - without these, a missed
        // publish serves stale config for the 5 minute default and the expiry refetch blocks the
        // worker's hot path.
        const cacheOptions = {
            refreshAgeMs: 2 * 60 * 1000,
            refreshBackgroundAgeMs: 30 * 1000,
            // Absorb transient Postgres blips inside a single load attempt so failed background
            // refreshes don't re-fire at caller QPS and hard-cap refreshes don't fail the batch.
            loaderRetry: DEFAULT_LOADER_RETRY,
        }

        this.lazyLoaderByTeam = new LazyLoader({
            name: 'hog_flow_manager_by_team',
            ...cacheOptions,
            loader: async (teamIds) => await this.fetchTeamHogFlows(teamIds),
        })

        this.lazyLoader = new LazyLoader({
            name: 'hog_flow_manager',
            ...cacheOptions,
            loader: async (ids) => await this.fetchHogFlows(ids),
        })

        this.pubSub.on<{ teamId: Team['id']; hogFlowIds: HogFlow['id'][] }>('reload-hog-flows', (message) => {
            const { teamId, hogFlowIds } = message
            logger.debug('⚡', '[PubSub] Reloading hog flows!', { teamId, hogFlowIds })
            this.onHogFlowsReloaded(teamId, hogFlowIds)
        })
    }

    public async getHogFlowsForTeams(teamIds: Team['id'][]): Promise<Record<Team['id'], HogFlow[]>> {
        const result = teamIds.reduce<Record<Team['id'], HogFlow[]>>((acc, teamId) => {
            acc[teamId] = []
            return acc
        }, {})

        const teamItemIds = await this.getHogFlowIdsForTeams(teamIds)
        const allIds = Object.values(teamItemIds).flat()
        const items = await this.lazyLoader.getMany(allIds)

        for (const item of Object.values(items)) {
            if (!item) {
                continue
            }
            result[item.team_id] = result[item.team_id] ?? []
            result[item.team_id].push(item)
        }

        return result
    }

    public async getHogFlowIdsForTeams(teamIds: Team['id'][]): Promise<Record<Team['id'], string[]>> {
        const result = teamIds.reduce<Record<Team['id'], string[]>>((acc, teamId) => {
            acc[teamId] = []
            return acc
        }, {})

        const teamItems = await this.lazyLoaderByTeam.getMany(teamIds.map((x) => x.toString()))

        if (!teamItems) {
            return result
        }

        // For each team, filter functions by type and collect their IDs
        Object.entries(teamItems).forEach(([teamId, teamFns]) => {
            if (teamFns) {
                result[parseInt(teamId)] = teamFns.map((fn) => fn.id)
            }
        })

        return result
    }

    public async getHogFlowsForTeam(teamId: Team['id']): Promise<HogFlow[]> {
        return (await this.getHogFlowsForTeams([teamId]))[teamId] ?? []
    }

    public async getHogFlow(id: HogFlow['id']): Promise<HogFlow | null> {
        return (await this.lazyLoader.get(id)) ?? null
    }

    public async getHogFlowCheckingPrimaryOnMiss(id: HogFlow['id']): Promise<HogFlow | null> {
        return (await this.getHogFlowsCheckingPrimaryOnMiss([id]))[id]
    }

    public async getHogFlowsCheckingPrimaryOnMiss(
        ids: HogFlow['id'][]
    ): Promise<Record<HogFlow['id'], HogFlow | null>> {
        const remembered = Object.fromEntries(ids.map((id) => [id, this.rememberedPrimaryResult(id)]))
        const cached = await this.lazyLoader.getMany(ids.filter((id) => !remembered[id]))
        const misses = [...new Set(ids.filter((id) => remembered[id] === undefined && !cached[id]))]
        const fromPrimary = await this.readPrimary(misses)
        return Object.fromEntries(ids.map((id) => [id, remembered[id] ?? cached[id] ?? fromPrimary[id] ?? null]))
    }

    private async readPrimary(ids: HogFlow['id'][]): Promise<Record<HogFlow['id'], HogFlow | null>> {
        const unread = ids.filter((id) => !this.primaryReads.has(id))
        if (unread.length > 0) {
            const read = this.fetchHogFlows(unread, PostgresUse.COMMON_WRITE)
            for (const id of unread) {
                const settled: Promise<HogFlow | null> = read.then((flows) =>
                    this.settlePrimaryRead(id, flows[id] ?? null, settled)
                )
                this.primaryReads.set(id, settled)
                const forget = (): void => {
                    if (this.primaryReads.get(id) === settled) {
                        this.primaryReads.delete(id)
                    }
                }
                settled.then(forget, forget)
            }
        }
        const reads = ids.map((id) => this.primaryReads.get(id) ?? Promise.resolve(null))
        const flows = await Promise.all(reads)
        return Object.fromEntries(ids.map((id, index) => [id, flows[index]]))
    }

    private settlePrimaryRead(id: HogFlow['id'], flow: HogFlow | null, read: Promise<HogFlow | null>): HogFlow | null {
        if (this.primaryReads.get(id) !== read) {
            return flow
        }
        if (flow) {
            this.lazyLoader.markForRefresh(id)
        }
        this.rememberPrimaryResult(id, flow)
        return flow
    }

    private rememberedPrimaryResult(id: HogFlow['id']): HogFlow | null | undefined {
        const remembered = this.primaryResults.get(id)
        if (remembered === undefined) {
            return undefined
        }
        if (remembered.until > Date.now()) {
            return remembered.flow
        }
        this.primaryResults.delete(id)
        return undefined
    }

    private rememberPrimaryResult(id: HogFlow['id'], flow: HogFlow | null): void {
        this.primaryResults.delete(id)
        if (this.primaryResults.size >= PRIMARY_RESULT_MAX_SIZE) {
            const oldest = this.primaryResults.keys().next().value
            if (oldest !== undefined) {
                this.primaryResults.delete(oldest)
            }
        }
        this.primaryResults.set(id, { flow, until: Date.now() + PRIMARY_RESULT_TTL_MS })
    }

    public async getHogFlows(ids: HogFlow['id'][]): Promise<Record<HogFlow['id'], HogFlow | null>> {
        return await this.lazyLoader.getMany(ids)
    }

    private onHogFlowsReloaded(teamId: Team['id'], hogFlowIds: HogFlow['id'][]): void {
        this.lazyLoaderByTeam.markForRefresh(teamId.toString())
        this.lazyLoader.markForRefresh(hogFlowIds)
        hogFlowIds.forEach((id) => {
            this.primaryResults.delete(id)
            this.primaryReads.delete(id)
        })
    }

    private async fetchTeamHogFlows(teamIds: string[]): Promise<Record<string, HogFlowTeamInfo[]>> {
        logger.debug('[HogFlowManager]', 'Fetching team hog flows', { teamIds })
        const response = await this.postgres.query<HogFlowTeamInfo>(
            PostgresUse.COMMON_READ,
            `SELECT id, team_id, version FROM posthog_hogflow WHERE status='active' AND team_id = ANY($1)`,
            [validTeamIds(teamIds)],
            'fetchAllTeamHogFlows'
        )

        const byTeam: Record<string, HogFlowTeamInfo[]> = {}

        for (const item of response.rows) {
            const teamId = item.team_id.toString()
            if (!byTeam[teamId]) {
                byTeam[teamId] = []
            }
            byTeam[teamId].push(item)
        }

        return byTeam
    }

    private async fetchHogFlows(
        ids: string[],
        use: PostgresUse = PostgresUse.COMMON_READ
    ): Promise<Record<string, HogFlow | undefined>> {
        logger.debug('[HogFlowManager]', 'Fetching hog flows', { ids })

        const response = await this.postgres.query<HogFlow>(
            use,
            `SELECT ${HOG_FLOW_FIELDS.join(', ')} FROM posthog_hogflow WHERE id = ANY($1)`,
            [ids],
            'fetchHogFlows'
        )

        const items = response.rows

        return items.reduce<Record<string, HogFlow | undefined>>((acc, item) => {
            // Ensure billable_action_types is properly parsed as an array
            // PostgreSQL might return empty JSON arrays as empty objects
            if (item.billable_action_types !== undefined && item.billable_action_types !== null) {
                if (!Array.isArray(item.billable_action_types)) {
                    // If it's an empty object, convert to empty array
                    if (
                        typeof item.billable_action_types === 'object' &&
                        Object.keys(item.billable_action_types).length === 0
                    ) {
                        item.billable_action_types = []
                    } else {
                        // For any other non-array value, default to empty array
                        item.billable_action_types = []
                    }
                }
            }
            try {
                this.mergeEncryptedInputs(item)
            } catch (error) {
                // A throw here would fail the batched load for every flow in it. Only this flow is left
                // out, because serving it without its secrets would skip a webhook trigger's auth check.
                logger.warn('[HogFlowManager]', 'Could not merge encrypted inputs - flow is left out', {
                    hogFlowId: item.id,
                    error: error instanceof Error ? error.message : 'Unknown error',
                })
                captureException(error)
                return acc
            }
            acc[item.id] = item
            return acc
        }, {})
    }

    // Decrypts `encrypted_inputs` and folds each action's secret inputs back into
    // `action.config.inputs` so the executor sees a whole config. `encrypted_inputs` is authoritative:
    // if a key also appears in plaintext `actions` (a row not yet re-saved since encryption shipped),
    // the encrypted value takes precedence, so both shapes resolve to the right value.
    private mergeEncryptedInputs(item: HogFlow): void {
        const raw = item.encrypted_inputs as unknown

        let decrypted: Record<string, Record<string, unknown>> | undefined
        if (raw && typeof raw === 'object' && !Array.isArray(raw)) {
            // The sql lib occasionally hands back an already-parsed object
            decrypted = raw as Record<string, Record<string, unknown>>
        } else if (typeof raw === 'string' && raw) {
            try {
                const plaintext = this.encryptedFields.decrypt(raw)
                if (plaintext) {
                    decrypted = parseJSON(plaintext)
                }
            } catch (error) {
                // The blob is dropped below and the flow runs without its secrets (fail-open, matching
                // HogFunctionManagerService). The counter makes the failure alertable - the most likely
                // cause is Fernet key skew between Django and the workers.
                logger.warn('[HogFlowManager]', 'Could not decrypt encrypted inputs - flow will run without them', {
                    error: error instanceof Error ? error.message : 'Unknown error',
                })
                counterEncryptedInputsDecryptFailed.inc()
                captureException(error)
            }
        }

        // Drop the encrypted blob from the in-memory flow either way - downstream reads inputs off
        // `action.config.inputs`, and this keeps the ciphertext out of anything that logs the flow.
        delete item.encrypted_inputs

        if (!decrypted) {
            return
        }

        for (const action of item.actions ?? []) {
            const actionSecrets = decrypted[action.id]
            if (!actionSecrets || !('config' in action)) {
                continue
            }
            const config = action.config as { inputs?: Record<string, unknown> }
            config.inputs = { ...config.inputs, ...actionSecrets }

            // The top-level `trigger` is derived from the trigger action and is stripped of secrets
            // the same way. The source-webhook consumer builds its function from `hogFlow.trigger`
            // (not the action), so re-merge the trigger action's secrets there too or a webhook
            // trigger's secret auth header would be missing at runtime.
            if (action.type === 'trigger' && item.trigger && 'inputs' in item.trigger) {
                const trigger = item.trigger as { inputs?: Record<string, unknown> }
                trigger.inputs = { ...trigger.inputs, ...actionSecrets }
            }
        }
    }
}
