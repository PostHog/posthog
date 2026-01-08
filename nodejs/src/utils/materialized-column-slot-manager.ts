import { MaterializedColumnSlot } from '../types'
import { PostgresRouter, PostgresUse } from './db/postgres'
import { LazyLoader } from './lazy-loader'

/**
 * Manages materialized column slot assignments for teams.
 *
 * Uses the same TTL as TeamManager (2 minutes + 30s jitter) to ensure
 * consistent cache behavior across the ingestion pipeline.
 */
export class MaterializedColumnSlotManager {
    private lazyLoader: LazyLoader<MaterializedColumnSlot[]>

    constructor(private postgres: PostgresRouter) {
        this.lazyLoader = new LazyLoader({
            name: 'MaterializedColumnSlotManager',
            // IMPORTANT: If you change these values, update posthog/temporal/eav_backfill/workflows.py
            // The workflow waits 3 minutes to account for refreshAgeMs + refreshJitterMs + buffer
            refreshAgeMs: 2 * 60 * 1000, // 2 minutes
            refreshJitterMs: 30 * 1000, // 30 seconds
            loader: async (teamIds: string[]) => {
                return await this.fetchSlots(teamIds)
            },
        })
    }

    /**
     * Get materialized column slots for a team.
     * Returns an empty array if no slots are configured.
     */
    public async getSlots(teamId: number): Promise<MaterializedColumnSlot[]> {
        return (await this.lazyLoader.get(String(teamId))) ?? []
    }

    /**
     * Get materialized column slots for multiple teams.
     */
    public async getSlotsForTeams(teamIds: number[]): Promise<Record<string, MaterializedColumnSlot[]>> {
        const results = await this.lazyLoader.getMany(teamIds.map(String))
        // Convert null values to empty arrays
        const converted: Record<string, MaterializedColumnSlot[]> = {}
        for (const [key, value] of Object.entries(results)) {
            converted[key] = value ?? []
        }
        return converted
    }

    /**
     * Mark slots for a team as needing refresh.
     * Call this after a slot is created, updated, or deleted.
     */
    public markForRefresh(teamId: number): void {
        this.lazyLoader.markForRefresh(String(teamId))
    }

    private async fetchSlots(teamIds: string[]): Promise<Record<string, MaterializedColumnSlot[] | null>> {
        const numericTeamIds = teamIds.map((id) => parseInt(id, 10)).filter((id) => !isNaN(id) && id > 0)

        if (numericTeamIds.length === 0) {
            // Return nulls for all requested IDs
            const result: Record<string, MaterializedColumnSlot[] | null> = {}
            for (const id of teamIds) {
                result[id] = null
            }
            return result
        }

        const queryResult = await this.postgres.query<{
            team_id: number
            property_name: string
            slot_index: number
            property_type: 'String' | 'Numeric' | 'Boolean' | 'DateTime'
            state: 'READY' | 'BACKFILL' | 'ERROR'
            materialization_type: 'dmat' | 'eav'
        }>(
            PostgresUse.COMMON_READ,
            `SELECT
                team_id,
                property_name,
                slot_index,
                property_type,
                state,
                COALESCE(materialization_type, 'dmat') as materialization_type
            FROM posthog_materializedcolumnslot
            WHERE team_id = ANY($1)
                AND state IN ('READY', 'BACKFILL')
            ORDER BY team_id, slot_index`,
            [numericTeamIds],
            'fetch-materialized-column-slots'
        )

        // Group slots by team_id
        const slotsByTeam: Record<string, MaterializedColumnSlot[]> = {}
        for (const row of queryResult.rows) {
            const teamIdStr = String(row.team_id)
            if (!slotsByTeam[teamIdStr]) {
                slotsByTeam[teamIdStr] = []
            }
            slotsByTeam[teamIdStr].push({
                property_name: row.property_name,
                slot_index: row.slot_index,
                property_type: row.property_type,
                state: row.state,
                materialization_type: row.materialization_type,
            })
        }

        // Build result with nulls for teams that weren't found
        const result: Record<string, MaterializedColumnSlot[] | null> = {}
        for (const id of teamIds) {
            result[id] = slotsByTeam[id] ?? null
        }

        return result
    }
}
