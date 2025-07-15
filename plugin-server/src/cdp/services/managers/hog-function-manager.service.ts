import { Hub, Team } from '../../../types'
import { PostgresUse } from '../../../utils/db/postgres'
import { parseJSON } from '../../../utils/json-parse'
import { LazyLoader } from '../../../utils/lazy-loader'
import { logger } from '../../../utils/logger'
import { captureException } from '../../../utils/posthog'
import { HOG_FUNCTION_TEMPLATES } from '../../templates'
import { HogFunctionType, HogFunctionTypeType, IntegrationType } from '../../types'

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

const isAddonRequired = (hogFunction: HogFunctionType): boolean => {
    if (typeof hogFunction.is_addon_required === 'boolean') {
        // Don't double check
        return hogFunction.is_addon_required
    }

    if (hogFunction.type !== 'destination') {
        // Only destinations are part of the paid plan
        return false
    }

    // TODO: ensure all free-templates are moved to the templates here
    // FUTURE: When we move templates fully to the DB we should be loading it from there
    const template = HOG_FUNCTION_TEMPLATES.find((t) => t.id === hogFunction.template_id)
    return template?.free !== true
}

export class HogFunctionManagerService {
    private lazyLoader: LazyLoader<HogFunctionType>
    private lazyLoaderByTeam: LazyLoader<HogFunctionTeamInfo[]>

    constructor(private hub: Hub) {
        this.lazyLoaderByTeam = new LazyLoader({
            name: 'hog_function_manager_by_team',
            loader: async (teamIds) => await this.fetchTeamHogFunctions(teamIds),
        })

        this.lazyLoader = new LazyLoader({
            name: 'hog_function_manager',
            loader: async (ids) => await this.fetchHogFunctions(ids),
        })

        this.hub.pubSub.on<{ integrationIds: IntegrationType['id'][] }>('reload-integrations', ({ integrationIds }) => {
            logger.debug('⚡', '[PubSub] Reloading integrations!', { integrationIds })
            this.onIntegrationsReloaded(integrationIds)
        })

        this.hub.pubSub.on<{ teamId: Team['id']; hogFunctionIds: HogFunctionType['id'][] }>(
            'reload-hog-functions',
            ({ teamId, hogFunctionIds }) => {
                logger.debug('⚡', '[PubSub] Reloading hog functions!', { teamId, hogFunctionIds })
                this.onHogFunctionsReloaded(teamId, hogFunctionIds)
            }
        )
    }

    public async getHogFunctionsForTeams(
        teamIds: Team['id'][],
        types: HogFunctionTypeType[]
    ): Promise<Record<Team['id'], HogFunctionType[]>> {
        const result = teamIds.reduce<Record<Team['id'], HogFunctionType[]>>((acc, teamId) => {
            acc[teamId] = []
            return acc
        }, {})

        const teamHogFunctionIds = await this.getHogFunctionIdsForTeams(teamIds, types)
        const allHogFunctionIds = Object.values(teamHogFunctionIds).flat()
        const hogFunctions = await this.lazyLoader.getMany(allHogFunctionIds)

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

    public async getHogFunctionIdsForTeams(
        teamIds: Team['id'][],
        types: HogFunctionTypeType[]
    ): Promise<Record<Team['id'], string[]>> {
        const result = teamIds.reduce<Record<Team['id'], string[]>>((acc, teamId) => {
            acc[teamId] = []
            return acc
        }, {})

        const teamHogFunctions = await this.lazyLoaderByTeam.getMany(teamIds.map((x) => x.toString()))

        if (!teamHogFunctions) {
            return result
        }

        // For each team, filter functions by type and collect their IDs
        Object.entries(teamHogFunctions).forEach(([teamId, teamFns]) => {
            if (teamFns) {
                result[parseInt(teamId)] = teamFns.filter((fn) => types.includes(fn.type)).map((fn) => fn.id)
            }
        })

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
        const hogFunctionsRequiringRefresh = Object.values(this.lazyLoader.getCache()).filter((hogFunction) => {
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
        logger.debug('[HogFunctionManager]', 'Fetching team hog functions', { teamIds })
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
        logger.debug('[HogFunctionManager]', 'Fetching hog functions', { ids })

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
            item.is_addon_required = isAddonRequired(item)

            // Decrypt inputs
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
        logger.debug('[HogFunctionManager]', 'Enriching with integrations', { functionCount: items.length })
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
            logger.debug('[HogFunctionManager]', 'No integrations to enrich with')
            return
        }

        logger.debug('[HogFunctionManager]', 'Fetching integrations', { ids: integrationIds })

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

        logger.debug('[HogFunctionManager]', 'Decrypting integrations', { integrationCount: integrations.length })

        const integrationConfigsByTeamAndId: Record<string, Record<string, any>> = integrations.reduce(
            (acc, integration) => {
                acc[`${integration.team_id}:${integration.id}`] = {
                    ...integration.config,
                    ...this.hub.encryptedFields.decryptObject(integration.sensitive_config || {}, {
                        ignoreDecryptionErrors: true,
                    }),
                    integrationId: integration.id,
                }
                return acc
            },
            {} as Record<string, Record<string, any>>
        )
        logger.debug('[HogFunctionManager]', 'Enriching hog functions', { functionCount: items.length })

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
        logger.debug('[HogFunctionManager]', 'Enriched hog functions', {
            functionCount: items.length,
            updatedValuesCount,
        })
    }
}
