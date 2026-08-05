import { BackgroundRefresher } from '~/common/utils/background-refresher'
import { PostgresRouter, PostgresUse } from '~/common/utils/db/postgres'
import { logger } from '~/common/utils/logger'
import { Component } from '~/ingestion/common/scopes'

import { treeHasConditions } from './evaluate'
import { EventFilterRowSchema, EventFilterRule } from './schema'

/**
 * Manages per-team event filter config loaded from Postgres. One filter
 * per team, cached via a `BackgroundRefresher` that reloads all active
 * filters every 60s. The constructor does not prime the cache; call
 * `prime()` (or wrap construction in `EventFilterManagerComponent`) to
 * await the initial load.
 */
export class EventFilterManager {
    private refresher: BackgroundRefresher<Map<number, EventFilterRule>>

    constructor(private readonly postgres: PostgresRouter) {
        this.refresher = new BackgroundRefresher(async () => this.fetchAllFilters(), 60_000)
    }

    async prime(): Promise<void> {
        // Failures are logged but don't surface — `tryGet` will retry in the
        // background on subsequent reads.
        await this.refresher.get().catch((error) => {
            logger.error('Failed to initialize event filter config', { error })
        })
    }

    /** Returns the filter for a team, or null if disabled or has no conditions. Non-blocking. */
    getFilter(teamId: number): EventFilterRule | null {
        const filter = this.refresher.tryGet()?.get(teamId) ?? null
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

/**
 * Scope entry for `EventFilterManager`. `start()` constructs the manager
 * and awaits the initial cache prime before handing it back. Stop is a
 * no-op — dropping the manager and refresher references lets GC reclaim
 * them.
 */
export class EventFilterManagerComponent implements Component<EventFilterManager> {
    constructor(private readonly postgres: PostgresRouter) {}

    async start(): Promise<{ value: EventFilterManager; stop: () => Promise<void> }> {
        const manager = new EventFilterManager(this.postgres)
        await manager.prime()
        return { value: manager, stop: () => Promise.resolve() }
    }
}
