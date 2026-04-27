import { MaterializedColumnSlot } from '../types'
import { PostgresRouter, PostgresUse } from './db/postgres'
import { LazyLoader, TEAM_AND_SLOTS_REFRESH_AGE_MS, TEAM_AND_SLOTS_REFRESH_JITTER_MS } from './lazy-loader'

/**
 * Loads each team's dmat (dynamic materialized column) slot configuration so the
 * ingestion pipeline can populate `dmat_<type>_<index>` columns alongside each event.
 *
 * Cache TTL matches `TeamManager` (2min ± 30s) so that when an operator changes a slot,
 * every plugin-server instance picks up the change within ~2.5 min. The dmat Temporal
 * workflow waits 3 min between transitioning slots to BACKFILL and submitting the
 * historical mutation, so by the time the mutation runs every ingester is already
 * writing to the new column.
 *
 * Only slots in BACKFILL or READY state with a non-null `slot_index` are loaded — PENDING
 * slots have not been packed into a column yet, and ERROR slots are quiesced until
 * an operator transitions them back to PENDING for retry.
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

    /**
     * Batched variant — used by the prefetch step to warm the cache for an entire
     * batch of events before per-event lookups happen.
     */
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

        // We JOIN posthog_propertydefinition because the slot table only stores the FK —
        // property_name lives on the definition row. The JOIN is per-team-per-refresh
        // (covered by the team-id index on slots and the PK on prop defs) and the result
        // is small (≤ 5 rows per team), so the cost is negligible.
        const queryResult = await this.postgres.query<{
            team_id: number
            property_name: string
            slot_index: number
            property_type: 'String' | 'Numeric' | 'Boolean' | 'DateTime'
            state: 'READY' | 'BACKFILL'
            compaction_target_slot_index: number | null
        }>(
            PostgresUse.COMMON_READ,
            `SELECT
                s.team_id,
                pd.name AS property_name,
                s.slot_index,
                s.property_type,
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
                property_type: row.property_type,
                state: row.state,
                compaction_target_slot_index: row.compaction_target_slot_index,
            })
        }

        // LazyLoader uses null vs [] to distinguish "team not loaded yet" vs "team has zero slots".
        const result: Record<string, MaterializedColumnSlot[] | null> = {}
        for (const id of teamIds) {
            result[id] = slotsByTeam[id] ?? null
        }

        return result
    }
}
