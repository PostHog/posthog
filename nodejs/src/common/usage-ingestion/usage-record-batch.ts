import { ValueMatcher } from '~/types'

import { UsageIngestionClient, UsageRecordInput } from './client'

export interface UsageRecordBatchConfig {
    unit: string
    isTeamEnabled: ValueMatcher<number>
    isUsageKeyEnabled?: (teamId: number, usageKey: string) => boolean
}

interface PendingRecord {
    teamId: number
    usageKey: string
    recordId: string
    dimensions?: Record<string, string>
    quantity: number
    unit?: string
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

    add(
        teamId: number,
        usageKey: string,
        recordId: string,
        dimensions?: Record<string, string>,
        quantity = 1,
        unit?: string
    ): void {
        if (
            !this.client ||
            quantity <= 0 ||
            !this.config.isTeamEnabled(teamId) ||
            (this.config.isUsageKeyEnabled && !this.config.isUsageKeyEnabled(teamId, usageKey))
        ) {
            return
        }
        const key = `${teamId}:${usageKey}:${recordId}`
        if (!this.records.has(key)) {
            this.records.set(key, { teamId, usageKey, recordId, dimensions, quantity, unit })
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
            unit: record.unit ?? this.config.unit,
            quantity: record.quantity,
            eventTimestampMs,
            dimensions: record.dimensions,
        }))
        this.records.clear()
        await this.client.ingest(records)
    }
}
