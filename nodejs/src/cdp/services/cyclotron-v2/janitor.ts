import { DateTime } from 'luxon'
import { Pool } from 'pg'
import { Counter, Gauge } from 'prom-client'

import { logger } from '~/common/utils/logger'

import { CyclotronJobInvocationHogFlow } from '../../types'
import { v2JobToInvocation } from '../job-queue/job-queue-postgres-v2'
import { HogInvocationResultsService } from '../monitoring/hog-invocation-results.service'
import { CyclotronV2CleanupResult, CyclotronV2DequeuedJob, CyclotronV2JanitorConfig } from './types'

// Stable, low-cardinality `error_kind` stamped on the failed invocation result
// the janitor writes when it gives up on a poison pill. Lets operators target
// exactly these give-ups from the rerun tooling (rerun filter `error_kind`).
export const JANITOR_POISON_PILL_ERROR_KIND = 'janitor_poison_pill'

const janitorDeletedCounter = new Counter({
    name: 'cdp_cyclotron_v2_janitor_deleted',
    help: 'Number of terminal jobs cleaned up by the janitor',
    labelNames: ['status'],
})

const janitorStalledCounter = new Counter({
    name: 'cdp_cyclotron_v2_janitor_stalled',
    help: 'Number of stalled jobs reset by the janitor',
})

const janitorPoisonedCounter = new Counter({
    name: 'cdp_cyclotron_v2_janitor_poisoned',
    help: 'Number of poison pill jobs given up on (recorded as failed, replayable) by the janitor',
})

const janitorGiveUpSkippedCounter = new Counter({
    name: 'cdp_cyclotron_v2_janitor_give_up_skipped',
    help: 'Poison pills the janitor could not record a recovery row for, so kept (not deleted)',
})

const janitorRunCounter = new Counter({
    name: 'cdp_cyclotron_v2_janitor_runs',
    help: 'Number of janitor cleanup runs completed',
})

const queueDepthGauge = new Gauge({
    name: 'cdp_cyclotron_v2_queue_depth',
    help: 'Number of available jobs per queue',
    labelNames: ['queue'],
})

interface PoisonRow {
    id: string
    team_id: number
    function_id: string | null
    queue_name: string
    priority: number
    // pg returns these as ISO strings here (same as the worker's dequeue rows),
    // not Date objects — parse with fromISO, never fromJSDate.
    scheduled: string
    created: string
    parent_run_id: string | null
    state: Buffer | null
    distinct_id: string | null
    person_id: string | null
    action_id: string | null
    janitor_touch_count: number
    transition_count: number
}

export class CyclotronV2Janitor {
    private pool: Pool
    private intervalHandle: ReturnType<typeof setInterval> | null = null

    private readonly cleanupBatchSize: number
    private readonly cleanupIntervalMs: number
    private readonly stallTimeoutMs: number
    private readonly maxTouchCount: number
    private readonly cleanupGraceMs: number
    private readonly poisonRecoveryEnabled: boolean
    private readonly stallBackoffBaseMs: number
    private readonly stallBackoffMaxMs: number

    constructor(
        config: CyclotronV2JanitorConfig,
        // Optional so the v1 postgres paths and unit tests that don't exercise
        // the give-up path can construct a janitor without Kafka. When absent
        // the janitor never deletes poison pills (it only resets/retries) — it
        // refuses to drop a job it can't record a recovery row for.
        private invocationResults?: HogInvocationResultsService
    ) {
        this.pool = new Pool({
            connectionString: config.pool.dbUrl,
            max: config.pool.maxConnections ?? 5,
            idleTimeoutMillis: config.pool.idleTimeoutMs ?? 30000,
        })
        this.cleanupBatchSize = config.cleanupBatchSize ?? 10000
        this.cleanupIntervalMs = config.cleanupIntervalMs ?? 10000
        this.stallTimeoutMs = config.stallTimeoutMs ?? 30000
        this.maxTouchCount = config.maxTouchCount ?? 3
        this.cleanupGraceMs = config.cleanupGraceMs ?? 10000
        this.poisonRecoveryEnabled = config.poisonRecoveryEnabled ?? true
        this.stallBackoffBaseMs = config.stallBackoffBaseMs ?? 30000
        this.stallBackoffMaxMs = config.stallBackoffMaxMs ?? 600000

        if (!this.poisonRecoveryEnabled) {
            logger.warn(
                'CyclotronV2Janitor poison-pill recovery DISABLED via CYCLOTRON_NODE_POISON_PILL_RECOVERY_ENABLED=false — reverting to legacy behavior: poison pills are marked failed with no replay record'
            )
        }
    }

    async start(): Promise<void> {
        const client = await this.pool.connect()
        client.release()

        this.intervalHandle = setInterval(() => {
            this.runOnce().catch((err) => {
                logger.error('CyclotronV2Janitor run error', { error: String(err) })
            })
        }, this.cleanupIntervalMs)

        // Run immediately on start
        await this.runOnce()
    }

    async runOnce(): Promise<CyclotronV2CleanupResult> {
        const deletedCounts = await this.cleanupTerminalJobs()
        const deleted = Object.values(deletedCounts).reduce((a, b) => a + b, 0)

        // Give up on genuine poison pills. The kill-switch picks between two
        // self-contained paths with no inline flag checks beyond this branch:
        // the new record-then-delete path, or master's legacy mark-failed path.
        // The legacy path (and the flag) can be deleted wholesale once we trust
        // recording in production.
        const poisonedIds = this.poisonRecoveryEnabled
            ? await this.recordAndDeletePoisonPills()
            : await this.failPoisonPills()

        const stalled = await this.resetStalledJobs()
        const depths = await this.measureQueueDepths()

        janitorRunCounter.inc()

        return { deleted, stalled, poisoned: poisonedIds.length, poisonedIds, depths }
    }

    private async cleanupTerminalJobs(): Promise<Record<string, number>> {
        const cutoff = new Date(Date.now() - this.cleanupGraceMs)

        const result = await this.pool.query<{ status: string; count: string }>(
            `WITH to_delete AS (
                SELECT id
                FROM cyclotron_jobs
                WHERE status IN ('completed', 'failed', 'canceled')
                  AND last_transition < $1
                ORDER BY last_transition ASC
                LIMIT $2
                FOR UPDATE SKIP LOCKED
            )
            DELETE FROM cyclotron_jobs
            USING to_delete
            WHERE cyclotron_jobs.id = to_delete.id
            RETURNING cyclotron_jobs.status::text`,
            [cutoff, this.cleanupBatchSize]
        )

        let total = 0
        const counts: Record<string, number> = {}
        for (const row of result.rows) {
            counts[row.status] = (counts[row.status] ?? 0) + 1
            total++
        }

        for (const [status, count] of Object.entries(counts)) {
            janitorDeletedCounter.inc({ status }, count)
        }

        if (total > 0) {
            logger.info('CyclotronV2Janitor cleaned up terminal jobs', { counts, total })
        }

        return counts
    }

    /**
     * Kill-switch OFF path — restores master's pre-recovery behavior verbatim:
     * mark poison pills `failed` (then `cleanupTerminalJobs` sweeps them like any
     * other failed job) with no recovery record. A give-up here is lost to replay,
     * exactly as before this change — that is what OFF means. Kept as a
     * self-contained counterpart to `recordAndDeletePoisonPills` so this whole
     * path, and the flag, can be deleted once recording is trusted in production.
     */
    private async failPoisonPills(): Promise<string[]> {
        const heartbeatCutoff = new Date(Date.now() - this.stallTimeoutMs)

        const result = await this.pool.query<{ id: string }>(
            `UPDATE cyclotron_jobs
             SET status = 'failed', lock_id = NULL, last_heartbeat = NULL,
                 last_transition = NOW(), transition_count = transition_count + 1
             WHERE id IN (
                 SELECT id
                 FROM cyclotron_jobs
                 WHERE status = 'running'
                   AND COALESCE(last_heartbeat, $1) <= $1
                   AND janitor_touch_count >= $2
                 FOR UPDATE SKIP LOCKED
             )
             RETURNING id`,
            [heartbeatCutoff, this.maxTouchCount]
        )

        const ids = result.rows.map((r) => r.id)
        if (ids.length > 0) {
            janitorPoisonedCounter.inc(ids.length)
            logger.warn('CyclotronV2Janitor failed poison pill jobs (recovery disabled, no replay record)', {
                count: ids.length,
            })
        }
        return ids
    }

    /**
     * Give up on poison pills: running jobs with a stale heartbeat that have
     * been reset too many times. Each one is recorded as a `failed`, replayable
     * invocation result (discoverable in the Invocations UI, re-runnable by the
     * existing rerun tooling) and only then deleted — so there is never a window
     * where the cyclotron row is gone but no recovery record exists. The
     * original incident deleted these with no trace; here every give-up is
     * logged with its id and recorded for replay.
     */
    private async recordAndDeletePoisonPills(): Promise<string[]> {
        const heartbeatCutoff = new Date(Date.now() - this.stallTimeoutMs)

        const result = await this.pool.query<PoisonRow>(
            `SELECT id, team_id, function_id, queue_name, priority, scheduled, created,
                    parent_run_id, state, distinct_id, person_id, action_id,
                    janitor_touch_count, transition_count
             FROM cyclotron_jobs
             WHERE status = 'running'
               AND COALESCE(last_heartbeat, $1) <= $1
               AND janitor_touch_count >= $2
             ORDER BY last_transition ASC
             LIMIT $3
             FOR UPDATE SKIP LOCKED`,
            [heartbeatCutoff, this.maxTouchCount, this.cleanupBatchSize]
        )

        if (result.rows.length === 0) {
            return []
        }

        if (!this.invocationResults) {
            // No way to record a recovery row — keep the jobs rather than drop
            // them silently. resetStalledJobs will retry them this cycle.
            janitorGiveUpSkippedCounter.inc(result.rows.length)
            logger.warn('CyclotronV2Janitor cannot record poison pill recovery (no results service), keeping jobs', {
                count: result.rows.length,
            })
            return []
        }

        const recordedIds: string[] = []
        let skipped = 0
        for (const row of result.rows) {
            const invocation = this.poisonRowToInvocation(row)
            const ok = await this.invocationResults.recordTerminalFailureDurably(invocation, {
                error: `poison pill: stalled and reset ${row.janitor_touch_count} times without completing`,
                errorKind: JANITOR_POISON_PILL_ERROR_KIND,
            })
            if (ok) {
                recordedIds.push(row.id)
            } else {
                skipped++
            }
        }

        if (skipped > 0) {
            janitorGiveUpSkippedCounter.inc(skipped)
            logger.warn('CyclotronV2Janitor kept poison pills it could not durably record', { count: skipped })
        }

        if (recordedIds.length === 0) {
            return []
        }

        // Re-assert the FULL poison predicate (not just status='running') in the
        // DELETE. Between the SELECT and here a row could have been reset to
        // 'available' and re-dequeued by a worker — that re-dequeue stamps a
        // fresh heartbeat, so the stale-heartbeat / touch-count guard no longer
        // matches and we won't delete an actively-running job. RETURNING gives
        // the rows actually removed, so the metric/log reflect real give-ups
        // even if a concurrent janitor or worker raced us to some of them.
        const deleted = await this.pool.query<{ id: string }>(
            `DELETE FROM cyclotron_jobs
             WHERE id = ANY($1::uuid[])
               AND status = 'running'
               AND COALESCE(last_heartbeat, $2) <= $2
               AND janitor_touch_count >= $3
             RETURNING id`,
            [recordedIds, heartbeatCutoff, this.maxTouchCount]
        )
        const deletedIds = deleted.rows.map((r) => r.id)

        if (deletedIds.length > 0) {
            janitorPoisonedCounter.inc(deletedIds.length)
            logger.warn('CyclotronV2Janitor gave up on poison pill jobs (recorded as failed, replayable)', {
                count: deletedIds.length,
                ids: deletedIds,
            })
        }

        return deletedIds
    }

    // Turn a raw poisoned row into a hog flow invocation the results service can
    // serialize. postgres-v2 backs hog flows, so we tag it as such — the stub
    // `hogFlow` carries only the id the lifecycle row needs (function_id), while
    // the rerun path rebuilds the full flow from the function id on replay.
    private poisonRowToInvocation(row: PoisonRow): CyclotronJobInvocationHogFlow {
        const job: CyclotronV2DequeuedJob = {
            id: row.id,
            teamId: row.team_id,
            functionId: row.function_id,
            queueName: row.queue_name,
            priority: row.priority,
            scheduled: DateTime.fromISO(row.scheduled, { zone: 'utc' }),
            created: DateTime.fromISO(row.created, { zone: 'utc' }),
            parentRunId: row.parent_run_id,
            transitionCount: row.transition_count,
            state: row.state,
            distinctId: row.distinct_id,
            personId: row.person_id,
            actionId: row.action_id,
            ack: () => Promise.resolve(),
            fail: () => Promise.resolve(),
            reschedule: () => Promise.resolve(),
            cancel: () => Promise.resolve(),
            heartbeat: () => Promise.resolve(),
            bulkCreateAndCheckIn: () => Promise.resolve({ newJobIds: [] }),
        }
        const invocation = v2JobToInvocation(job)
        return { ...invocation, hogFlow: { id: invocation.functionId } } as CyclotronJobInvocationHogFlow
    }

    private async resetStalledJobs(): Promise<number> {
        const heartbeatCutoff = new Date(Date.now() - this.stallTimeoutMs)

        // Exponential backoff with half-jitter on the next scheduled time, keyed
        // on janitor_touch_count, so repeated stalls back off and a fleet-wide
        // stall doesn't immediately re-flood the workers that just recovered.
        // Half-jitter (delay in [0.5, 1] x the capped backoff) still defers the
        // job while spreading a synchronized herd across the window. Disabled when
        // stallBackoffBaseMs <= 0 — scheduled is left untouched (immediate retry).
        const backoffEnabled = this.stallBackoffBaseMs > 0
        const backoffClause = backoffEnabled
            ? `, scheduled = NOW() + (
                   LEAST($2::float8 * POWER(2, janitor_touch_count), $3::float8) * (0.5 + 0.5 * random())
               ) * INTERVAL '1 millisecond'`
            : ''
        const params: (Date | number)[] = backoffEnabled
            ? [heartbeatCutoff, this.stallBackoffBaseMs, this.stallBackoffMaxMs]
            : [heartbeatCutoff]

        const result = await this.pool.query(
            `WITH stalled AS (
                SELECT id
                FROM cyclotron_jobs
                WHERE status = 'running'
                  AND COALESCE(last_heartbeat, $1) <= $1
                FOR UPDATE SKIP LOCKED
            )
            UPDATE cyclotron_jobs
            SET status = 'available', lock_id = NULL, last_heartbeat = NULL,
                janitor_touch_count = janitor_touch_count + 1${backoffClause}
            FROM stalled
            WHERE cyclotron_jobs.id = stalled.id`,
            params
        )

        const count = result.rowCount ?? 0
        if (count > 0) {
            janitorStalledCounter.inc(count)
            logger.info('CyclotronV2Janitor reset stalled jobs', { count })
        }

        return count
    }

    async measureQueueDepths(): Promise<Map<string, number>> {
        const result = await this.pool.query<{ queue_name: string; count: string }>(
            `SELECT queue_name, COUNT(*) as count
             FROM cyclotron_jobs
             WHERE status = 'available' AND scheduled <= NOW()
             GROUP BY queue_name`
        )

        const depths = new Map<string, number>()
        for (const row of result.rows) {
            const count = parseInt(row.count, 10)
            depths.set(row.queue_name, count)
            queueDepthGauge.labels({ queue: row.queue_name }).set(count)
        }

        return depths
    }

    isRunning(): boolean {
        return this.intervalHandle !== null
    }

    async stop(): Promise<void> {
        if (this.intervalHandle) {
            clearInterval(this.intervalHandle)
            this.intervalHandle = null
        }
        await this.pool.end()
    }
}
