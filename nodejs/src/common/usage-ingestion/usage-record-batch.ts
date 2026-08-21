import { ValueMatcher } from '~/types'

import { UsageIngestionClient, UsageRecordInput } from './client'

export interface UsageRecordBatchConfig {
    unit: string
    isTeamEnabled: ValueMatcher<number>
}

interface PendingRecord {
    teamId: number
    usageKey: string
    recordId: string
    dimensions?: Record<string, string>
}

/**
 * Collects one usage record per billed thing, identified by a record ID the
 * producer can reproduce. Every record carries quantity 1, so a second `add` of
 * the same identity is the same thing seen twice and is discarded rather than
 * added — the aggregate lives in ClickHouse, keyed the same way.
 *
 * Keyed by (team, usage key, record ID) to match the ingest contract's identity.
 * Keying on the record ID alone would merge two teams that share an ID and bill
 * both to the first one.
 */
export class UsageRecordBatch {
    private records = new Map<string, PendingRecord>()

    constructor(
        private readonly client: UsageIngestionClient | null,
        private readonly config: UsageRecordBatchConfig
    ) {}

    get size(): number {
        return this.records.size
    }

    add(teamId: number, usageKey: string, recordId: string, dimensions?: Record<string, string>): void {
        if (!this.client || !this.config.isTeamEnabled(teamId)) {
            return
        }
        const key = `${teamId}:${usageKey}:${recordId}`
        if (!this.records.has(key)) {
            this.records.set(key, { teamId, usageKey, recordId, dimensions })
        }
    }

    async flush(): Promise<void> {
        if (!this.client || this.records.size === 0) {
            return
        }
        const eventTimestampMs = Date.now()
        const records: UsageRecordInput[] = [...this.records.values()].map((record) => ({
            recordId: record.recordId,
            teamId: record.teamId,
            usageKey: record.usageKey,
            unit: this.config.unit,
            quantity: 1,
            eventTimestampMs,
            dimensions: record.dimensions,
        }))
        this.records.clear()
        await this.client.ingest(records)
    }
}
