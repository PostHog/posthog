import { UsageIngestionClient } from '~/common/usage-ingestion/client'
import { UsageRecordBatch } from '~/common/usage-ingestion/usage-record-batch'
import { logger } from '~/common/utils/logger'
import { ValueMatcher } from '~/types'

const USAGE_KEY = 'cdp_billable_invocations'
const DEFAULT_FLUSH_INTERVAL_MS = 10_000
const MAX_PENDING_RECORDS = 2_000

export interface CdpBillableInvocation {
    teamId: number
    /** Identity of the billed thing. A replay must produce the same value, or it bills twice. */
    recordId: string
}

/**
 * Deliberately independent of `app_metrics2`: it owns its own batching and flushing, so the app
 * metric a call site also emits can be deleted without touching billing. The timer bounds how
 * long a record waits; `shutdown()` is what keeps a graceful deploy lossless.
 */
export class CdpUsageReporterService {
    private batch: UsageRecordBatch
    private timer: NodeJS.Timeout | null = null

    constructor(
        client: UsageIngestionClient | null,
        isTeamEnabled: ValueMatcher<number>,
        private readonly flushIntervalMs: number = DEFAULT_FLUSH_INTERVAL_MS
    ) {
        this.batch = new UsageRecordBatch(client, { unit: 'invocations', isTeamEnabled })
    }

    reportBillableInvocation(invocation: CdpBillableInvocation): void {
        this.batch.add(invocation.teamId, USAGE_KEY, invocation.recordId)
        if (this.batch.size >= MAX_PENDING_RECORDS) {
            void this.flush()
            return
        }
        this.scheduleFlush()
    }

    /** One pass, for the timer: an invocation reported mid-send waits for the next flush. */
    async flush(): Promise<void> {
        await this.send(() => this.batch.flush())
    }

    /** For a consumer that is stopping: keeps flushing until nothing is left in memory. */
    async shutdown(): Promise<void> {
        await this.send(() => this.batch.drain())
    }

    private async send(sendBatch: () => Promise<void>): Promise<void> {
        if (this.timer) {
            clearTimeout(this.timer)
            this.timer = null
        }
        try {
            await sendBatch()
        } catch (error) {
            logger.warn('\u26a0\ufe0f', 'failed to flush cdp usage records', { error: String(error) })
        }
    }

    private scheduleFlush(): void {
        if (this.timer || this.batch.size === 0) {
            return
        }
        // Unreferenced so a pending flush never keeps the process alive on shutdown.
        this.timer = setTimeout(() => void this.flush(), this.flushIntervalMs)
        this.timer.unref()
    }
}
