import { PostgresRouter, PostgresUse } from './db/postgres'
import { parseJSON } from './json-parse'
import { LazyLoader } from './lazy-loader'

export interface RealtimeSupportedFilter {
    conditionHash: string // The 16-char SHA256 hash from the filter
    bytecode: any // HogQL bytecode for execution
    team_id: number
    cohort_id: number // For tracking which cohort this filter belongs to
}

interface CohortRow {
    cohort_id: number
    team_id: number
    filters: any | null // JSON object (PostgreSQL deserializes JSON/JSONB columns automatically)
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
                filters
            FROM posthog_cohort 
            WHERE team_id = ANY($1) 
              AND deleted = FALSE 
              AND filters IS NOT NULL
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

        // Process filters from each cohort and deduplicate by conditionHash per team
        const seenConditionHashesByTeam = new Map<string, Set<string>>()

        result.rows.forEach((cohortRow) => {
            const teamIdStr = String(cohortRow.team_id)

            if (!resultRecord[teamIdStr]) {
                resultRecord[teamIdStr] = []
            }

            if (!seenConditionHashesByTeam.has(teamIdStr)) {
                seenConditionHashesByTeam.set(teamIdStr, new Set<string>())
            }

            // PostgreSQL automatically deserializes JSON/JSONB columns, so filters is already an object
            const filtersJson = cohortRow.filters || {}

            const teamSeenHashes = seenConditionHashesByTeam.get(teamIdStr)!

            // Recursively traverse filter tree to extract inline bytecode from leaf nodes
            const traverse = (node: any) => {
                if (!node) {
                    return
                }

                // If it's a group node (OR/AND), recurse into values
                if (node.type === 'OR' || node.type === 'AND') {
                    if (Array.isArray(node.values)) {
                        node.values.forEach((value: any) => traverse(value))
                    }
                    return
                }

                // It's a leaf filter node - check if it has bytecode
                if (!node.conditionHash || !node.bytecode) {
                    return // Skip nodes without bytecode
                }

                // Skip person property entries explicitly
                if (node.type === 'person') {
                    return
                }

                const conditionHash = node.conditionHash

                // Deduplicate: only add if we haven't seen this conditionHash for this team before
                if (!teamSeenHashes.has(conditionHash)) {
                    teamSeenHashes.add(conditionHash)

                    const filter: RealtimeSupportedFilter = {
                        conditionHash,
                        bytecode: node.bytecode,
                        team_id: cohortRow.team_id,
                        cohort_id: cohortRow.cohort_id,
                    }

                    resultRecord[teamIdStr].push(filter)
                }
            }

            // Start traversal from properties root
            if (filtersJson.properties) {
                traverse(filtersJson.properties)
            }
        })

        return resultRecord
    }
}
