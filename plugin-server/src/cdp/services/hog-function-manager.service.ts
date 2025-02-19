import * as schedule from 'node-schedule'

import { Hub, Team } from '../../types'
import { PostgresUse } from '../../utils/db/postgres'
import { captureException } from '../../utils/posthog'
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
    private refreshIntegrationsJob?: schedule.Job
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
            'reload-hog-functions': async () => {
                await this.reloadAllHogFunctions()
            },
            'reload-all-hog-functions': async () => {
                await this.reloadAllHogFunctions()
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

        // every 1 minute we reload all updated hog functions
        this.refreshJob = schedule.scheduleJob('*/1 * * * *', async () => {
            await this.reloadAllHogFunctions().catch((error) => {
                status.error('🍿', 'Error reloading hog functions:', error)
            })
        })

        // every 1 minute we reload all updated hog functions
        this.refreshIntegrationsJob = schedule.scheduleJob('*/5 * * * *', async () => {
            status.info('🍿', 'Refreshing integrations')
            await this.reloadAllIntegrations().catch((error) => {
                status.error('🍿', 'Error reloading integrations:', error)
            })
        })
        this.ready = true
    }

    public async stop(): Promise<void> {
        if (this.refreshJob) {
            schedule.cancelJob(this.refreshJob)
        }
        if (this.refreshIntegrationsJob) {
            schedule.cancelJob(this.refreshIntegrationsJob)
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
        status.info('🍿', 'Reloading all hog functions')

        const items = (
            this.lastUpdatedAt
                ? // If we have the latest updated at timestamp for a hog function then we load all updated hog functions
                  // Whether deleted/enabled or not
                  await this.hub.postgres.query<HogFunctionType>(
                      PostgresUse.COMMON_READ,
                      `SELECT ${HOG_FUNCTION_FIELDS.join(', ')} FROM posthog_hogfunction WHERE type = ANY($1)
                       AND updated_at > $2
                       ORDER BY updated_at ASC`,
                      [this.hogTypes, this.lastUpdatedAt],
                      'fetchUpdatedHogFunctions'
                  )
                : // Otherwise just load all enabled functions
                  await this.hub.postgres.query<HogFunctionType>(
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

        // The query is sorted by updated_at so we can just take the last one
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
        status.info('🍿', 'Reloading integrations', { teamId, integrationCount: ids.length })

        // We need to find all hog functions that depend on these integrations and re-enrich them

        // TODO: Change this to be like the reloadAllHogFunctions so we can also update the cache

        const items = this.getTeamHogFunctions(teamId)
        const itemsToReload = items.filter((item) => ids.some((id) => item.depends_on_integration_ids?.has(id)))

        return this.enrichWithIntegrations(itemsToReload)
    }

    public async reloadAllIntegrations(): Promise<void> {
        status.info('🍿', 'Reloading all integrations')
        // Reload all integrations for all hog functions in use
        await this.enrichWithIntegrations(Object.values(this.hogFunctions).filter((x) => !!x) as HogFunctionType[])
    }

    public sanitize(items: HogFunctionType[]): void {
        items.forEach((item) => {
            const encryptedInputs = item.encrypted_inputs

            if (!Array.isArray(item.inputs_schema)) {
                // NOTE: The sql lib can sometimes return an empty object instead of an empty array
                item.inputs_schema = []
            }

            // Handle case where encrypted_inputs is already an object
            if (encryptedInputs && typeof encryptedInputs === 'object' && !Array.isArray(encryptedInputs)) {
                return
            }

            // Handle case where encrypted_inputs is a string that needs decryption
            if (typeof encryptedInputs === 'string') {
                try {
                    const decrypted = this.hub.encryptedFields.decrypt(encryptedInputs)
                    if (decrypted) {
                        item.encrypted_inputs = JSON.parse(decrypted)
                    }
                } catch (error) {
                    if (encryptedInputs) {
                        status.warn('🍿', 'Could not parse encrypted inputs - preserving original value', {
                            error: error instanceof Error ? error.message : 'Unknown error',
                        })
                        captureException(error)
                    }
                }
            }
            // For any other case (null, undefined, unexpected types), leave as-is
        })
    }

    public async enrichWithIntegrations(items: HogFunctionType[]): Promise<void> {
        status.info('🍿', 'Enriching with integrations', { functionCount: items.length })
        const integrationIds: number[] = []

        items.forEach((item) => {
            item.inputs_schema?.forEach((schema) => {
                if (schema.type === 'integration') {
                    const input = item.inputs?.[schema.key]
                    const value = input?.value?.integrationId ?? input?.value
                    if (value && typeof value === 'number') {
                        integrationIds.push(value)
                        item.depends_on_integration_ids = item.depends_on_integration_ids || new Set()
                        item.depends_on_integration_ids.add(value)
                    }
                }
            })
        })

        if (!integrationIds.length) {
            status.info('🍿', 'No integrations to enrich with')
            return
        }

        status.info('🍿', 'Fetching integrations', { integrationCount: integrationIds.length })

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

        status.info('🍿', 'Decrypting integrations', { integrationCount: integrations.length })

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
                        integrationId: integration.id,
                    },
                }
            },
            {}
        )
        status.info('🍿', 'Enriching hog functions', { functionCount: items.length })

        let updatedValuesCount = 0
        items.forEach((item) => {
            item.inputs_schema?.forEach((schema) => {
                if (schema.type === 'integration') {
                    const input = item.inputs?.[schema.key]
                    if (!input) {
                        return
                    }
                    const integrationId = input.value?.integrationId ?? input.value
                    const integrationConfig = integrationConfigsByTeamAndId[`${item.team_id}:${integrationId}`]
                    if (integrationConfig) {
                        input.value = integrationConfig
                        updatedValuesCount++
                    }
                }
            })
        })
        status.info('🍿', 'Enriched hog functions', { functionCount: items.length, updatedValuesCount })
    }
}
