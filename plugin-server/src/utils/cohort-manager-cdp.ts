import { Cohort } from '../types'
import { PostgresRouter, PostgresUse } from './db/postgres'
import { LazyLoader } from './lazy-loader'

export class CohortManagerCDP {
    private lazyLoader: LazyLoader<Cohort[]>

    constructor(private postgres: PostgresRouter) {
        this.lazyLoader = new LazyLoader({
            name: 'CohortManagerCDP',
            refreshAge: 5 * 60 * 1000, // 5 minutes
            refreshJitterMs: 60 * 1000, // 1 minute
            loader: async (teamIds: string[]) => {
                return await this.fetchCohorts(teamIds)
            },
        })
    }

    public async getCohortsForTeam(teamId: number): Promise<Cohort[]> {
        const cohorts = await this.lazyLoader.get(String(teamId))
        return cohorts || []
    }

    public async getCohortsForTeams(teamIds: number[]): Promise<Record<string, Cohort[] | null>> {
        return this.lazyLoader.getMany(teamIds.map(String))
    }

    private async fetchCohorts(teamIds: string[]): Promise<Record<string, Cohort[]>> {
        const teamIdNumbers = teamIds.map(Number).filter((id) => !isNaN(id))

        if (teamIdNumbers.length === 0) {
            return {}
        }

        const result = await this.postgres.query<Cohort>(
            PostgresUse.COMMON_READ,
            `SELECT
                id,
                name,
                description,
                deleted,
                groups,
                team_id,
                created_at,
                created_by_id,
                is_calculating,
                last_calculation,
                errors_calculating,
                is_static,
                version,
                pending_version,
                bytecode,
                bytecode_error
            FROM posthog_cohort
            WHERE team_id = ANY($1) AND deleted = FALSE
            AND bytecode IS NOT NULL AND bytecode_error IS NULL
            ORDER BY team_id, id DESC
            `,
            [teamIdNumbers],
            'fetch-cohorts-by-team'
        )

        // Initialize result record with empty arrays for all requested team IDs
        const resultRecord: Record<string, Cohort[]> = {}
        for (const teamId of teamIds) {
            resultRecord[teamId] = []
        }

        // Group cohorts by team_id
        result.rows.forEach((cohort) => {
            const teamIdStr = String(cohort.team_id)
            if (!resultRecord[teamIdStr]) {
                resultRecord[teamIdStr] = []
            }
            resultRecord[teamIdStr].push(cohort)
        })

        return resultRecord
    }
}
