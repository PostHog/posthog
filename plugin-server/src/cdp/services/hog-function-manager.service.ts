import { Hub, Team } from '../../types'
import { PostgresUse } from '../../utils/db/postgres'
import { parseJSON } from '../../utils/json-parse'
import { LazyLoader } from '../../utils/lazy-loader'
import { logger } from '../../utils/logger'
import { captureException } from '../../utils/posthog'
import { PubSub } from '../../utils/pubsub'
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

export type HogFunctionTeamInfo = Pick<HogFunctionType, 'id' | 'team_id' | 'type'>

// /**
//  * Sorts HogFunctions by their execution_order and creation date.
//  * Functions with no execution_order are placed at the end.
//  * When execution_order is the same, earlier created functions come first.
//  */
const sortHogFunctions = (functions: HogFunctionType[]): HogFunctionType[] => {
    return [...functions].sort((a, b) => {
        // If either execution_order is null/undefined, it should go last
        if (a.execution_order == null && b.execution_order == null) {
            // Both are null/undefined, sort by creation date - ISO dates are lexicographically sortable
            return a.created_at.localeCompare(b.created_at)
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
        return a.created_at.localeCompare(b.created_at)
    })
}

export class HogFunctionManagerService {
    private lazyLoader: LazyLoader<HogFunctionType>
    private lazyLoaderByTeam: LazyLoader<HogFunctionTeamInfo[]>
    private started: boolean
    private pubSub: PubSub

    constructor(private hub: Hub) {
        this.started = false

        this.pubSub = new PubSub(this.hub, {
            'reload-integrations': (message) => {
                const { integrationIds } = parseJSON(message) as {
                    integrationIds: IntegrationType['id'][]
                }
                this.onIntegrationsReloaded(integrationIds)
            },
            'reload-hog-functions': (message) => {
                const { teamId, hogFunctionIds } = parseJSON(message) as {
                    teamId: Team['id']
                    hogFunctionIds: HogFunctionType['id'][]
                }

                logger.info('[HogFunctionManager]', 'Marking hog functions for refresh', {
                    teamId,
                    hogFunctionIds,
                })
                this.onHogFunctionsReloaded(teamId, hogFunctionIds)
            },
        })

        this.lazyLoaderByTeam = new LazyLoader({
            name: 'hog_function_manager_by_team',
            loader: async (teamIds) => await this.fetchTeamHogFunctions(teamIds),
        })

        this.lazyLoader = new LazyLoader({
            name: 'hog_function_manager',
            loader: async (ids) => await this.fetchHogFunctions(ids),
        })
    }

    public async start(): Promise<void> {
        // TRICKY - when running with individual capabilities, this won't run twice but locally or as a complete service it will...
        if (this.started) {
            return
        }
        this.started = true
        await this.pubSub.start()
    }

    public async stop(): Promise<void> {
        await this.pubSub.stop()
    }

    public async getHogFunctionsForTeams(
        teamIds: Team['id'][],
        types: HogFunctionTypeType[]
    ): Promise<Record<Team['id'], HogFunctionType[]>> {
        const result = teamIds.reduce<Record<Team['id'], HogFunctionType[]>>((acc, teamId) => {
            acc[teamId] = []
            return acc
        }, {})

        const teamHogFunctions = await this.lazyLoaderByTeam.getMany(teamIds.map((x) => x.toString()))

        if (!teamHogFunctions) {
            return result
        }

        const hogFunctionIds = Object.values(teamHogFunctions).flatMap(
            (teamFns) => teamFns?.filter((fn) => types.includes(fn.type)).map((fn) => fn.id) ?? []
        )
        const hogFunctions = await this.lazyLoader.getMany(hogFunctionIds)

        for (const fn of Object.values(hogFunctions)) {
            if (!fn) {
                continue
            }
            result[fn.team_id] = result[fn.team_id] ?? []
            result[fn.team_id].push(fn)
        }

        for (const [teamId, fns] of Object.entries(result)) {
            result[parseInt(teamId)] = sortHogFunctions(fns)
        }

        return result
    }

    public async getHogFunctionsForTeam(teamId: Team['id'], types: HogFunctionTypeType[]): Promise<HogFunctionType[]> {
        return (await this.getHogFunctionsForTeams([teamId], types))[teamId] ?? []
    }

    public async getHogFunction(id: HogFunctionType['id']): Promise<HogFunctionType | null> {
        return (await this.lazyLoader.get(id)) ?? null
    }

    public async getHogFunctions(
        ids: HogFunctionType['id'][]
    ): Promise<Record<HogFunctionType['id'], HogFunctionType | null>> {
        return await this.lazyLoader.getMany(ids)
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

    private onHogFunctionsReloaded(teamId: Team['id'], hogFunctionIds: HogFunctionType['id'][]) {
        this.lazyLoaderByTeam.markForRefresh(teamId.toString())
        this.lazyLoader.markForRefresh(hogFunctionIds)
    }

    private onIntegrationsReloaded(integrationIds: IntegrationType['id'][]) {
        const hogFunctionsRequiringRefresh = Object.values(this.lazyLoader.cache).filter((hogFunction) => {
            for (const integrationId of integrationIds) {
                if (hogFunction?.depends_on_integration_ids?.has(integrationId)) {
                    return true
                }
            }
            return false
        })

        this.lazyLoader.markForRefresh(
            hogFunctionsRequiringRefresh.filter((x) => !!x).map((hogFunction) => hogFunction!.id)
        )
    }

    private async fetchTeamHogFunctions(teamIds: string[]): Promise<Record<string, HogFunctionTeamInfo[]>> {
        logger.info('[HogFunctionManager]', 'Fetching team hog functions', { teamIds })
        const response = await this.hub.postgres.query<Pick<HogFunctionType, 'id' | 'team_id' | 'type'>>(
            PostgresUse.COMMON_READ,
            `SELECT id, team_id, type FROM posthog_hogfunction WHERE enabled = TRUE AND deleted = FALSE AND team_id = ANY($1)`,
            [teamIds],
            'fetchAllTeamHogFunctions'
        )

        const hogFunctionsByTeam: Record<string, HogFunctionTeamInfo[]> = {}

        for (const item of response.rows) {
            const teamId = item.team_id.toString()
            if (!hogFunctionsByTeam[teamId]) {
                hogFunctionsByTeam[teamId] = []
            }
            hogFunctionsByTeam[teamId].push(item)
        }

        return hogFunctionsByTeam
    }

    private async fetchHogFunctions(ids: string[]): Promise<Record<string, HogFunctionType | undefined>> {
        logger.info('[HogFunctionManager]', 'Fetching hog functions', { ids })

        const response = await this.hub.postgres.query<HogFunctionType>(
            PostgresUse.COMMON_READ,
            `SELECT ${HOG_FUNCTION_FIELDS.join(', ')} FROM posthog_hogfunction WHERE id = ANY($1)`,
            [ids],
            'fetchHogFunctions'
        )

        const hogFunctions = response.rows

        this.sanitize(hogFunctions)
        await this.enrichWithIntegrations(hogFunctions)

        return hogFunctions.reduce<Record<string, HogFunctionType | undefined>>((acc, hogFunction) => {
            acc[hogFunction.id] = hogFunction
            return acc
        }, {})
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
                        item.encrypted_inputs = parseJSON(decrypted)
                    }
                } catch (error) {
                    if (encryptedInputs) {
                        logger.warn(
                            '[HogFunctionManager]',
                            'Could not parse encrypted inputs - preserving original value',
                            {
                                error: error instanceof Error ? error.message : 'Unknown error',
                            }
                        )
                        captureException(error)
                    }
                }
            }
            // For any other case (null, undefined, unexpected types), leave as-is
        })
    }

    public async enrichWithIntegrations(items: HogFunctionType[]): Promise<void> {
        logger.info('[HogFunctionManager]', 'Enriching with integrations', { functionCount: items.length })
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
            logger.info('[HogFunctionManager]', 'No integrations to enrich with')
            return
        }

        logger.info('[HogFunctionManager]', 'Fetching integrations', { ids: integrationIds })

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

        logger.info('[HogFunctionManager]', 'Decrypting integrations', { integrationCount: integrations.length })

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
        logger.info('[HogFunctionManager]', 'Enriching hog functions', { functionCount: items.length })

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
        logger.info('[HogFunctionManager]', 'Enriched hog functions', {
            functionCount: items.length,
            updatedValuesCount,
        })
    }
}
