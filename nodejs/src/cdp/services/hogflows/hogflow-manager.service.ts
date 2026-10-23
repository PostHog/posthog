import { Counter } from 'prom-client'

import { HogFlow } from '~/cdp/schema/hogflow'
import { PostgresRouter, PostgresUse } from '~/common/utils/db/postgres'
import { parseJSON } from '~/common/utils/json-parse'
import { DEFAULT_LOADER_RETRY, LazyLoader } from '~/common/utils/lazy-loader'
import { logger } from '~/common/utils/logger'
import { captureException } from '~/common/utils/posthog'
import { PubSub } from '~/common/utils/pubsub'
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

type HogFlowRevisionSteps = Pick<HogFlow, 'actions' | 'edges' | 'trigger'>

export class HogFlowManagerService {
    private lazyLoader: LazyLoader<HogFlow>
    private lazyLoaderByTeam: LazyLoader<HogFlowTeamInfo[]>
    private revisionStepsLoader: LazyLoader<HogFlowRevisionSteps>
    private actionIdsWithSecrets = new WeakMap<HogFlow, ReadonlySet<string>>()

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

        // A revision never changes, so it needs no reload.
        this.revisionStepsLoader = new LazyLoader({
            name: 'hog_flow_revision_steps',
            loaderRetry: DEFAULT_LOADER_RETRY,
            loader: async (keys) => await this.fetchRevisionSteps(keys),
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

    public async getHogFlows(ids: HogFlow['id'][]): Promise<Record<HogFlow['id'], HogFlow | null>> {
        return await this.lazyLoader.getMany(ids)
    }

    /**
     * The flow with the steps and trigger it had when it was published as `version`. Everything else, such as
     * its status and email pause, stays live, and a step that is sensitive now stays sensitive. Null when no
     * revision holds that version, or when a step of it holds secret inputs, which revisions do not store.
     */
    public async getHogFlowAtVersion(hogFlow: HogFlow, version: number): Promise<HogFlow | null> {
        const steps = await this.revisionStepsLoader.get(revisionKey(hogFlow.id, version))
        const liveSecrets = this.actionIdsWithSecrets.get(hogFlow)
        if (!steps || steps.actions.some((action) => liveSecrets?.has(action.id))) {
            return null
        }
        return { ...hogFlow, ...steps, actions: withLiveSensitivity(steps.actions, hogFlow.actions), version }
    }

    private async fetchRevisionSteps(keys: string[]): Promise<Record<string, HogFlowRevisionSteps | undefined>> {
        const revisions = keys.map(parseRevisionKey)
        const response = await this.postgres.query<{ hog_flow_id: string; version: number; content: HogFlow }>(
            PostgresUse.COMMON_READ,
            `SELECT r.hog_flow_id, r.version, r.content
             FROM workflows_hogflowrevision r
             JOIN unnest($1::uuid[], $2::int[]) AS k(hog_flow_id, version)
               ON r.hog_flow_id = k.hog_flow_id AND r.version = k.version`,
            [revisions.map((r) => r.hogFlowId), revisions.map((r) => r.version)],
            'fetchHogFlowRevisionSteps'
        )
        const steps: Record<string, HogFlowRevisionSteps | undefined> = {}
        for (const row of response.rows) {
            steps[revisionKey(row.hog_flow_id, row.version)] = {
                actions: row.content.actions,
                edges: row.content.edges,
                trigger: row.content.trigger,
            }
        }
        return steps
    }

    private onHogFlowsReloaded(teamId: Team['id'], hogFlowIds: HogFlow['id'][]): void {
        this.lazyLoaderByTeam.markForRefresh(teamId.toString())
        this.lazyLoader.markForRefresh(hogFlowIds)
    }

    private async fetchTeamHogFlows(teamIds: string[]): Promise<Record<string, HogFlowTeamInfo[]>> {
        logger.debug('[HogFlowManager]', 'Fetching team hog flows', { teamIds })
        const response = await this.postgres.query<HogFlowTeamInfo>(
            PostgresUse.COMMON_READ,
            `SELECT id, team_id, version FROM posthog_hogflow WHERE status='active' AND team_id = ANY($1)`,
            [teamIds],
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

    private async fetchHogFlows(ids: string[]): Promise<Record<string, HogFlow | undefined>> {
        logger.debug('[HogFlowManager]', 'Fetching hog flows', { ids })

        const response = await this.postgres.query<HogFlow>(
            PostgresUse.COMMON_READ,
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
            this.mergeEncryptedInputs(item)
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
        this.actionIdsWithSecrets.set(item, new Set(Object.keys(decrypted)))

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

const revisionKey = (hogFlowId: HogFlow['id'], version: number): string => `${hogFlowId}:${version}`

const parseRevisionKey = (key: string): { hogFlowId: string; version: number } => {
    const separator = key.lastIndexOf(':')
    return { hogFlowId: key.slice(0, separator), version: Number(key.slice(separator + 1)) }
}

const withLiveSensitivity = (pinned: HogFlow['actions'], live: HogFlow['actions']): HogFlow['actions'] => {
    const sensitiveIds = new Set(
        live
            .filter((action) => action.type === 'function_email' && action.config.sensitive === true)
            .map((action) => action.id)
    )
    return pinned.map((action) =>
        action.type === 'function_email' && sensitiveIds.has(action.id)
            ? { ...action, config: { ...action.config, sensitive: true } }
            : action
    )
}
