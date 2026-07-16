import { ClickHouseClient } from '@clickhouse/client'
import { Counter } from 'prom-client'

import { logger } from '~/common/utils/logger'

import { RerunJobManager } from '../../rerun/rerun-job.manager'
import { RerunFunctionKind } from '../../rerun/rerun-job.types'
import { JANITOR_POISON_PILL_ERROR_KIND } from './janitor'

const autodrainGroupsCounter = new Counter({
    name: 'cdp_cyclotron_v2_autodrain_groups_total',
    help: 'Poison-pill groups discovered by the autodrain service',
})

const autodrainEnqueuedCounter = new Counter({
    name: 'cdp_cyclotron_v2_autodrain_enqueued_total',
    help: 'Rerun wrapper jobs enqueued by the autodrain service to drain recorded poison pills',
})

const autodrainErrorsCounter = new Counter({
    name: 'cdp_cyclotron_v2_autodrain_errors_total',
    help: 'Groups the autodrain service failed to enqueue a rerun for',
})

// ClickHouse's `DateTime64` parser only accepts 'YYYY-MM-DD HH:MM:SS[.fff]'. Our
// window bounds are produced as ISO 8601 (with `T` and `Z`), so strip those
// before binding to query params — same conversion the rerun paginator does.
const toClickhouseDateTime = (value: string): string => {
    if (!value) {
        return value
    }
    if (!value.includes('T')) {
        return value
    }
    return value
        .replace('T', ' ')
        .replace(/Z$/, '')
        .replace(/([+-]\d{2}):?(\d{2})$/, '')
}

export interface CyclotronPoisonPillAutodrainConfig {
    intervalMs: number
    windowHours: number
    maxAttempts: number
    groupBatch: number
    maxCountPerGroup: number
}

export interface AutodrainRunResult {
    groups: number
    enqueued: number
}

// count()/team_id come back from ClickHouse JSONEachRow as strings (64-bit
// integers are quoted by default), so parse them where we need numbers.
interface DiscoveredGroupRow {
    team_id: string | number
    function_kind: string
    function_id: string
    pending: string | number
}

/**
 * Periodically drains recorded cyclotron poison pills. The janitor records a
 * poison-pill give-up as a `failed` invocation result with
 * `error_kind='janitor_poison_pill'` and then deletes the cyclotron row — durable
 * and recoverable, but recovery was a manual operator rerun. This service does
 * that rerun automatically: it discovers groups with pending poison pills in
 * ClickHouse and enqueues a rerun wrapper for each via the existing rerun tooling.
 */
export class CyclotronPoisonPillAutodrain {
    private intervalHandle: ReturnType<typeof setInterval> | null = null

    constructor(
        private clickhouse: ClickHouseClient,
        private rerunManager: RerunJobManager,
        private config: CyclotronPoisonPillAutodrainConfig
    ) {}

    async start(): Promise<void> {
        this.intervalHandle = setInterval(() => {
            this.runOnce().catch((err) => {
                logger.error('CyclotronPoisonPillAutodrain run error', { error: String(err) })
            })
        }, this.config.intervalMs)

        // Run immediately on start rather than waiting a full interval.
        await this.runOnce()
    }

    async runOnce(): Promise<AutodrainRunResult> {
        // Pin the window once so discovery and the reruns it spawns agree on the
        // same bounds — a rerun's filter must not span a wider window than the
        // discovery that found it.
        const windowEnd = new Date()
        const windowStart = new Date(windowEnd.getTime() - this.config.windowHours * 60 * 60 * 1000)
        const windowStartIso = windowStart.toISOString()
        const windowEndIso = windowEnd.toISOString()

        const groups = await this.discoverGroups(windowStartIso, windowEndIso)
        autodrainGroupsCounter.inc(groups.length)

        if (groups.length === 0) {
            return { groups: 0, enqueued: 0 }
        }

        let enqueued = 0
        for (const group of groups) {
            const teamId = Number(group.team_id)
            const functionKind = group.function_kind as RerunFunctionKind
            try {
                await this.rerunManager.enqueue(teamId, functionKind, group.function_id, {
                    filter: {
                        window_start: windowStartIso,
                        window_end: windowEndIso,
                        status: ['failed'],
                        error_kind: [JANITOR_POISON_PILL_ERROR_KIND],
                        max_attempts: this.config.maxAttempts,
                        max_count: this.config.maxCountPerGroup,
                    },
                })
                enqueued++
            } catch (err) {
                // One group failing must not abort the tick — record it and move
                // on so the remaining groups still drain this cycle.
                autodrainErrorsCounter.inc()
                logger.error('CyclotronPoisonPillAutodrain failed to enqueue rerun for group', {
                    team_id: teamId,
                    function_kind: functionKind,
                    function_id: group.function_id,
                    error: err instanceof Error ? err.message : String(err),
                })
            }
        }
        autodrainEnqueuedCounter.inc(enqueued)

        logger.info('CyclotronPoisonPillAutodrain drained poison-pill groups', {
            groups: groups.length,
            enqueued,
        })

        return { groups: groups.length, enqueued }
    }

    /**
     * Find distinct (team_id, function_kind, function_id) groups that still have
     * at least one poison pill pending a drain — an invocation whose LATEST
     * lifecycle row (argMax by `version`) is a not-deleted `failed`
     * `janitor_poison_pill` under the attempts cap, within the window.
     *
     * Loop prevention / dedup — why this converges without a cursor or state table:
     *  - `max_attempts` bounds retries. The recorded `attempts` climbs on each
     *    rerun; both this HAVING and the rerun paginator exclude over-cap
     *    invocations, so a genuinely-always-poison job is drained a bounded number
     *    of times and then left failed.
     *  - Self-dedup. When the rerun re-enqueues an invocation it writes a
     *    `running` lifecycle row, so that invocation's argMax(status) flips to
     *    `running` and it drops out of discovery until it either completes (drops
     *    out) or re-poisons — in which case the janitor writes a fresh `failed`
     *    `janitor_poison_pill` row with `attempts+1`, rediscovered but closer to
     *    the cap. No cursor or state table is needed for v1.
     *  - Throttle. At most `group_batch` groups per tick, `max_count` invocations
     *    per group, plus the tick interval between runs.
     */
    private async discoverGroups(windowStartIso: string, windowEndIso: string): Promise<DiscoveredGroupRow[]> {
        // The table is partitioned by toYYYYMMDD(scheduled_at), so the window
        // bound pins the query to a handful of partitions instead of a full scan.
        const result = await this.clickhouse.query({
            query: `/* query_type:cyclotron_poison_pill_autodrain_discover */
                SELECT team_id, function_kind, function_id, count() AS pending
                FROM (
                    SELECT team_id, function_kind, function_id, invocation_id
                    FROM hog_invocation_results
                    WHERE scheduled_at >= {window_start:DateTime64(6,'UTC')}
                      AND scheduled_at <  {window_end:DateTime64(6,'UTC')}
                    GROUP BY team_id, function_kind, function_id, invocation_id
                    HAVING argMax(is_deleted, version) = 0
                       AND argMax(status, version) = 'failed'
                       AND argMax(error_kind, version) = {error_kind:String}
                       AND argMax(attempts, version) < {max_attempts:UInt8}
                )
                GROUP BY team_id, function_kind, function_id
                ORDER BY pending DESC
                LIMIT {group_batch:UInt32}`,
            query_params: {
                window_start: toClickhouseDateTime(windowStartIso),
                window_end: toClickhouseDateTime(windowEndIso),
                error_kind: JANITOR_POISON_PILL_ERROR_KIND,
                max_attempts: this.config.maxAttempts,
                group_batch: this.config.groupBatch,
            },
            format: 'JSONEachRow',
        })

        return (await result.json()) as DiscoveredGroupRow[]
    }

    isRunning(): boolean {
        return this.intervalHandle !== null
    }

    stop(): void {
        if (this.intervalHandle) {
            clearInterval(this.intervalHandle)
            this.intervalHandle = null
        }
    }
}
