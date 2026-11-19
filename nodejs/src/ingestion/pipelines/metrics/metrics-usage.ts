import { Message } from 'node-rdkafka'

export type UsageStats = {
    bytesReceived: number
    recordsReceived: number
    bytesAllowed: number
    bytesAllowedRecords: number
    recordsAllowed: number
    bytesDropped: number
    recordsDropped: number
}

const DEFAULT_USAGE_STATS: UsageStats = {
    bytesReceived: 0,
    recordsReceived: 0,
    bytesAllowed: 0,
    bytesAllowedRecords: 0,
    recordsAllowed: 0,
    bytesDropped: 0,
    recordsDropped: 0,
}

type UsageStatsByTeam = Map<number, UsageStats>

export interface AllowedMetricsMessage {
    teamId: number
    recordId: string
    timestampMs?: number
    bytes: number
    bytesRecords: number
    records: number
}

/** Stable across Kafka replays. Usage-ingestion dedups on the record ID and the day of the timestamp. */
export function kafkaMessageUsageIdentity(message: Message): { recordId: string; timestampMs?: number } {
    return { recordId: `${message.topic}:${message.partition}:${message.offset}`, timestampMs: message.timestamp }
}

export class MetricsUsageAccumulator {
    private readonly stats: UsageStatsByTeam = new Map()
    private readonly allowed: AllowedMetricsMessage[] = []

    recordReceived(teamId: number, bytes: number, records: number): void {
        const stats = this.statsFor(teamId)
        stats.bytesReceived += bytes
        stats.recordsReceived += records
    }

    recordAllowed(
        teamId: number,
        identity: { recordId: string; timestampMs?: number },
        bytes: number,
        records: number,
        bytesRecords: number
    ): void {
        const stats = this.statsFor(teamId)
        stats.bytesAllowed += bytes
        stats.bytesAllowedRecords += bytesRecords
        stats.recordsAllowed += records
        this.allowed.push({ teamId, ...identity, bytes, bytesRecords, records })
    }

    allowedMessages(): readonly AllowedMetricsMessage[] {
        return this.allowed
    }

    recordDropped(teamId: number, bytes: number, records: number): void {
        const stats = this.statsFor(teamId)
        stats.bytesDropped += bytes
        stats.recordsDropped += records
    }

    entries(): IterableIterator<[number, UsageStats]> {
        return this.stats.entries()
    }

    private statsFor(teamId: number): UsageStats {
        let stats = this.stats.get(teamId)
        if (!stats) {
            stats = { ...DEFAULT_USAGE_STATS }
            this.stats.set(teamId, stats)
        }
        return stats
    }
}

export interface MetricsUsageBatchContext {
    usage: MetricsUsageAccumulator
}
