import { Hub, Team } from '../../../types'
import { PostgresUse } from '../../../utils/db/postgres'
import { parseJSON } from '../../../utils/json-parse'
import { LazyLoader } from '../../../utils/lazy-loader'
import { logger } from '../../../utils/logger'
import { captureException } from '../../../utils/posthog'
import { HogFunctionType, HogFunctionTypeType } from '../../types'

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

    constructor(private hub: Hub) {
        this.lazyLoaderByTeam = new LazyLoader({
            name: 'hog_function_manager_by_team',
            loader: async (teamIds) => await this.fetchTeamHogFunctions(teamIds),
        })

        this.lazyLoader = new LazyLoader({
            name: 'hog_function_manager',
            loader: async (ids) => await this.fetchHogFunctions(ids),
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
        types: HogFunctionTypeType[],
        /** Optional way to pre-filter hog functions before returning them */
        filterFn?: (hogFunction: HogFunctionType) => boolean
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
            if (filterFn && !filterFn(fn)) {
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
        return items[0] ?? null
    }

    private onHogFunctionsReloaded(teamId: Team['id'], hogFunctionIds: HogFunctionType['id'][]): void {
        this.lazyLoaderByTeam.markForRefresh(teamId.toString())
        this.lazyLoader.markForRefresh(hogFunctionIds)
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

        return hogFunctions.reduce<Record<string, HogFunctionType | undefined>>((acc, hogFunction) => {
            acc[hogFunction.id] = hogFunction
            return acc
        }, {})
    }

    public sanitize(items: HogFunctionType[]): void {
        items.forEach((item) => {
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
}
