import { Message } from 'node-rdkafka'

import { UsageIngestionClient, UsageRecordInput } from '~/common/usage-ingestion/client'
import { ValueMatcher } from '~/types'

interface OffsetRange {
    teamId: number
    usageKey: string
    topic: string
    partition: number
    minOffset: number
    maxOffset: number
    quantity: number
}

/**
 * Accumulates billable event counts for one Kafka batch and sends one usage
 * record per (team, usage key, topic, partition).
 *
 * The record ID is the consumed offset range, so a batch that is replayed over
 * the same offsets after a rebalance produces the same ID and is deduplicated
 * in ClickHouse instead of being counted twice.
 */
export class EventUsageBatch {
    private ranges = new Map<string, OffsetRange>()

    constructor(
        private readonly client: UsageIngestionClient | null,
        private readonly isTeamEnabled: ValueMatcher<number>
    ) {}

    increment(teamId: number, usageKey: string, message: Message, quantity: number): void {
        if (!this.client || quantity <= 0 || !this.isTeamEnabled(teamId)) {
            return
        }
        const key = `${teamId}:${usageKey}:${message.topic}:${message.partition}`
        const existing = this.ranges.get(key)
        if (existing) {
            existing.minOffset = Math.min(existing.minOffset, message.offset)
            existing.maxOffset = Math.max(existing.maxOffset, message.offset)
            existing.quantity += quantity
        } else {
            this.ranges.set(key, {
                teamId,
                usageKey,
                topic: message.topic,
                partition: message.partition,
                minOffset: message.offset,
                maxOffset: message.offset,
                quantity,
            })
        }
    }

    async flush(): Promise<void> {
        if (!this.client || this.ranges.size === 0) {
            return
        }
        const eventTimestampMs = Date.now()
        const records: UsageRecordInput[] = [...this.ranges.values()].map((range) => ({
            recordId: `${range.topic}:${range.partition}:${range.minOffset}-${range.maxOffset}:${range.usageKey}`,
            teamId: range.teamId,
            usageKey: range.usageKey,
            unit: 'events',
            quantity: range.quantity,
            eventTimestampMs,
            dimensions: { topic: range.topic, partition: String(range.partition) },
        }))
        this.ranges.clear()
        await this.client.ingest(records)
    }
}
