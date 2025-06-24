import { HogFlow } from '~/schema/hogflow'
import { Hub, Team } from '~/types'
import { PostgresUse } from '~/utils/db/postgres'
import { parseJSON } from '~/utils/json-parse'
import { LazyLoader } from '~/utils/lazy-loader'
import { logger } from '~/utils/logger'
import { PubSub } from '~/utils/pubsub'

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
    'edges',
    'actions',
    'abort_action',
]

export type HogFlowTeamInfo = Pick<HogFlow, 'id' | 'team_id' | 'version'>

export class HogFlowManagerService {
    private lazyLoader: LazyLoader<HogFlow>
    private lazyLoaderByTeam: LazyLoader<HogFlowTeamInfo[]>
    private started: boolean
    private pubSub: PubSub

    constructor(private hub: Hub) {
        this.started = false

        this.pubSub = new PubSub(this.hub, {
            'reload-hog-flows': (message) => {
                const { teamId, hogFlowIds } = parseJSON(message) as {
                    teamId: Team['id']
                    hogFlowIds: HogFlow['id'][]
                }
                logger.info('⚡', '[PubSub] Reloading hog flows!', { teamId, hogFlowIds })
                this.onHogFlowsReloaded(teamId, hogFlowIds)
            },
        })

        this.lazyLoaderByTeam = new LazyLoader({
            name: 'hog_flow_manager_by_team',
            loader: async (teamIds) => await this.fetchTeamHogFlows(teamIds),
        })

        this.lazyLoader = new LazyLoader({
            name: 'hog_flow_manager',
            loader: async (ids) => await this.fetchHogFlows(ids),
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

    private onHogFlowsReloaded(teamId: Team['id'], hogFlowIds: HogFlow['id'][]) {
        this.lazyLoaderByTeam.markForRefresh(teamId.toString())
        this.lazyLoader.markForRefresh(hogFlowIds)
    }

    private async fetchTeamHogFlows(teamIds: string[]): Promise<Record<string, HogFlowTeamInfo[]>> {
        logger.info('[HogFlowManager]', 'Fetching team hog flows', { teamIds })
        const response = await this.hub.postgres.query<HogFlowTeamInfo>(
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
        logger.info('[HogFlowManager]', 'Fetching hog flows', { ids })

        const response = await this.hub.postgres.query<HogFlow>(
            PostgresUse.COMMON_READ,
            `SELECT ${HOG_FLOW_FIELDS.join(', ')} FROM posthog_hogflow WHERE id = ANY($1)`,
            [ids],
            'fetchHogFlows'
        )

        const items = response.rows

        return items.reduce<Record<string, HogFlow | undefined>>((acc, item) => {
            acc[item.id] = item
            return acc
        }, {})
    }
}
