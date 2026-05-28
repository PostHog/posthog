import { BackgroundRefresher } from '../../../utils/background-refresher'
import { PostgresRouter, PostgresUse } from '../../../utils/db/postgres'
import { logger } from '../../../utils/logger'
import { Manager } from '../service-registry'
import { treeHasConditions } from './evaluate'
import { EventFilterRowSchema, EventFilterRule } from './schema'

/**
 * Per-team event filter cache, backed by a `BackgroundRefresher`.
 * Pure read surface: `getFilter` returns the filter for a team (or null).
 * Lifecycle (constructing the refresher and priming the cache) lives in
 * `EventFilterManagerScope`.
 */
export class EventFilterManager {
    constructor(private readonly refresher: BackgroundRefresher<Map<number, EventFilterRule>>) {}

    /** Returns the filter for a team, or null if disabled or has no conditions. Non-blocking. */
    getFilter(teamId: number): EventFilterRule | null {
        const filter = this.refresher.tryGet()?.get(teamId) ?? null
        if (filter && !treeHasConditions(filter.filter_tree)) {
            return null
        }
        return filter
    }
}

/**
 * Owns the lifecycle of an `EventFilterManager`. Start creates a
 * `BackgroundRefresher` that reloads all active filters every 60s,
 * primes the cache (failures here are logged but don't block start —
 * `tryGet` retries in the background), and hands back a manager that
 * reads from that refresher. Stop is a no-op: dropping the manager and
 * refresher references lets GC reclaim them.
 */
export class EventFilterManagerScope implements Manager<EventFilterManager> {
    constructor(private readonly postgres: PostgresRouter) {}

    async start(): Promise<{ value: EventFilterManager; stop: () => Promise<void> }> {
        const refresher = new BackgroundRefresher(async () => fetchAllFilters(this.postgres), 60_000)
        await refresher.get().catch((error) => {
            logger.error('Failed to initialize event filter config', { error })
        })
        return { value: new EventFilterManager(refresher), stop: () => Promise.resolve() }
    }
}

async function fetchAllFilters(postgres: PostgresRouter): Promise<Map<number, EventFilterRule>> {
    const { rows } = await postgres.query<{
        id: string
        team_id: number
        mode: string
        filter_tree: unknown
    }>(
        PostgresUse.COMMON_READ,
        `SELECT id, team_id, mode, filter_tree
         FROM posthog_eventfilterconfig
         WHERE mode != 'disabled' AND filter_tree IS NOT NULL`,
        [],
        'fetchAllEventFilters'
    )

    const map = new Map<number, EventFilterRule>()
    for (const row of rows) {
        const parsed = EventFilterRowSchema.safeParse(row)
        if (parsed.success) {
            map.set(parsed.data.team_id, parsed.data)
        } else {
            logger.warn('Skipping invalid event filter config', {
                team_id: row.team_id,
                id: row.id,
                error: parsed.error.message,
            })
        }
    }

    logger.debug('🔁 event_filter_manager - refreshed filters', { teamCount: map.size })
    return map
}
