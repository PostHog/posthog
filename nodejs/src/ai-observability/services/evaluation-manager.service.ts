import { PostgresRouter, PostgresUse } from '~/common/utils/db/postgres'
import { LazyLoader } from '~/common/utils/lazy-loader'
import { logger } from '~/common/utils/logger'
import { PubSub } from '~/common/utils/pubsub'

import { Team } from '../../types'
import { Evaluation, EvaluationInfo } from '../types'

const EVALUATION_FIELDS = [
    'e.id',
    'e.team_id',
    'e.name',
    'e.enabled',
    'e.status',
    'e.status_reason',
    'e.evaluation_type',
    'e.evaluation_config',
    'e.output_type',
    'e.output_config',
    'e.conditions',
    'e.target',
    'e.target_config',
    'e.created_at',
    'e.updated_at',
]

export class EvaluationManagerService {
    private lazyLoader: LazyLoader<Evaluation>
    private lazyLoaderByTeam: LazyLoader<EvaluationInfo[]>

    constructor(
        private postgres: PostgresRouter,
        private pubSub: PubSub
    ) {
        this.lazyLoaderByTeam = new LazyLoader({
            name: 'evaluation_manager_by_team',
            loader: async (teamIds) => await this.fetchTeamEvaluations(teamIds),
        })

        this.lazyLoader = new LazyLoader({
            name: 'evaluation_manager',
            loader: async (ids) => await this.fetchEvaluations(ids),
        })

        this.pubSub.on<{ teamId: Team['id']; evaluationIds: Evaluation['id'][] }>(
            'reload-evaluations',
            ({ teamId, evaluationIds }) => {
                logger.debug('⚡', '[PubSub] Reloading evaluations!', { teamId, evaluationIds })
                this.onEvaluationsReloaded(teamId, evaluationIds)
            }
        )
    }

    public async getEvaluationsForTeam(teamId: Team['id']): Promise<Evaluation[]> {
        return (await this.getEvaluationsForTeams([teamId]))[teamId] ?? []
    }

    public async getEvaluationsForTeams(teamIds: Team['id'][]): Promise<Record<Team['id'], Evaluation[]>> {
        const result = teamIds.reduce<Record<Team['id'], Evaluation[]>>((acc, teamId) => {
            acc[teamId] = []
            return acc
        }, {})

        const teamEvaluationIds = await this.getEvaluationIdsForTeams(teamIds)
        const allEvaluationIds = Object.values(teamEvaluationIds).flat()
        const evaluations = await this.lazyLoader.getMany(allEvaluationIds)

        for (const evaluation of Object.values(evaluations)) {
            if (!evaluation) {
                continue
            }
            result[evaluation.team_id] = result[evaluation.team_id] ?? []
            result[evaluation.team_id].push(evaluation)
        }

        return result
    }

    public async getEvaluationIdsForTeams(teamIds: Team['id'][]): Promise<Record<Team['id'], string[]>> {
        const result = teamIds.reduce<Record<Team['id'], string[]>>((acc, teamId) => {
            acc[teamId] = []
            return acc
        }, {})

        const teamEvaluations = await this.lazyLoaderByTeam.getMany(teamIds.map((x) => x.toString()))

        if (!teamEvaluations) {
            return result
        }

        Object.entries(teamEvaluations).forEach(([teamId, teamEvals]) => {
            if (teamEvals) {
                result[parseInt(teamId)] = teamEvals.map((evaluation) => evaluation.id)
            }
        })

        return result
    }

    public async getEvaluation(id: Evaluation['id']): Promise<Evaluation | null> {
        return (await this.lazyLoader.get(id)) ?? null
    }

    private onEvaluationsReloaded(teamId: Team['id'], evaluationIds: Evaluation['id'][]): void {
        this.lazyLoaderByTeam.markForRefresh(teamId.toString())
        this.lazyLoader.markForRefresh(evaluationIds)
    }

    private async fetchTeamEvaluations(teamIds: string[]): Promise<Record<string, EvaluationInfo[]>> {
        logger.debug('[EvaluationManager]', 'Fetching team evaluations', { teamIds })
        const response = await this.postgres.query<EvaluationInfo>(
            PostgresUse.COMMON_READ,
            `SELECT id, team_id FROM llm_analytics_evaluation WHERE enabled = TRUE AND deleted = FALSE AND team_id = ANY($1)`,
            [teamIds],
            'fetchAllTeamEvaluations'
        )

        const evaluationsByTeam: Record<string, EvaluationInfo[]> = {}

        for (const item of response.rows) {
            const teamId = item.team_id.toString()
            if (!evaluationsByTeam[teamId]) {
                evaluationsByTeam[teamId] = []
            }
            evaluationsByTeam[teamId].push(item)
        }

        return evaluationsByTeam
    }

    private async fetchEvaluations(ids: string[]): Promise<Record<string, Evaluation | undefined>> {
        logger.debug('[EvaluationManager]', 'Fetching evaluations', { ids })

        const response = await this.postgres.query<Evaluation>(
            PostgresUse.COMMON_READ,
            `SELECT ${EVALUATION_FIELDS.join(', ')}, mc.provider_key_id::text AS provider_key_id
             FROM llm_analytics_evaluation e
             LEFT JOIN llm_analytics_llmmodelconfiguration mc ON e.model_configuration_id = mc.id
             WHERE e.id = ANY($1)`,
            [ids],
            'fetchEvaluations'
        )

        const evaluations = response.rows

        return evaluations.reduce<Record<string, Evaluation | undefined>>((acc, evaluation) => {
            acc[evaluation.id] = evaluation
            return acc
        }, {})
    }
}
