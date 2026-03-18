import { PostgresRouter, PostgresUse } from './db/postgres'
import { LazyLoader } from './lazy-loader'

export interface Action {
    id: number
    name: string
    team_id: number
    deleted: boolean
    bytecode: any
    bytecode_error: string | null
    steps_json: any
    created_at: string
    updated_at: string
}

export class ActionManagerCDP {
    private lazyLoader: LazyLoader<Action[]>

    constructor(private postgres: PostgresRouter) {
        this.lazyLoader = new LazyLoader({
            name: 'ActionManagerCDP',
            refreshAgeMs: 5 * 60 * 1000, // 5 minutes
            refreshJitterMs: 60 * 1000, // 1 minute
            loader: async (teamIds: string[]) => {
                return await this.fetchActions(teamIds)
            },
        })
    }

    public async getActionsForTeam(teamId: number): Promise<Action[]> {
        const actions = await this.lazyLoader.get(String(teamId))
        return actions || []
    }

    public async getActionsForTeams(teamIds: number[]): Promise<Record<string, Action[] | null>> {
        return this.lazyLoader.getMany(teamIds.map(String))
    }

    private async fetchActions(teamIds: string[]): Promise<Record<string, Action[]>> {
        const teamIdNumbers = teamIds.map(Number).filter((id) => !isNaN(id))

        if (teamIdNumbers.length === 0) {
            return {}
        }

        const result = await this.postgres.query<Action>(
            PostgresUse.COMMON_READ,
            `SELECT
                id,
                name,
                team_id,
                deleted,
                bytecode,
                bytecode_error,
                steps_json,
                created_at,
                updated_at
            FROM posthog_action
            WHERE team_id = ANY($1) AND deleted = FALSE
            AND bytecode IS NOT NULL
            ORDER BY team_id, updated_at DESC
            `,
            [teamIdNumbers],
            'fetch-actions-by-team'
        )

        // Initialize result record with empty arrays for all requested team IDs
        const resultRecord: Record<string, Action[]> = {}
        for (const teamId of teamIds) {
            resultRecord[teamId] = []
        }

        // Group actions by team_id
        result.rows.forEach((action) => {
            const teamIdStr = String(action.team_id)
            if (!resultRecord[teamIdStr]) {
                resultRecord[teamIdStr] = []
            }
            resultRecord[teamIdStr].push(action)
        })

        return resultRecord
    }
}
