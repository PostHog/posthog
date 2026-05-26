import { BackgroundRefresher } from '../../../utils/background-refresher'
import { PostgresRouter, PostgresUse } from '../../../utils/db/postgres'
import { logger } from '../../../utils/logger'
import { treeHasConditions } from './evaluate'
import { EventFilterRowSchema, EventFilterRule } from './schema'

/**
 * Manages per-team event filter config loaded from Postgres.
 * One filter per team. Uses BackgroundRefresher to load all active filters
 * (mode = 'dry_run' or 'live').
 */
/**
 * The `EventFilterManager` surface visible to callers that should not have
 * access to its lifecycle methods (e.g. pipeline steps that receive the
 * service from a `Lifecycle`'s stripped service map). Same shape as
 * `EventFilterManager` minus `start`/`stop`.
 */
export type EventFilterManagerHandle = Omit<EventFilterManager, 'start' | 'stop'>

export class EventFilterManager {
    private refresher?: BackgroundRefresher<Map<number, EventFilterRule>>

    constructor(private postgres: PostgresRouter) {}

    public async start(): Promise<void> {
        this.refresher = new BackgroundRefresher(async () => this.fetchAllFilters(), 60_000)
        // Prime the filter cache. Failures are logged but don't block start —
        // `tryGet` will retry in the background on subsequent reads.
        await this.refresher.get().catch((error) => {
            logger.error('Failed to initialize event filter config', { error })
        })
    }

    public stop(): Promise<void> {
        // Drop the refresher. Once the reference is gone, no further
        // refreshes happen and the cache is GC'd. Subsequent `getFilter`
        // calls return null (no filter applied).
        this.refresher = undefined
        return Promise.resolve()
    }

    /** Returns the filter for a team, or null if disabled or has no conditions. Non-blocking. */
    getFilter(teamId: number): EventFilterRule | null {
        const filter = this.refresher?.tryGet()?.get(teamId) ?? null
        if (filter && !treeHasConditions(filter.filter_tree)) {
            return null
        }
        return filter
    }

    private async fetchAllFilters(): Promise<Map<number, EventFilterRule>> {
        const { rows } = await this.postgres.query<{
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
}
