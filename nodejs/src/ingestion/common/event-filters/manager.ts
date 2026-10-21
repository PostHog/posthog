import { BackgroundRefresher } from '~/common/utils/background-refresher'
import { PostgresRouter, PostgresUse } from '~/common/utils/db/postgres'
import { IngestionPipeline } from '~/common/utils/event-ingestion-restrictions'
import { DEFAULT_LOADER_RETRY, LazyLoader } from '~/common/utils/lazy-loader'
import { logger } from '~/common/utils/logger'
import { Component } from '~/ingestion/common/scopes'

import { treeHasConditions } from './evaluate'
import { eventFiltersOverrideLoadErrors, eventFiltersRefreshErrors } from './metrics'
import { EventFilterRowSchema, EventFilterRule } from './schema'

export interface EventFilterManagerOptions {
    pipeline: IngestionPipeline
}

/**
 * Manages per-team event filter config loaded from Postgres. One filter
 * per team, cached via a `BackgroundRefresher` that reloads all active
 * filters every 60s. The constructor does not prime the cache; call
 * `prime()` (or wrap construction in `EventFilterManagerComponent`) to
 * await the initial load.
 */
export class EventFilterManager {
    private refresher: BackgroundRefresher<Map<number, EventFilterRule>>
    private pipelineOverrides: LazyLoader<boolean>

    constructor(
        private readonly postgres: PostgresRouter,
        private readonly options: EventFilterManagerOptions
    ) {
        // A failed reload keeps the last loaded filters. The default handler rethrows from a
        // detached promise, and the server stops on an unhandled rejection.
        this.refresher = new BackgroundRefresher(
            async () => this.fetchAllFilters(),
            60_000,
            (error) => {
                logger.error('Failed to refresh event filter config', { error })
                eventFiltersRefreshErrors.inc()
            }
        )
        this.pipelineOverrides = new LazyLoader({
            name: 'event_filter_pipeline_overrides',
            refreshAgeMs: 60_000,
            loaderRetry: DEFAULT_LOADER_RETRY,
            loader: async (teamIds) => this.fetchPipelineOverrides(teamIds),
        })
    }

    async prime(): Promise<void> {
        // Do not catch a first load error: startup must fail. A consumer without its filters
        // ingests the events that a filter drops, and those events cannot be removed later.
        await this.refresher.get()
    }

    /** Returns the filter for a team, or null if disabled or has no conditions. Non-blocking. */
    getFilter(teamId: number): EventFilterRule | null {
        const filter = this.refresher.tryGet()?.get(teamId) ?? null
        if (filter && !treeHasConditions(filter.filter_tree)) {
            return null
        }
        return filter
    }

    /**
     * True when the team's override drops every event in this pipeline. Fails open: when
     * the override cannot load, events are ingested, because a wrong drop cannot be undone.
     */
    async dropsAllEvents(teamId: number): Promise<boolean> {
        try {
            return (await this.pipelineOverrides.get(String(teamId))) ?? false
        } catch {
            eventFiltersOverrideLoadErrors.inc()
            return false
        }
    }

    private async fetchPipelineOverrides(teamIds: string[]): Promise<Record<string, boolean>> {
        try {
            // Overrides are stored under the parent team of an environment.
            const { rows } = await this.postgres.query<{ team_id: number; drop_all_events: boolean }>(
                PostgresUse.COMMON_READ,
                `SELECT t.id AS team_id, o.drop_all_events
                 FROM posthog_team t
                 JOIN posthog_eventfilterpipelineoverride o ON o.team_id = COALESCE(t.parent_team_id, t.id)
                 WHERE t.id = ANY($1) AND o.pipeline = $2`,
                [teamIds.map(Number), this.options.pipeline],
                'fetchEventFilterPipelineOverrides'
            )
            return Object.fromEntries(rows.map((row) => [String(row.team_id), row.drop_all_events]))
        } catch (error) {
            logger.error('Failed to load event filter pipeline overrides', {
                pipeline: this.options.pipeline,
                error,
            })
            throw error
        }
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
    constructor(
        private readonly postgres: PostgresRouter,
        private readonly options: EventFilterManagerOptions
    ) {}

    async start(): Promise<{ value: EventFilterManager; stop: () => Promise<void> }> {
        const manager = new EventFilterManager(this.postgres, this.options)
        await manager.prime()
        return { value: manager, stop: () => Promise.resolve() }
    }
}
