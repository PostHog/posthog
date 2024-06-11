import * as schedule from 'node-schedule'

import { PluginsServerConfig, Team } from '../types'
import { PostgresRouter, PostgresUse } from '../utils/db/postgres'
import { PubSub } from '../utils/pubsub'
import { status } from '../utils/status'
import { HogFunctionType } from './types'

export type HogFunctionMap = Record<HogFunctionType['id'], HogFunctionType>
export type HogFunctionCache = Record<Team['id'], HogFunctionMap>

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

    public getTeamHogFunctions(teamId: Team['id']): HogFunctionMap {
        if (!this.ready) {
            throw new Error('HogFunctionManager is not ready! Run HogFunctionManager.start() before this')
        }
        return this.cache[teamId] || {}
    }

    public async reloadAllHogFunctions(): Promise<void> {
        this.cache = await fetchAllHogFunctionsGroupedByTeam(this.postgres)
        status.info('🍿', 'Fetched all hog functions from DB anew')
    }

    public async reloadHogFunctions(teamId: Team['id'], ids: HogFunctionType['id'][]): Promise<void> {
        status.info('🍿', `Reloading hog functions ${ids} from DB`)
        const items = await fetchHogFunctions(this.postgres, ids)

        // for each item we need to update the cache
        // if the ID is not in the list we need to remove it from the cache

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
}

const HOG_FUNCTION_FIELDS = ['id', 'team_id', 'name', 'enabled', 'inputs', 'filters', 'bytecode']

export async function fetchAllHogFunctionsGroupedByTeam(client: PostgresRouter): Promise<HogFunctionCache> {
    const items = (
        await client.query<HogFunctionType>(
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

    const cache: HogFunctionCache = {}
    for (const item of items) {
        if (!cache[item.team_id]) {
            cache[item.team_id] = {}
        }

        cache[item.team_id][item.id] = item
    }

    return cache
}

export async function fetchHogFunctions(
    client: PostgresRouter,
    ids: HogFunctionType['id'][]
): Promise<HogFunctionType[]> {
    const items: HogFunctionType[] = (
        await client.query(
            PostgresUse.COMMON_READ,
            `SELECT ${HOG_FUNCTION_FIELDS.join(', ')}
                FROM posthog_hogfunction
                WHERE id = ANY($1)) AND deleted = FALSE AND enabled = TRUE`,
            [ids],
            'fetchHogFunctions'
        )
    ).rows
    return items
}
