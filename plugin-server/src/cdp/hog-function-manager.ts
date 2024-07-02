import * as schedule from 'node-schedule'

import { PluginsServerConfig, Team } from '../types'
import { PostgresRouter, PostgresUse } from '../utils/db/postgres'
import { PubSub } from '../utils/pubsub'
import { status } from '../utils/status'
import { HogFunctionType, IntegrationType } from './types'

export type HogFunctionMap = Record<HogFunctionType['id'], HogFunctionType>
export type HogFunctionCache = Record<Team['id'], HogFunctionMap>

const HOG_FUNCTION_FIELDS = ['id', 'team_id', 'name', 'enabled', 'inputs', 'inputs_schema', 'filters', 'bytecode']

export class HogFunctionManager {
    private started: boolean
    private ready: boolean
    private cache: HogFunctionCache
    private pubSub: PubSub
    private refreshJob?: schedule.Job

    constructor(private postgres: PostgresRouter, private serverConfig: PluginsServerConfig) {
        this.started = false
        this.ready = false
        this.cache = {}

        this.pubSub = new PubSub(this.serverConfig, {
            'reload-hog-functions': async (message) => {
                const { hogFunctionIds, teamId } = JSON.parse(message)
                await this.reloadHogFunctions(teamId, hogFunctionIds)
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
        return Object.values(this.cache[teamId] || {})
    }

    public getTeamHogFunction(teamId: Team['id'], hogFunctionId: HogFunctionType['id']): HogFunctionType | undefined {
        if (!this.ready) {
            throw new Error('HogFunctionManager is not ready! Run HogFunctionManager.start() before this')
        }
        return this.cache[teamId]?.[hogFunctionId]
    }

    public teamHasHogFunctions(teamId: Team['id']): boolean {
        return !!Object.keys(this.getTeamHogFunctions(teamId)).length
    }

    public async reloadAllHogFunctions(): Promise<void> {
        const items = (
            await this.postgres.query<HogFunctionType>(
                PostgresUse.COMMON_READ,
                `
            SELECT ${HOG_FUNCTION_FIELDS.join(', ')}
            FROM posthog_hogfunction
            WHERE deleted = FALSE AND enabled = TRUE
        `,
                [],
                'fetchAllHogFunctions'
            )
        ).rows

        await this.enrichWithIntegrations(items)

        const cache: HogFunctionCache = {}
        for (const item of items) {
            if (!cache[item.team_id]) {
                cache[item.team_id] = {}
            }

            cache[item.team_id][item.id] = item
        }

        this.cache = cache
        status.info('🍿', 'Fetched all hog functions from DB anew')
    }

    public async reloadHogFunctions(teamId: Team['id'], ids: HogFunctionType['id'][]): Promise<void> {
        status.info('🍿', `Reloading hog functions ${ids} from DB`)

        const items: HogFunctionType[] = (
            await this.postgres.query(
                PostgresUse.COMMON_READ,
                `SELECT ${HOG_FUNCTION_FIELDS.join(', ')}
                FROM posthog_hogfunction
                WHERE id = ANY($1) AND deleted = FALSE AND enabled = TRUE`,
                [ids],
                'fetchEnabledHogFunctions'
            )
        ).rows

        await this.enrichWithIntegrations(items)

        if (!this.cache[teamId]) {
            this.cache[teamId] = {}
        }

        for (const id of ids) {
            // First of all delete the item from the cache - this covers the case where the item was deleted or disabled
            delete this.cache[teamId][id]
        }

        for (const item of items) {
            this.cache[teamId][item.id] = item
        }
    }

    public async fetchHogFunction(id: HogFunctionType['id']): Promise<HogFunctionType | null> {
        const items: HogFunctionType[] = (
            await this.postgres.query(
                PostgresUse.COMMON_READ,
                `SELECT ${HOG_FUNCTION_FIELDS.join(', ')}
                FROM posthog_hogfunction
                WHERE id = $1 AND deleted = FALSE`,
                [id],
                'fetchHogFunction'
            )
        ).rows
        await this.enrichWithIntegrations(items)
        return items[0] ?? null
    }

    public async enrichWithIntegrations(items: HogFunctionType[]): Promise<void> {
        const integrationIds: number[] = []

        items.forEach((item) => {
            item.inputs_schema?.forEach((schema) => {
                if (schema.type === 'integration') {
                    const input = item.inputs?.[schema.key]
                    if (input && typeof input.value === 'number') {
                        integrationIds.push(input.value)
                    }
                }
            })
        })

        if (!items.length) {
            return
        }

        const integrations: IntegrationType[] = (
            await this.postgres.query(
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
                return {
                    ...acc,
                    [`${integration.team_id}:${integration.id}`]: {
                        ...integration.config,
                        ...integration.sensitive_config,
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
