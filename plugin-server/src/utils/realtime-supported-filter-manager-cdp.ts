import { PostgresRouter, PostgresUse } from './db/postgres'
import { LazyLoader } from './lazy-loader'

export interface RealtimeSupportedFilter {
    conditionHash: string // The 16-char SHA256 hash from the filter
    bytecode: any // HogQL bytecode for execution
    team_id: number
    cohort_id: number // For tracking which cohort this filter belongs to
    filter_path: string // e.g., "properties.values[0]"
}

interface CohortRow {
    cohort_id: number
    team_id: number
    compiled_bytecode: any
}

export class RealtimeSupportedFilterManagerCDP {
    private lazyLoader: LazyLoader<RealtimeSupportedFilter[]>

    constructor(private postgres: PostgresRouter) {
        this.lazyLoader = new LazyLoader({
            name: 'RealtimeSupportedFilterManagerCDP',
            refreshAgeMs: 5 * 60 * 1000, // 5 minutes
            refreshJitterMs: 60 * 1000, // 1 minute
            loader: async (teamIds: string[]) => {
                return await this.fetchRealtimeSupportedFilters(teamIds)
            },
        })
    }

    public async getRealtimeSupportedFiltersForTeam(teamId: number): Promise<RealtimeSupportedFilter[]> {
        const filters = await this.lazyLoader.get(String(teamId))
        return filters || []
    }

    public async getRealtimeSupportedFiltersForTeams(
        teamIds: number[]
    ): Promise<Record<string, RealtimeSupportedFilter[] | null>> {
        return this.lazyLoader.getMany(teamIds.map(String))
    }

    private async fetchRealtimeSupportedFilters(teamIds: string[]): Promise<Record<string, RealtimeSupportedFilter[]>> {
        const teamIdNumbers = teamIds.map(Number).filter((id) => !isNaN(id))

        if (teamIdNumbers.length === 0) {
            return {}
        }

        const result = await this.postgres.query<CohortRow>(
            PostgresUse.COMMON_READ,
            `SELECT 
                id as cohort_id,
                team_id,
                compiled_bytecode
            FROM posthog_cohort 
            WHERE team_id = ANY($1) 
              AND deleted = FALSE 
              AND compiled_bytecode IS NOT NULL
              AND cohort_type = 'realtime'
            ORDER BY team_id, created_at DESC`,
            [teamIdNumbers],
            'fetch-realtime-supported-filters-by-team'
        )

        // Initialize result record with empty arrays for all requested team IDs
        const resultRecord: Record<string, RealtimeSupportedFilter[]> = {}
        for (const teamId of teamIds) {
            resultRecord[teamId] = []
        }

        // Process compiled_bytecode from each cohort and deduplicate by conditionHash per team
        const seenConditionHashesByTeam = new Map<string, Set<string>>()

        result.rows.forEach((cohortRow) => {
            const teamIdStr = String(cohortRow.team_id)

            if (!resultRecord[teamIdStr]) {
                resultRecord[teamIdStr] = []
            }

            if (!seenConditionHashesByTeam.has(teamIdStr)) {
                seenConditionHashesByTeam.set(teamIdStr, new Set<string>())
            }

            // Parse compiled_bytecode JSON array
            let compiledBytecode: any[]
            try {
                compiledBytecode = Array.isArray(cohortRow.compiled_bytecode)
                    ? cohortRow.compiled_bytecode
                    : JSON.parse(cohortRow.compiled_bytecode || '[]')
            } catch (error) {
                console.warn(`Failed to parse compiled_bytecode for cohort ${cohortRow.cohort_id}:`, error)
                return
            }

            const teamSeenHashes = seenConditionHashesByTeam.get(teamIdStr)!

            // Extract filters from compiled_bytecode array
            compiledBytecode.forEach((bytecodeEntry) => {
                if (!bytecodeEntry?.conditionHash || !bytecodeEntry?.bytecode || !bytecodeEntry?.filter_path) {
                    return // Skip invalid entries
                }

                const conditionHash = bytecodeEntry.conditionHash

                // Deduplicate: only add if we haven't seen this conditionHash for this team before
                if (!teamSeenHashes.has(conditionHash)) {
                    teamSeenHashes.add(conditionHash)

                    const filter: RealtimeSupportedFilter = {
                        conditionHash,
                        bytecode: bytecodeEntry.bytecode,
                        team_id: cohortRow.team_id,
                        cohort_id: cohortRow.cohort_id,
                        filter_path: bytecodeEntry.filter_path,
                    }

                    resultRecord[teamIdStr].push(filter)
                }
            })
        })

        return resultRecord
    }
}
