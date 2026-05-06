import { MaterializedColumnSlot } from '../types'
import { PostgresRouter, PostgresUse } from './db/postgres'
import { LazyLoader, TEAM_AND_SLOTS_REFRESH_AGE_MS, TEAM_AND_SLOTS_REFRESH_JITTER_MS } from './lazy-loader'

/**
 * Loads each team's dmat slot config for ingestion. Cache TTL is 2min ± 30s; the workflow's
 * 3-min wait before submitting mutations is calibrated against this.
 *
 * Only READY / BACKFILL slots with a non-null `slot_index` are loaded. To kill dmat
 * ingestion, transition slots to PENDING with `slot_index = NULL` — see `docs/internal/dmat-deployment.md`.
 */
export class MaterializedColumnSlotManager {
    private lazyLoader: LazyLoader<MaterializedColumnSlot[]>

    constructor(private postgres: PostgresRouter) {
        this.lazyLoader = new LazyLoader({
            name: 'MaterializedColumnSlotManager',
            refreshAgeMs: TEAM_AND_SLOTS_REFRESH_AGE_MS,
            refreshJitterMs: TEAM_AND_SLOTS_REFRESH_JITTER_MS,
            loader: async (teamIds: string[]) => {
                return await this.fetchSlots(teamIds)
            },
        })
    }

    /** Returns the team's slot config, or an empty array if none are configured. */
    public async getSlots(teamId: number): Promise<MaterializedColumnSlot[]> {
        return (await this.lazyLoader.get(String(teamId))) ?? []
    }

    /** Batched variant used by the prefetch step to warm the cache for a whole batch. */
    public async getSlotsForTeams(teamIds: number[]): Promise<Record<string, MaterializedColumnSlot[]>> {
        const results = await this.lazyLoader.getMany(teamIds.map(String))
        const converted: Record<string, MaterializedColumnSlot[]> = {}
        for (const [key, value] of Object.entries(results)) {
            converted[key] = value ?? []
        }
        return converted
    }

    private async fetchSlots(teamIds: string[]): Promise<Record<string, MaterializedColumnSlot[] | null>> {
        const numericTeamIds = teamIds.map(Number)

        // property_name lives on posthog_propertydefinition — the slot table only stores the FK.
        const queryResult = await this.postgres.query<{
            team_id: number
            property_name: string
            slot_index: number
            state: 'READY' | 'BACKFILL'
            compaction_target_slot_index: number | null
        }>(
            PostgresUse.COMMON_READ,
            `SELECT
                s.team_id,
                pd.name AS property_name,
                s.slot_index,
                s.state,
                s.compaction_target_slot_index
            FROM posthog_materializedcolumnslot s
            JOIN posthog_propertydefinition pd ON s.property_definition_id = pd.id
            WHERE s.team_id = ANY($1)
                AND s.state IN ('READY', 'BACKFILL')
                AND s.slot_index IS NOT NULL
            ORDER BY s.team_id, s.slot_index`,
            [numericTeamIds],
            'fetch-materialized-column-slots'
        )

        const slotsByTeam: Record<string, MaterializedColumnSlot[]> = {}
        for (const row of queryResult.rows) {
            const teamIdStr = String(row.team_id)
            if (!slotsByTeam[teamIdStr]) {
                slotsByTeam[teamIdStr] = []
            }
            slotsByTeam[teamIdStr].push({
                property_name: row.property_name,
                slot_index: row.slot_index,
                state: row.state,
                compaction_target_slot_index: row.compaction_target_slot_index,
            })
        }

        // null = "team not loaded yet"; [] = "team has zero slots". LazyLoader needs both.
        const result: Record<string, MaterializedColumnSlot[] | null> = {}
        for (const id of teamIds) {
            result[id] = slotsByTeam[id] ?? null
        }

        return result
    }
}
