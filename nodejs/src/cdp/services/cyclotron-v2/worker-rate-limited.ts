import { logger } from '~/common/utils/logger'

import { CyclotronV2BatchLimit, CyclotronV2WorkerConfig } from './types'
import { CyclotronV2DequeuedJob } from './types'
import { CyclotronV2Worker, sleep } from './worker'

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

    protected override async runConsumerLoop(
        processBatch: (jobs: CyclotronV2DequeuedJob[]) => Promise<void>
    ): Promise<void> {
        while (this.isConsuming) {
            try {
                this.lastPollTime = new Date()

                // Pre-size the token-bucket claim to the number of rows actually
                // available for this poll, capped at batchMaxSize. Idle polls
                // (count === 0) skip the limiter entirely so the bucket stays
                // at capacity for the next burst. Sparse polls (count < capacity)
                // only consume what they'll send, fixing the "1 ready job drains
                // the whole bucket" failure mode of asking for full capacity
                // every time.
                const visibleRows = await this.countWork(this.batchMaxSize)
                if (visibleRows === 0) {
                    await sleep(this.pollDelayMs)
                    continue
                }

                const decision = await this.getBatchLimit(visibleRows)
                // === 0 (not <=) so a future bug returning a negative limit
                // surfaces as a SQL LIMIT error instead of silently sleeping.
                if (decision && decision.limit === 0) {
                    await sleep(decision.sleepMs ?? this.pollDelayMs)
                    continue
                }
                const effectiveLimit = decision ? Math.min(decision.limit, this.batchMaxSize) : this.batchMaxSize

                const rows = this.fairDequeue
                    ? await this.fairDequeueJobs(effectiveLimit)
                    : await this.dequeueJobs(effectiveLimit)

                if (rows.length === 0) {
                    if (this.includeEmptyBatches) {
                        await processBatch([])
                    }
                    await sleep(this.pollDelayMs)
                    continue
                }

                const jobs = rows.map((row) => this.wrapJob(row))
                await processBatch(jobs)
            } catch (err) {
                logger.error('CyclotronV2RateLimitedWorker consumer loop error', { error: String(err) })
                await sleep(this.pollDelayMs)
            }
        }
    }
}
