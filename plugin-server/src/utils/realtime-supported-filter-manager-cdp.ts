import { PostgresRouter, PostgresUse } from './db/postgres'
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

            const teamSeenHashes = seenConditionHashesByTeam.get(teamIdStr)!
            const filtersJson = cohortRow.filters || {}

            const extracted = this.extractRealtimeFiltersFromFiltersJson(filtersJson, cohortRow, teamSeenHashes)
            if (extracted.length > 0) {
                resultRecord[teamIdStr].push(...extracted)
            }
        })

        return resultRecord
    }

    // Extracts realtime-executable filters from a cohort's filters JSON
    private extractRealtimeFiltersFromFiltersJson(
        filtersJson: any,
        cohortRow: CohortRow,
        teamSeenHashes: Set<string>
    ): RealtimeSupportedFilter[] {
        const collected: RealtimeSupportedFilter[] = []

        const visitLeaf = (node: any) => {
            // Only accept leaf nodes that have inline bytecode and conditionHash
            if (!node || !node.conditionHash || !node.bytecode) {
                return
            }

            // Only accept event filters - skip person and cohort filters
            // Note: 'behavioral' filters are event-related and should pass through
            if (node.type === 'person' || node.type === 'cohort') {
                return
            }

            const conditionHash = node.conditionHash as string
            if (teamSeenHashes.has(conditionHash)) {
                return
            }
            teamSeenHashes.add(conditionHash)

            collected.push({
                conditionHash,
                bytecode: node.bytecode,
                team_id: cohortRow.team_id,
                cohort_id: cohortRow.cohort_id,
            })
        }

        if (filtersJson && filtersJson.properties) {
            this.traverseFilterTree(filtersJson.properties, visitLeaf)
        }

        return collected
    }

    // Generic DFS over the filter tree; calls visit on every leaf node
    private traverseFilterTree(node: any, visit: (leaf: any) => void): void {
        if (!node) {
            return
        }
        const isGroup = node.type === 'OR' || node.type === 'AND'
        if (isGroup) {
            if (Array.isArray(node.values)) {
                for (const child of node.values) {
                    this.traverseFilterTree(child, visit)
                }
            }
            return
        }
        visit(node)
    }
}
