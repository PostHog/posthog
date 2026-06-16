import { logger } from '../../../utils/logger'
import { CyclotronV2BatchLimit, CyclotronV2WorkerConfig } from './types'
import { CyclotronV2DequeuedJob } from './types'
import { CyclotronV2Worker, sleep } from './worker'

/**
 * Variant of CyclotronV2Worker that consults a per-poll rate-limit hook before
 * dequeuing. Returning `{ limit: 0 }` skips the SQL entirely and sleeps;
 * returning `{ limit: N }` clamps the dequeue batch to `min(N, batchMaxSize)`.
 *
 * Used by the email worker to gate SES sends behind a Valkey-backed token
 * bucket. Other consumers run the plain `CyclotronV2Worker` with no rate-limit
 * code in their poll loop.
 */
export class CyclotronV2RateLimitedWorker extends CyclotronV2Worker {
    constructor(
        config: CyclotronV2WorkerConfig,
        private readonly getBatchLimit: () => Promise<CyclotronV2BatchLimit | undefined>
    ) {
        super(config)
    }

    protected override async runConsumerLoop(
        processBatch: (jobs: CyclotronV2DequeuedJob[]) => Promise<void>
    ): Promise<void> {
        while (this.isConsuming) {
            try {
                this.lastPollTime = new Date()

                // Cheap pre-check: only claim tokens if there's actual work to
                // dequeue. Skipping this on idle polls keeps the bucket at
                // capacity (preserves burst), and keeps the limiter's metrics
                // silent when there's nothing to send. The SELECT hits the
                // same partial index as dequeueJobs — strictly cheaper than the
                // UPDATE ... SKIP LOCKED we'd otherwise have run.
                if (!(await this.hasWork())) {
                    await sleep(this.pollDelayMs)
                    continue
                }

                const decision = await this.getBatchLimit()
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
