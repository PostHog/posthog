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

    /** Whether a record for this team would be kept, so a caller can skip building one. */
    accepts(teamId: number): boolean {
        return this.client !== null && this.config.isTeamEnabled(teamId)
    }

    add(teamId: number, usageKey: string, recordId: string): void {
        if (!this.accepts(teamId)) {
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
        // A team that is not reporting must not put the flush behind its Kafka writes.
        if (!this.accepts(teamId)) {
            return
        }
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

    /**
     * Sends what is queued when the call starts. An acknowledgement that lands while this
     * awaits belongs to the next flush, so a caller that keeps adding stays bounded: one
     * pass, one send. A caller that is finished adding wants {@link drain} instead, because
     * nothing would flush that record afterwards.
     */
    async flush(): Promise<void> {
        const pending = this.pendingAcknowledgements
        this.pendingAcknowledgements = []
        await Promise.all(pending)
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

    /**
     * Flushes until nothing is left queued. Only for a caller that has stopped adding: the
     * end of a batch, or a consumer shutting down. Records live in memory until they are
     * sent, so a batch that ends without draining bills nothing for the writes it was still
     * waiting on.
     */
    async drain(): Promise<void> {
        do {
            await this.flush()
        } while (this.pendingAcknowledgements.length > 0 || this.records.size > 0)
    }
}
