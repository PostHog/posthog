import { Pool } from 'pg'
import { Counter, Gauge } from 'prom-client'

import { logger } from '~/common/utils/logger'
import { captureException } from '~/common/utils/posthog'

import { ConversionWatcherRow, CyclotronJobInvocationResult } from '../../types'

const counterConversionWatchersInserted = new Counter({
    name: 'cdp_conversion_watchers_inserted',
    help: 'Conversion watcher rows written at run start, one per enrolled run on a goal workflow.',
})

const counterConversionWatchersFailed = new Counter({
    name: 'cdp_conversion_watchers_failed',
    help: 'Watcher rows dropped because the insert failed. Each one is a run whose conversion can never be counted, so the conversion rate under-reports by exactly this much.',
})

const gaugeConversionWatchersPending = new Gauge({
    name: 'cdp_conversion_watchers_pending_rows',
    help: 'Watcher rows queued in memory waiting for the next flush. Resets to 0 after each flush.',
})

// Bounds a single INSERT's parameter count: Postgres caps a statement at 65535 bindings, and each row
// binds 10.
const INSERT_CHUNK_SIZE = 1000

/**
 * Writes a watcher row when a run enrolls.
 *
 * Reading and claiming watchers belongs to the subscription matcher, which is where the event stream
 * is, and deleting expired ones belongs to the cyclotron janitor. This service is the write side,
 * wired into `InvocationResultsService` alongside the other result-borne row sinks.
 */
export class ConversionWatchersService {
    private queuedRows: ConversionWatcherRow[] = []
    private pool: Pool | null = null
    private stopped = false
    private inFlight = new Set<Promise<unknown>>()

    // Owns its pool rather than taking one, mirroring the subscription matcher: the table lives in the
    // cyclotron database, which nothing else in the result-sink chain connects to. A process without
    // the connection string drops watchers via the failure counter rather than throwing, so processes
    // that never run workflows are unaffected.
    constructor(
        private readonly databaseUrl: string | undefined,
        private readonly maxConnections?: number
    ) {}

    // Built on first use, not in the constructor. Every CDP service set constructs this service, but
    // only the ones that actually run workflows ever write a row — an eager pool would have every
    // consumer, and every test that builds a service set, holding cyclotron connections it never uses.
    private getPool(): Pool | null {
        if (this.pool || this.stopped || !this.databaseUrl) {
            return this.pool
        }
        this.pool = new Pool({ connectionString: this.databaseUrl, max: this.maxConnections })
        // pg throws an uncaught exception if an idle client errors with no listener attached, which
        // would take down the process for something this sink is allowed to drop.
        this.pool.on('error', (err) => {
            logger.error('⚠️', 'Conversion watcher pool error', { err })
        })
        return this.pool
    }

    // Idempotent: pg rejects a second end() with "Called end on pool more than once", and several
    // shutdown paths reach this one service — the base consumer teardown, CdpRerunWorkerConsumer's
    // own stop(), and CdpApi.stop(). A consumer stopped twice must not fail its own shutdown.
    public async stop(): Promise<void> {
        // Set first so a flush that has not started yet gets no pool and drops its rows through the
        // failure counter, rather than opening a connection this method is about to close.
        this.stopped = true
        // A flush that is already running holds a pool reference and awaits a query. Ending the pool
        // under it would fail the work it has not finished, so wait for every one of them. Each
        // operation reports its own failure, and shutdown must not re-raise that.
        await Promise.all([...this.inFlight].map((operation) => operation.catch(() => {})))
        const pool = this.pool
        this.pool = null
        await pool?.end()
    }

    public queueInvocationResults(results: CyclotronJobInvocationResult[]): void {
        for (const result of results) {
            if (result.conversionWatchers.length) {
                this.queuedRows.push(...result.conversionWatchers)
            }
        }
        gaugeConversionWatchersPending.set(this.queuedRows.length)
    }

    // Registers a running operation so stop() can wait for it before it closes the pool. The operation
    // takes its pool reference before the first await, so by the time it is tracked it already holds
    // one, and stop() cannot slip in between. The returned promise is the caller's, so a failure still
    // surfaces where it was started.
    private track<T>(operation: Promise<T>): Promise<T> {
        this.inFlight.add(operation)
        void operation.catch(() => {}).finally(() => this.inFlight.delete(operation))
        return operation
    }

    public async flush(): Promise<void> {
        await this.track(this.writeQueuedRows())
    }

    private async writeQueuedRows(): Promise<void> {
        if (!this.queuedRows.length) {
            return
        }
        const rows = this.queuedRows
        this.queuedRows = []
        gaugeConversionWatchersPending.set(0)

        const pool = this.getPool()
        if (!pool) {
            counterConversionWatchersFailed.inc(rows.length)
            logger.error('⚠️', 'Dropping conversion watchers: no cyclotron database configured', {
                count: rows.length,
            })
            return
        }

        for (let offset = 0; offset < rows.length; offset += INSERT_CHUNK_SIZE) {
            const chunk = rows.slice(offset, offset + INSERT_CHUNK_SIZE)
            try {
                await this.insertChunk(pool, chunk)
                counterConversionWatchersInserted.inc(chunk.length)
            } catch (err) {
                // Dropping a watcher silently under-reports conversions rather than failing loudly, so
                // this counter is the only signal that it happened. Not rethrown: a failed insert must
                // not take down the batch that produced the run, which has already executed.
                counterConversionWatchersFailed.inc(chunk.length)
                logger.error('⚠️', 'Failed to insert conversion watchers', { err, count: chunk.length })
                captureException(err)
            }
        }
    }

    private async insertChunk(pool: Pool, rows: ConversionWatcherRow[]): Promise<void> {
        const values: any[] = []
        const placeholders = rows.map((row, index) => {
            const base = index * 10
            values.push(
                row.id,
                row.team_id,
                row.function_id,
                row.run_id,
                row.parent_run_id,
                row.distinct_id,
                row.person_id,
                row.flow_version,
                JSON.stringify(row.goal),
                row.expires_at
            )
            return `($${base + 1}, $${base + 2}, $${base + 3}, $${base + 4}, $${base + 5}, $${base + 6}, $${base + 7}, $${base + 8}, $${base + 9}, $${base + 10})`
        })

        await pool.query(
            `INSERT INTO conversion_watchers
                (id, team_id, function_id, run_id, parent_run_id, distinct_id, person_id, flow_version, goal, expires_at)
             VALUES ${placeholders.join(', ')}
             ON CONFLICT (id) DO NOTHING`,
            values
        )
    }
}
