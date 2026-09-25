import { instrumentFn, setSpanAttributes } from '~/common/tracing/tracing-utils'
import { PostgresRouter, PostgresUse } from '~/common/utils/db/postgres'
import { logger } from '~/common/utils/logger'

const REFRESH_MS = 30_000
const UNKNOWN_ID_REFRESH_MS = 5_000
// Sweep only once the map is big enough to be worth walking; a team is dropped well after its
// entry went stale, so an active team is never evicted between messages.
const MAX_CACHED_TEAMS = 1_000
const EVICT_AFTER_MS = 10 * 60_000

/** app_metrics2 metric names written per source (`instance_id` = LogsSource id); the sources health API reads them. */
export const SOURCE_RECORDS_RECEIVED_METRIC = 'source_records_received'
export const SOURCE_RECORDS_DROPPED_METRIC = 'source_records_dropped'

/** `unknown` is an id no source of the team has: deleted, mistyped, or from another environment. */
export type LogsSourceState = 'enabled' | 'disabled' | 'unknown'

const sourcesCacheInstrumentOpts = { measureTime: false, sendException: false } as const

type CacheEntry = {
    enabledById: Map<string, boolean>
    fetchedAtMs: number
    refreshAfterMs: number
}

const stateOf = (entry: CacheEntry, sourceId: string): LogsSourceState => {
    const enabled = entry.enabledById.get(sourceId)
    if (enabled === undefined) {
        return 'unknown'
    }
    return enabled ? 'enabled' : 'disabled'
}

export class LogsSourcesCache {
    private cache = new Map<number, CacheEntry>()
    private pending = new Map<number, Promise<CacheEntry>>()

    constructor(private postgres: PostgresRouter) {}

    public async getSourceState(teamId: number, sourceId: string): Promise<LogsSourceState> {
        // Deliberately uninstrumented: this runs per message, and a hit is two map lookups.
        // Only the fetch below carries a span.
        const existing = this.cache.get(teamId)
        if (existing && !this.isStale(existing, sourceId)) {
            return stateOf(existing, sourceId)
        }
        return this.refreshAndRead(teamId, sourceId, existing)
    }

    private isStale(entry: CacheEntry, sourceId: string): boolean {
        const ageMs = Date.now() - entry.fetchedAtMs
        if (ageMs >= entry.refreshAfterMs) {
            return true
        }
        // An id absent from a fresh set is usually a source enabled a moment ago, so it refetches
        // sooner. The floor keeps an id that will never appear from refetching per message.
        return !entry.enabledById.has(sourceId) && ageMs >= UNKNOWN_ID_REFRESH_MS
    }

    private refreshAndRead(
        teamId: number,
        sourceId: string,
        existing: CacheEntry | undefined
    ): Promise<LogsSourceState> {
        return instrumentFn(
            {
                key: 'logsIngestion.sources.refresh',
                ...sourcesCacheInstrumentOpts,
                getLoggingContext: () => ({ team_id: teamId, source_id: sourceId }),
            },
            async () => {
                try {
                    const entry = await this.refresh(teamId)
                    setSpanAttributes({ 'logs.sources.source_count': entry.enabledById.size })
                    return stateOf(entry, sourceId)
                } catch (error) {
                    // Fail open: this runs in the ingestion hot path, so a Postgres blip must not
                    // drop otherwise-valid logs. Serve the last-known set when there is one, else
                    // treat the source as enabled. The stale `fetchedAtMs` retries on the next message.
                    logger.warn('[logs-sources] fetch failed, falling back', {
                        teamId,
                        error: String(error),
                    })
                    setSpanAttributes({
                        'logs.sources.fetch_failed': true,
                        'logs.sources.served_stale': Boolean(existing),
                    })
                    return existing ? stateOf(existing, sourceId) : 'enabled'
                }
            }
        )
    }

    /** One fetch per team at a time: a batch of messages for a cold team shares the query. */
    private refresh(teamId: number): Promise<CacheEntry> {
        const inFlight = this.pending.get(teamId)
        if (inFlight) {
            return inFlight
        }
        const fetch = this.fetchSources(teamId)
            .then((enabledById) => {
                const entry = {
                    enabledById,
                    fetchedAtMs: Date.now(),
                    // Jitter, so the teams warmed by one batch do not all re-query in the same tick.
                    refreshAfterMs: REFRESH_MS * (0.85 + Math.random() * 0.3),
                }
                this.cache.set(teamId, entry)
                this.evictExpired(entry.fetchedAtMs)
                return entry
            })
            .finally(() => this.pending.delete(teamId))
        this.pending.set(teamId, fetch)
        return fetch
    }

    /** The consumer runs for days, so a team it stopped serving must not hold an entry forever. */
    private evictExpired(nowMs: number): void {
        if (this.cache.size <= MAX_CACHED_TEAMS) {
            return
        }
        for (const [teamId, entry] of this.cache) {
            if (nowMs - entry.fetchedAtMs >= EVICT_AFTER_MS) {
                this.cache.delete(teamId)
            }
        }
    }

    private async fetchSources(teamId: number): Promise<Map<string, boolean>> {
        const res = await this.postgres.query<{ id: string; enabled: boolean }>(
            PostgresUse.COMMON_READ,
            `SELECT id::text AS id, enabled
             FROM logs_logssource
             WHERE team_id = $1`,
            [teamId],
            'logs-sources-fetch'
        )
        return new Map(res.rows.map((r) => [r.id, r.enabled]))
    }
}
