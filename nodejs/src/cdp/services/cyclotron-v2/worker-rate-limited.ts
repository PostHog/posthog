import { CyclotronV2BatchLimit, CyclotronV2WorkerConfig } from './types'
import { CyclotronV2Worker, PollPlan } from './worker'

/**
 * Variant of CyclotronV2Worker that consults a per-poll rate-limit hook before
 * dequeuing. The hook receives the count of rows actually visible for this
 * poll (capped at `batchMaxSize`); returning `{ limit: 0 }` skips the SQL
 * entirely and sleeps, `{ limit: N }` clamps the dequeue batch to
 * `min(N, batchMaxSize)`.
 *
 * Used by the email worker to gate SES sends behind a Valkey-backed token
 * bucket. Sizing the claim to the visible row count is what keeps a sparse
 * stream of email jobs (one ready row at a time) from draining the bucket's
 * full capacity per send — see `countWork` on the base worker. Other consumers
 * run the plain `CyclotronV2Worker` with no rate-limit code in their poll loop.
 */
export class CyclotronV2RateLimitedWorker extends CyclotronV2Worker {
    constructor(
        config: CyclotronV2WorkerConfig,
        private readonly getBatchLimit: (requested: number) => Promise<CyclotronV2BatchLimit | undefined>
    ) {
        super(config)
    }

    protected override async planPoll(): Promise<PollPlan> {
        const visibleRows = await this.countWork(this.batchMaxSize)
        if (visibleRows === 0) {
            return { skip: true, reason: 'empty' }
        }

        const decision = await this.getBatchLimit(visibleRows)
        // === 0 (not <=) so a future bug returning a negative limit surfaces as a
        // SQL LIMIT error instead of silently sleeping.
        if (decision && decision.limit === 0) {
            return { skip: true, reason: 'throttled', sleepMs: decision.sleepMs }
        }
        return { dequeue: decision ? Math.min(decision.limit, this.batchMaxSize) : this.batchMaxSize }
    }
}
