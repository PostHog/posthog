import { captureException } from '@sentry/node'
import * as schedule from 'node-schedule'

import { Hub, Team } from '../types'
import { PostgresUse } from '../utils/db/postgres'
import { PubSub } from '../utils/pubsub'
import { status } from '../utils/status'
import { HogFunctionType, IntegrationType } from './types'

type HogFunctionCache = {
    functions: Record<HogFunctionType['id'], HogFunctionType | undefined>
    teams: Record<Team['id'], HogFunctionType['id'][] | undefined>
}

const HOG_FUNCTION_FIELDS = [
    'id',
    'team_id',
    'name',
    'enabled',
    'inputs',
    'encrypted_inputs',
    'inputs_schema',
    'filters',
    'bytecode',
    'masking',
    'type',
]

const RELOAD_HOG_FUNCTION_TYPES = ['destination', 'email']

export class HogFunctionManager {
    private started: boolean
    private ready: boolean
    private cache: HogFunctionCache
    private pubSub: PubSub
    private refreshJob?: schedule.Job

    constructor(private hub: Hub) {
        this.started = false
        this.ready = false
        this.cache = {
            functions: {},
            teams: {},
        }

        this.pubSub = new PubSub(this.hub, {
            'reload-hog-functions': async (message) => {
                const { hogFunctionIds, teamId } = JSON.parse(message)
                await this.reloadHogFunctions(teamId, hogFunctionIds)
            },

            'reload-all-hog-functions': async () => {
                await this.reloadAllHogFunctions()
            },

            'reload-integrations': async (message) => {
                const { integrationIds, teamId } = JSON.parse(message)
                await this.reloadIntegrations(teamId, integrationIds)
            },
        })
    }

    public async start(): Promise<void> {
        // TRICKY - when running with individual capabilities, this won't run twice but locally or as a complete service it will...
        if (this.started) {
            return
        }
        this.started = true
        await this.pubSub.start()
        await this.reloadAllHogFunctions()

        // every 5 minutes all HogFunctionManager caches are reloaded for eventual consistency
        this.refreshJob = schedule.scheduleJob('*/5 * * * *', async () => {
            await this.reloadAllHogFunctions().catch((error) => {
                status.error('🍿', 'Error reloading hog functions:', error)
            })
        })
        this.ready = true
    }

    public async stop(): Promise<void> {
        if (this.refreshJob) {
            schedule.cancelJob(this.refreshJob)
        }

        await this.pubSub.stop()
    }

    public getTeamHogFunctions(teamId: Team['id']): HogFunctionType[] {
        if (!this.ready) {
            throw new Error('HogFunctionManager is not ready! Run HogFunctionManager.start() before this')
        }

        return Object.values(this.cache.teams[teamId] || [])
            .map((id) => this.cache.functions[id])
            .filter((x) => !!x) as HogFunctionType[]
    }

    public getTeamHogDestinations(teamId: Team['id']): HogFunctionType[] {
        return this.getTeamHogFunctions(teamId).filter((x) => x.type === 'destination' || !x.type)
    }

    public getHogFunction(id: HogFunctionType['id']): HogFunctionType | undefined {
        if (!this.ready) {
            throw new Error('HogFunctionManager is not ready! Run HogFunctionManager.start() before this')
        }

        return this.cache.functions[id]
    }

    public getTeamHogFunction(teamId: Team['id'], hogFunctionId: HogFunctionType['id']): HogFunctionType | undefined {
        if (!this.ready) {
            throw new Error('HogFunctionManager is not ready! Run HogFunctionManager.start() before this')
        }

        const fn = this.cache.functions[hogFunctionId]
        if (fn?.team_id === teamId) {
            return fn
        }
    }

    public teamHasHogDestinations(teamId: Team['id']): boolean {
        return !!Object.keys(this.getTeamHogDestinations(teamId)).length
    }

    public async reloadAllHogFunctions(): Promise<void> {
        const items = (
            await this.hub.postgres.query<HogFunctionType>(
                PostgresUse.COMMON_READ,
                `
            SELECT ${HOG_FUNCTION_FIELDS.join(', ')}
            FROM posthog_hogfunction
            WHERE deleted = FALSE AND enabled = TRUE AND (type is NULL or type = ANY($1))
        `,
                [RELOAD_HOG_FUNCTION_TYPES],
                'fetchAllHogFunctions'
            )
        ).rows

        this.sanitize(items)
        await this.enrichWithIntegrations(items)

        const cache: HogFunctionCache = {
            functions: {},
            teams: {},
        }

        for (const item of items) {
            cache.functions[item.id] = item
            cache.teams[item.team_id] = cache.teams[item.team_id] || []
            cache.teams[item.team_id]!.push(item.id)
        }

        this.cache = cache
        status.info('🍿', 'Fetched all hog functions from DB anew')
    }

    public async reloadHogFunctions(teamId: Team['id'], ids: HogFunctionType['id'][]): Promise<void> {
        status.info('🍿', `Reloading hog functions ${ids} from DB`)

        const items: HogFunctionType[] = (
            await this.hub.postgres.query(
                PostgresUse.COMMON_READ,
                `SELECT ${HOG_FUNCTION_FIELDS.join(', ')}
                FROM posthog_hogfunction
                WHERE id = ANY($1) AND deleted = FALSE AND enabled = TRUE`,
                [ids],
                'fetchEnabledHogFunctions'
            )
        ).rows

        this.sanitize(items)
        await this.enrichWithIntegrations(items)

        for (const id of ids) {
            delete this.cache.functions[id]
            this.cache.teams[teamId] = this.cache.teams[teamId]?.filter((x) => x !== id)
        }

        for (const item of items) {
            this.cache.functions[item.id] = item
            this.cache.teams[teamId] = this.cache.teams[teamId] || []
            this.cache.teams[teamId]!.push(item.id)
        }
    }

    public async fetchHogFunction(id: HogFunctionType['id']): Promise<HogFunctionType | null> {
        const items: HogFunctionType[] = (
            await this.hub.postgres.query(
                PostgresUse.COMMON_READ,
                `SELECT ${HOG_FUNCTION_FIELDS.join(', ')}
                FROM posthog_hogfunction
                WHERE id = $1 AND deleted = FALSE`,
                [id],
                'fetchHogFunction'
            )
        ).rows

        this.sanitize(items)
        await this.enrichWithIntegrations(items)
        return items[0] ?? null
    }

    public reloadIntegrations(teamId: Team['id'], ids: IntegrationType['id'][]): Promise<void> {
        // We need to find all hog functions that depend on these integrations and re-enrich them

        const items = this.getTeamHogFunctions(teamId)
        const itemsToReload = items.filter((item) => ids.some((id) => item.depends_on_integration_ids?.has(id)))

        return this.enrichWithIntegrations(itemsToReload)
    }

    public sanitize(items: HogFunctionType[]): void {
        items.forEach((item) => {
            const encryptedInputsString = item.encrypted_inputs as string | undefined

            if (encryptedInputsString) {
                try {
                    const decrypted = this.hub.encryptedFields.decrypt(encryptedInputsString || '')
                    item.encrypted_inputs = decrypted ? JSON.parse(decrypted) : {}
                } catch (error) {
                    status.error('🍿', 'Error parsing encrypted inputs:', error)
                    captureException(error)
                    // Quietly fail - not ideal but better then crashing out
                }
            }
        })

        return
    }

    public async enrichWithIntegrations(items: HogFunctionType[]): Promise<void> {
        const integrationIds: number[] = []

        items.forEach((item) => {
            item.inputs_schema?.forEach((schema) => {
                if (schema.type === 'integration') {
                    const input = item.inputs?.[schema.key]
                    if (input && typeof input.value === 'number') {
                        integrationIds.push(input.value)
                        item.depends_on_integration_ids = item.depends_on_integration_ids || new Set()
                        item.depends_on_integration_ids.add(input.value)
                    }
                }
            })
        })

        if (!items.length) {
            return
        }

        const integrations: IntegrationType[] = (
            await this.hub.postgres.query(
                PostgresUse.COMMON_READ,
                `SELECT id, team_id, kind, config, sensitive_config
                FROM posthog_integration
                WHERE id = ANY($1)`,
                [integrationIds],
                'fetchIntegrations'
            )
        ).rows

        const integrationConfigsByTeamAndId: Record<string, Record<string, any>> = integrations.reduce(
            (acc, integration) => {
                // Decrypt the sensitive config here
                return {
                    ...acc,
                    [`${integration.team_id}:${integration.id}`]: {
                        ...integration.config,
                        ...this.hub.encryptedFields.decryptObject(integration.sensitive_config || {}, {
                            ignoreDecryptionErrors: true,
                        }),
                    },
                }
            },
            {}
        )

        items.forEach((item) => {
            item.inputs_schema?.forEach((schema) => {
                if (schema.type === 'integration') {
                    const input = item.inputs?.[schema.key]
                    if (!input) {
                        return
                    }
                    const integrationId = input.value
                    const integrationConfig = integrationConfigsByTeamAndId[`${item.team_id}:${integrationId}`]
                    if (integrationConfig) {
                        input.value = integrationConfig
                    }
                }
            })
        })
    }
}
