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
    private pendingAcknowledgements: Promise<void>[] = []

    constructor(
        private readonly client: UsageIngestionClient | null,
        private readonly config: UsageRecordBatchConfig
    ) {}

    get size(): number {
        return this.records.size
    }

    add(teamId: number, usageKey: string, recordId: string): void {
        if (!this.client || !this.config.isTeamEnabled(teamId)) {
            return
        }
        const key = `${teamId}:${usageKey}:${recordId}`
        if (!this.records.has(key)) {
            this.records.set(key, { teamId, usageKey, recordId })
        }
    }

    /**
     * Adds a record only after every Kafka write for its logical event has
     * succeeded. The flush side effect waits for these acknowledgements, so it
     * is safe to schedule both production and usage reporting in the background.
     */
    addAfterAcknowledgements(
        acknowledgements: Promise<unknown | null>[],
        teamId: number,
        usageKey: string,
        recordId: string
    ): void {
        this.pendingAcknowledgements.push(
            Promise.all(acknowledgements)
                .then((results) => {
                    if (results.every((result) => result !== null)) {
                        this.add(teamId, usageKey, recordId)
                    }
                })
                // Kafka errors are handled by the producer side effect. They must
                // not turn into a billing record or an unhandled rejection here.
                .catch(() => undefined)
        )
    }

    async flush(): Promise<void> {
        await Promise.all(this.pendingAcknowledgements)
        this.pendingAcknowledgements = []
        if (!this.client || this.records.size === 0) {
            return
        }
        // Flush time, never anything off the event. toDate of this lands in the storage
        // sorting key, so a customer-supplied value would let a customer decide whether
        // their own records deduplicate.
        const timestampMs = Date.now()
        const records: UsageRecordInput[] = [...this.records.values()].map((record) => ({
            recordId: record.recordId,
            teamId: record.teamId,
            usageKey: record.usageKey,
            unit: this.config.unit,
            quantity: 1,
            timestampMs,
        }))
        this.records.clear()
        await this.client.ingest(records)
    }
}
