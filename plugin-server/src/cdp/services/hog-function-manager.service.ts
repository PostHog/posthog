import { captureException } from '@sentry/node'
import * as schedule from 'node-schedule'

import { Hub, Team } from '../../types'
import { PostgresUse } from '../../utils/db/postgres'
import { PubSub } from '../../utils/pubsub'
import { status } from '../../utils/status'
import { HogFunctionType, HogFunctionTypeType, IntegrationType } from '../types'

const HOG_FUNCTION_FIELDS = [
    'id',
    'team_id',
    'name',
    'enabled',
    'deleted',
    'inputs',
    'encrypted_inputs',
    'inputs_schema',
    'filters',
    'mappings',
    'bytecode',
    'masking',
    'type',
    'template_id',
    'execution_order',
    'created_at',
    'updated_at',
]

export class HogFunctionManagerService {
    private started: boolean
    private ready: boolean
    private hogFunctions: Record<HogFunctionType['id'], HogFunctionType | undefined>
    private orderedHogFunctionsCache: Record<Team['id'], HogFunctionType[] | undefined>

    private pubSub: PubSub
    private refreshJob?: schedule.Job
    private hogTypes: HogFunctionTypeType[] = []
    private lastUpdatedAt: string | null = null

    constructor(private hub: Hub) {
        this.started = false
        this.ready = false
        this.hogFunctions = {}
        this.orderedHogFunctionsCache = {}

        this.pubSub = new PubSub(this.hub, {
            'reload-integrations': async (message) => {
                const { integrationIds, teamId } = JSON.parse(message)
                await this.reloadIntegrations(teamId, integrationIds)
            },
        })
    }

    public async start(hogTypes: HogFunctionTypeType[]): Promise<void> {
        this.hogTypes = hogTypes
        // TRICKY - when running with individual capabilities, this won't run twice but locally or as a complete service it will...

        if (this.started) {
            return
        }
        this.started = true
        await this.pubSub.start()
        await this.reloadAllHogFunctions()

        // every 5 minutes all HogFunctionManagerService caches are reloaded for eventual consistency
        this.refreshJob = schedule.scheduleJob('*/1 * * * *', async () => {
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
            throw new Error('HogFunctionManagerService is not ready! Run HogFunctionManagerService.start() before this')
        }

        if (!this.orderedHogFunctionsCache[teamId]) {
            const functions = Object.values(this.hogFunctions).filter((x) => x?.team_id === teamId) as HogFunctionType[]
            this.orderedHogFunctionsCache[teamId] = this.sortHogFunctions(functions)
        }

        return this.orderedHogFunctionsCache[teamId] || []
    }

    /**
     * Sorts HogFunctions by their execution_order and creation date.
     * Functions with no execution_order are placed at the end.
     * When execution_order is the same, earlier created functions come first.
     */
    private sortHogFunctions(functions: HogFunctionType[]): HogFunctionType[] {
        return [...functions].sort((a, b) => {
            // If either execution_order is null/undefined, it should go last
            if (a.execution_order == null && b.execution_order == null) {
                // Both are null/undefined, sort by creation date
                return new Date(a.created_at).getTime() - new Date(b.created_at).getTime()
            }

            // Null/undefined values go last
            if (a.execution_order == null) {
                return 1
            }
            if (b.execution_order == null) {
                return -1
            }

            // If execution orders are different, sort by them
            if (a.execution_order !== b.execution_order) {
                return a.execution_order - b.execution_order
            }

            // If execution orders are the same, sort by creation date
            return new Date(a.created_at).getTime() - new Date(b.created_at).getTime()
        })
    }

    public getHogFunction(id: HogFunctionType['id']): HogFunctionType | undefined {
        if (!this.ready) {
            throw new Error('HogFunctionManagerService is not ready! Run HogFunctionManagerService.start() before this')
        }

        return this.hogFunctions[id]
    }

    public teamHasHogDestinations(teamId: Team['id']): boolean {
        return !!Object.keys(this.getTeamHogFunctions(teamId)).length
    }

    /**
     * Reloads all hog functions that have updates since the last full reload.
     * If we have never loaded then we only load enabled hog functions
     * Otherwise we load all hog functions that have been updated so we can also remove
     */
    public async reloadAllHogFunctions(): Promise<void> {
        const items = (
            this.lastUpdatedAt
                ? await this.hub.postgres.query<HogFunctionType>(
                      PostgresUse.COMMON_READ,
                      `SELECT ${HOG_FUNCTION_FIELDS.join(', ')} FROM posthog_hogfunction WHERE type = ANY($1)
                       AND updated_at > $2 
                       ORDER BY updated_at ASC`,
                      [this.hogTypes, this.lastUpdatedAt],
                      'fetchUpdatedHogFunctions'
                  )
                : await this.hub.postgres.query<HogFunctionType>(
                      PostgresUse.COMMON_READ,
                      `SELECT ${HOG_FUNCTION_FIELDS.join(', ')} FROM posthog_hogfunction WHERE type = ANY($1)
                        AND deleted = FALSE AND enabled = TRUE 
                        ORDER BY updated_at ASC`,
                      [this.hogTypes],
                      'fetchAllHogFunctions'
                  )
        ).rows

        if (!items.length) {
            status.debug('🍿', 'No updated hog functions found')
            return
        }

        // Add all new functions and remove all deleted or disabled functions
        for (const item of items) {
            // Clear the cache for this team in case the order changed
            delete this.orderedHogFunctionsCache[item.team_id]
            if (item.enabled && !item.deleted) {
                this.hogFunctions[item.id] = item
            } else {
                delete this.hogFunctions[item.id]
            }
        }

        const functions = Object.values(this.hogFunctions).filter((x) => !!x) as HogFunctionType[]
        this.sanitize(functions)
        await this.enrichWithIntegrations(functions)

        this.lastUpdatedAt = items[items.length - 1].updated_at
        status.info('🍿', 'Fetched all hog functions from DB anew')
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

        // TODO: Change this to be like the reloadAllHogFunctions so we can also update the cache

        const items = this.getTeamHogFunctions(teamId)
        const itemsToReload = items.filter((item) => ids.some((id) => item.depends_on_integration_ids?.has(id)))

        return this.enrichWithIntegrations(itemsToReload)
    }

    public sanitize(items: HogFunctionType[]): void {
        items.forEach((item) => {
            const encryptedInputsString = item.encrypted_inputs as string | undefined

            if (!Array.isArray(item.inputs_schema)) {
                // NOTE: The sql lib can sometimes return an empty object instead of an empty array
                item.inputs_schema = []
            }

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
