import { ValueMatcher } from '~/types'

import { UsageIngestionClient, UsageRecordInput } from './client'

export interface UsageRecordBatchConfig {
    usageKey: string
    unit: string
    isTeamEnabled: ValueMatcher<number>
}

interface PendingRecord {
    teamId: number
    quantity: number
    dimensions?: Record<string, string>
}

/**
 * Sums usage by record ID and sends one record per ID on flush. Summing matters
 * because two records sharing an ID are deduplicated in ClickHouse rather than
 * added, so the caller has to arrive at one quantity per ID before sending.
 */
export class UsageRecordBatch {
    private counts = new Map<string, PendingRecord>()

    constructor(
        private readonly client: UsageIngestionClient | null,
        private readonly config: UsageRecordBatchConfig
    ) {}

    get size(): number {
        return this.counts.size
    }

    add(teamId: number, recordId: string, quantity: number, dimensions?: Record<string, string>): void {
        if (!this.client || quantity <= 0 || !this.config.isTeamEnabled(teamId)) {
            return
        }
        const existing = this.counts.get(recordId)
        if (existing) {
            existing.quantity += quantity
        } else {
            this.counts.set(recordId, { teamId, quantity, dimensions })
        }
    }

    async flush(): Promise<void> {
        if (!this.client || this.counts.size === 0) {
            return
        }
        const eventTimestampMs = Date.now()
        const records: UsageRecordInput[] = [...this.counts.entries()].map(
            ([recordId, { teamId, quantity, dimensions }]) => ({
                recordId,
                teamId,
                usageKey: this.config.usageKey,
                unit: this.config.unit,
                quantity,
                eventTimestampMs,
                dimensions,
            })
        )
        this.counts.clear()
        await this.client.ingest(records)
    }
}
