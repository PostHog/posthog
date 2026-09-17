import { trace } from '@opentelemetry/api'

import { instrumentFn } from '~/common/tracing/tracing-utils'
import { PostgresRouter, PostgresUse } from '~/common/utils/db/postgres'
import { logger } from '~/common/utils/logger'

const REFRESH_MS = 30_000
// An id absent from a fresh set is usually a source enabled a moment ago, so it refetches sooner
// than the regular refresh. The floor keeps an id that will never appear from refetching per message.
const UNKNOWN_ID_REFRESH_MS = 5_000

/** app_metrics2 metric names written per source (`instance_id` = LogsSource id); the sources health API reads them. */
export const SOURCE_RECORDS_RECEIVED_METRIC = 'source_records_received'
export const SOURCE_RECORDS_DROPPED_METRIC = 'source_records_dropped'

/** `unknown` is an id no source of the team has: deleted, mistyped, or from another environment. */
export type LogsSourceState = 'enabled' | 'disabled' | 'unknown'

const sourcesCacheInstrumentOpts = { measureTime: false, sendException: false } as const

type CacheEntry = {
    enabledById: Map<string, boolean>
    fetchedAtMs: number
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
        return instrumentFn(
            {
                key: 'logsIngestion.sources.getSourceState',
                ...sourcesCacheInstrumentOpts,
                getLoggingContext: () => ({ team_id: teamId, source_id: sourceId }),
            },
            async () => {
                const now = Date.now()
                const existing = this.cache.get(teamId)
                if (existing) {
                    const ageMs = now - existing.fetchedAtMs
                    const known = existing.enabledById.has(sourceId)
                    if (ageMs < REFRESH_MS && (known || ageMs < UNKNOWN_ID_REFRESH_MS)) {
                        trace.getActiveSpan()?.setAttributes({ 'logs.sources.cache_hit': true })
                        return stateOf(existing, sourceId)
                    }
                }
                let entry: CacheEntry
                try {
                    entry = await this.refresh(teamId, now)
                } catch (error) {
                    // Fail open: this runs in the ingestion hot path, so a Postgres blip must not
                    // drop otherwise-valid logs. Serve the last-known set when there is one, else
                    // treat the source as enabled. The stale `fetchedAtMs` retries on the next message.
                    logger.warn('[logs-sources] fetch failed, falling back', {
                        teamId,
                        error: String(error),
                    })
                    trace.getActiveSpan()?.setAttributes({
                        'logs.sources.fetch_failed': true,
                        'logs.sources.served_stale': Boolean(existing),
                    })
                    return existing ? stateOf(existing, sourceId) : 'enabled'
                }
                trace.getActiveSpan()?.setAttributes({
                    'logs.sources.cache_hit': false,
                    'logs.sources.source_count': entry.enabledById.size,
                })
                return stateOf(entry, sourceId)
            }
        )
    }

    /** One fetch per team at a time: a batch of messages for a cold team shares the query. */
    private refresh(teamId: number, now: number): Promise<CacheEntry> {
        const inFlight = this.pending.get(teamId)
        if (inFlight) {
            return inFlight
        }
        const fetch = this.fetchSources(teamId)
            .then((enabledById) => {
                const entry = { enabledById, fetchedAtMs: now }
                this.cache.set(teamId, entry)
                return entry
            })
            .finally(() => this.pending.delete(teamId))
        this.pending.set(teamId, fetch)
        return fetch
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
