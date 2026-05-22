import { MaterializedColumnSlot } from '../types'
import { PostgresRouter, PostgresUse } from './db/postgres'
import { LazyLoader } from './lazy-loader'

/**
 * Cache TTL for a team's dmat slot config. Lives here rather than in the general-purpose
 * LazyLoader because it's calibrated against the dmat backfill workflow: the workflow waits
 * `cache_refresh_wait_seconds` (180s) after publishing a slot assignment before submitting the
 * historical mutation, so ingestion must start populating dmat columns within that window.
 * Worst-case refresh (age + jitter = 150s) stays below 180s.
 */
export const MATERIALIZED_COLUMN_SLOT_REFRESH_AGE_MS = 2 * 60 * 1000 // 2 minutes
export const MATERIALIZED_COLUMN_SLOT_REFRESH_JITTER_MS = 30 * 1000 // 30 seconds

/**
 * Loads each team's dmat slot config for ingestion. Only READY / BACKFILL slots with a
 * non-null `slot_index` are loaded.
 *
 * The whole feature is gated by `INGESTION_DMAT_COLUMN_WRITES_ENABLED`. When disabled this
 * manager short-circuits to "no slots" without touching Postgres, so the prefetch and extract
 * steps become no-ops. The flag is a coarse fleet-wide lever, not a routine toggle: re-enabling
 * after a disable leaves a gap that the historical backfill mutation must fill. Per-team rollout
 * is driven by the slot config in Postgres (transition slots to PENDING with `slot_index = NULL`
 * to stop populating a single team), not by this flag.
 */
export class MaterializedColumnSlotManager {
    private lazyLoader: LazyLoader<MaterializedColumnSlot[]>

    constructor(
        private postgres: PostgresRouter,
        private enabled: boolean
    ) {
        this.lazyLoader = new LazyLoader({
            name: 'MaterializedColumnSlotManager',
            refreshAgeMs: MATERIALIZED_COLUMN_SLOT_REFRESH_AGE_MS,
            refreshJitterMs: MATERIALIZED_COLUMN_SLOT_REFRESH_JITTER_MS,
            loader: async (teamIds: string[]) => {
                return await this.fetchSlots(teamIds)
            },
        })
    }

    /**
     * Returns the team's configured slots, or `[]` when the team has none configured or the
     * feature is disabled.
     *
     * A Postgres load failure PROPAGATES — same as `TeamManager.getTeam`. dmat slot config is
     * essential per-team config, not an optimization: once a slot is READY, HogQL reads the
     * column with no JSON fallback, so silently emitting an event missing its dmat column would
     * corrupt reads for that team. Failing closed lets the batch retry (absorbing transient
     * Postgres blips) and DLQs only on a persistent failure, rather than writing a NULL the
     * reader trusts.
     */
    public async getSlots(teamId: number): Promise<MaterializedColumnSlot[]> {
        if (!this.enabled) {
            return []
        }
        return (await this.lazyLoader.get(String(teamId))) ?? []
    }

    /**
     * Batched variant used by the prefetch step to warm the cache for a whole batch. Errors
     * propagate; the prefetch step treats a failure as a best-effort warm miss, and the per-event
     * `getSlots` re-attempts the load and fails closed if it still can't read the config.
     */
    public async getSlotsForTeams(teamIds: number[]): Promise<Record<string, MaterializedColumnSlot[]>> {
        if (!this.enabled || teamIds.length === 0) {
            return {}
        }
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
        }>(
            PostgresUse.COMMON_READ,
            `SELECT
                s.team_id,
                pd.name AS property_name,
                s.slot_index,
                s.state
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
            })
        }

        // Map every requested team to `null` when it has no slots, so LazyLoader negatively
        // caches it instead of re-querying for slot-less teams (the common case) on every event.
        const result: Record<string, MaterializedColumnSlot[] | null> = {}
        for (const id of teamIds) {
            result[id] = slotsByTeam[id] ?? null
        }

        return result
    }
}
