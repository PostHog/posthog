import { Team } from '../../types'
import { PostgresRouter, PostgresUse } from '../../utils/db/postgres'
import { LazyLoader } from '../../utils/lazy-loader'
import { logger } from '../../utils/logger'
import { PubSub } from '../../utils/pubsub'
import { Tagger, TaggerInfo } from '../types'

const TAGGER_FIELDS = ['id', 'team_id', 'name', 'enabled', 'tagger_config', 'conditions', 'created_at', 'updated_at']

export class TaggerManagerService {
    private lazyLoader: LazyLoader<Tagger>
    private lazyLoaderByTeam: LazyLoader<TaggerInfo[]>

    constructor(
        private postgres: PostgresRouter,
        private pubSub: PubSub
    ) {
        this.lazyLoaderByTeam = new LazyLoader({
            name: 'tagger_manager_by_team',
            loader: async (teamIds) => await this.fetchTeamTaggers(teamIds),
        })

        this.lazyLoader = new LazyLoader({
            name: 'tagger_manager',
            loader: async (ids) => await this.fetchTaggers(ids),
        })

        this.pubSub.on<{ teamId: Team['id']; taggerIds: Tagger['id'][] }>('reload-taggers', ({ teamId, taggerIds }) => {
            logger.debug('⚡', '[PubSub] Reloading taggers!', { teamId, taggerIds })
            this.onTaggersReloaded(teamId, taggerIds)
        })
    }

    public async getTaggersForTeam(teamId: Team['id']): Promise<Tagger[]> {
        return (await this.getTaggersForTeams([teamId]))[teamId] ?? []
    }

    public async getTaggersForTeams(teamIds: Team['id'][]): Promise<Record<Team['id'], Tagger[]>> {
        const result = teamIds.reduce<Record<Team['id'], Tagger[]>>((acc, teamId) => {
            acc[teamId] = []
            return acc
        }, {})

        const teamTaggerIds = await this.getTaggerIdsForTeams(teamIds)
        const allTaggerIds = Object.values(teamTaggerIds).flat()
        const taggers = await this.lazyLoader.getMany(allTaggerIds)

        for (const tagger of Object.values(taggers)) {
            if (!tagger) {
                continue
            }
            result[tagger.team_id] = result[tagger.team_id] ?? []
            result[tagger.team_id].push(tagger)
        }

        return result
    }

    public async getTaggerIdsForTeams(teamIds: Team['id'][]): Promise<Record<Team['id'], string[]>> {
        const result = teamIds.reduce<Record<Team['id'], string[]>>((acc, teamId) => {
            acc[teamId] = []
            return acc
        }, {})

        const teamTaggers = await this.lazyLoaderByTeam.getMany(teamIds.map((x) => x.toString()))

        if (!teamTaggers) {
            return result
        }

        Object.entries(teamTaggers).forEach(([teamId, teamTags]) => {
            if (teamTags) {
                result[parseInt(teamId)] = teamTags.map((tagger) => tagger.id)
            }
        })

        return result
    }

    public async getTagger(id: Tagger['id']): Promise<Tagger | null> {
        return (await this.lazyLoader.get(id)) ?? null
    }

    private onTaggersReloaded(teamId: Team['id'], taggerIds: Tagger['id'][]): void {
        this.lazyLoaderByTeam.markForRefresh(teamId.toString())
        this.lazyLoader.markForRefresh(taggerIds)
    }

    private async fetchTeamTaggers(teamIds: string[]): Promise<Record<string, TaggerInfo[]>> {
        logger.debug('[TaggerManager]', 'Fetching team taggers', { teamIds })
        const response = await this.postgres.query<TaggerInfo>(
            PostgresUse.COMMON_READ,
            `SELECT id, team_id FROM llm_analytics_tagger WHERE enabled = TRUE AND deleted = FALSE AND team_id = ANY($1)`,
            [teamIds],
            'fetchAllTeamTaggers'
        )

        const taggersByTeam: Record<string, TaggerInfo[]> = {}

        for (const item of response.rows) {
            const teamId = item.team_id.toString()
            if (!taggersByTeam[teamId]) {
                taggersByTeam[teamId] = []
            }
            taggersByTeam[teamId].push(item)
        }

        return taggersByTeam
    }

    private async fetchTaggers(ids: string[]): Promise<Record<string, Tagger | undefined>> {
        logger.debug('[TaggerManager]', 'Fetching taggers', { ids })

        // Filter deleted and disabled rows even though team-level discovery already
        // filters — taggers can be soft-deleted or disabled between discovery and
        // detail fetch, and we don't want to dispatch a run-tagger workflow for one.
        const response = await this.postgres.query<Tagger>(
            PostgresUse.COMMON_READ,
            `SELECT ${TAGGER_FIELDS.join(', ')} FROM llm_analytics_tagger WHERE id = ANY($1) AND deleted = FALSE AND enabled = TRUE`,
            [ids],
            'fetchTaggers'
        )

        const taggers = response.rows

        return taggers.reduce<Record<string, Tagger | undefined>>((acc, tagger) => {
            acc[tagger.id] = tagger
            return acc
        }, {})
    }
}
