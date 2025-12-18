import { PostgresRouter, PostgresUse } from './db/postgres'
import { LazyLoader } from './lazy-loader'
import { logger } from './logger'

/**
 * Type of filter for realtime cohort evaluation.
 *
 * - 'behavioral': Event-based filters that require processing event streams (e.g., "performed pageview")
 * - 'person_property': Person property filters evaluated against person state (e.g., "email is set")
 */
export type FilterType = 'behavioral' | 'person_property'

export interface RealtimeSupportedFilter {
    conditionHash: string // The 16-char SHA256 hash from the filter
    bytecode: any // HogQL bytecode for execution
    team_id: number
    cohort_id: number // For tracking which cohort this filter belongs to
    filter_type: FilterType // 'behavioral' for event filters, 'person_property' for person filters
}

export interface RealtimeSupportedFiltersByType {
    behavioral: RealtimeSupportedFilter[]
    person_property: RealtimeSupportedFilter[]
}

interface CohortRow {
    cohort_id: number
    team_id: number
    filters: any | null // JSON object (PostgreSQL deserializes JSON/JSONB columns automatically)
}

export class RealtimeSupportedFilterManagerCDP {
    private lazyLoader: LazyLoader<RealtimeSupportedFiltersByType>

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

    public async getRealtimeSupportedFiltersForTeam(teamId: number): Promise<RealtimeSupportedFiltersByType> {
        const filters = await this.lazyLoader.get(String(teamId))
        if (!filters) {
            return { behavioral: [], person_property: [] }
        }
        return filters
    }

    public async getRealtimeSupportedFiltersForTeams(
        teamIds: number[]
    ): Promise<Record<string, RealtimeSupportedFiltersByType>> {
        const allFilters = await this.lazyLoader.getMany(teamIds.map(String))

        // Ensure all entries have valid filter objects (not null)
        const result: Record<string, RealtimeSupportedFiltersByType> = {}
        for (const [teamId, filters] of Object.entries(allFilters)) {
            result[teamId] = filters || { behavioral: [], person_property: [] }
        }

        return result
    }

    private async fetchRealtimeSupportedFilters(
        teamIds: string[]
    ): Promise<Record<string, RealtimeSupportedFiltersByType>> {
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

        // Initialize result record with empty filter arrays for all requested team IDs
        const resultRecord: Record<string, RealtimeSupportedFiltersByType> = {}
        for (const teamId of teamIds) {
            resultRecord[teamId] = { behavioral: [], person_property: [] }
        }

        // Process filters from each cohort and deduplicate by conditionHash per team
        const seenConditionHashesByTeam = new Map<string, Set<string>>()

        result.rows.forEach((cohortRow) => {
            const teamIdStr = String(cohortRow.team_id)

            if (!resultRecord[teamIdStr]) {
                resultRecord[teamIdStr] = { behavioral: [], person_property: [] }
            }

            if (!seenConditionHashesByTeam.has(teamIdStr)) {
                seenConditionHashesByTeam.set(teamIdStr, new Set<string>())
            }

            const teamSeenHashes = seenConditionHashesByTeam.get(teamIdStr)!
            const filtersJson = cohortRow.filters || {}

            const extracted = this.extractRealtimeFiltersFromFiltersJson(filtersJson, cohortRow, teamSeenHashes)
            resultRecord[teamIdStr].behavioral.push(...extracted.behavioral)
            resultRecord[teamIdStr].person_property.push(...extracted.person_property)
        })

        return resultRecord
    }

    // Extracts realtime-executable filters from a cohort's filters JSON
    private extractRealtimeFiltersFromFiltersJson(
        filtersJson: any,
        cohortRow: CohortRow,
        teamSeenHashes: Set<string>
    ): RealtimeSupportedFiltersByType {
        const collected: RealtimeSupportedFiltersByType = {
            behavioral: [],
            person_property: [],
        }

        const visitLeaf = (node: any) => {
            // Only accept leaf nodes that have inline bytecode and conditionHash
            if (!node || !node.conditionHash || !node.bytecode) {
                return
            }

            // Skip cohort filters (recursive cohort references)
            if (node.type === 'cohort') {
                return
            }

            // Determine filter type based on node type
            let filterType: FilterType
            if (node.type === 'person') {
                filterType = 'person_property'
            } else if (node.type === 'behavioral') {
                filterType = 'behavioral'
            } else {
                logger.warn('Unknown filter type, skipping', {
                    filterType: node.type,
                    conditionHash: node.conditionHash,
                    cohortId: cohortRow.cohort_id,
                })
                return
            }

            const conditionHash = node.conditionHash as string
            if (teamSeenHashes.has(conditionHash)) {
                return
            }
            teamSeenHashes.add(conditionHash)

            const filter: RealtimeSupportedFilter = {
                conditionHash,
                bytecode: node.bytecode,
                team_id: cohortRow.team_id,
                cohort_id: cohortRow.cohort_id,
                filter_type: filterType,
            }

            // Add to the appropriate array based on filter type
            collected[filterType].push(filter)
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
