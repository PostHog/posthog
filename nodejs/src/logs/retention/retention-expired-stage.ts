import { Counter } from 'prom-client'

import type { LogRecord } from '~/logs/log-record-avro'
import { EMPTY_DROP_STATS, type PipelineStage, recordContentBytes } from '~/logs/pipeline/log-processing-pipeline'

const MICROS_PER_DAY = 86_400_000_000

export const logsRetentionExpiredRowsDroppedCounter = new Counter({
    name: 'logs_ingestion_retention_expired_rows_dropped_total',
    help: 'Log rows dropped because their timestamp plus their retention was already in the past when they arrived.',
    labelNames: ['team_id'],
})

/**
 * A message without the header comes from a capture-logs that clamps every timestamp to within 24
 * hours of ingest, and the shortest retention is 14 days, so none of its rows can be expired.
 */
export function canHoldExpiredRow(
    minTimestampMicros: number | undefined,
    shortestRetentionDays: number,
    nowMicros: number
): boolean {
    if (minTimestampMicros === undefined) {
        return false
    }
    return minTimestampMicros + shortestRetentionDays * MICROS_PER_DAY <= nowMicros
}

/**
 * Keep this fallback order the same as `original_expiry_timestamp` in `kafka_logs34_avro_mv`: the row's
 * `retention_days`, then the batch `retention-days` header, which carries the team default. If the two
 * disagree, this drops rows that ClickHouse would keep, or writes rows that it treats as expired.
 */
function isExpired(record: LogRecord, defaultRetentionDays: number, nowMicros: number): boolean {
    if (record.timestamp === null) {
        return false
    }
    const retentionDays = record.retention_days ?? defaultRetentionDays
    return record.timestamp + retentionDays * MICROS_PER_DAY <= nowMicros
}

export function makeRetentionExpiredStage(
    teamId: number,
    defaultRetentionDays: number,
    nowMicros: number
): PipelineStage {
    return {
        kind: 'filter',
        name: 'retention_expired',
        measuresBatchContentFirst: true,
        run: (records) => {
            const stats = EMPTY_DROP_STATS()
            const kept: LogRecord[] = []
            for (const record of records) {
                if (isExpired(record, defaultRetentionDays, nowMicros)) {
                    stats.recordsDropped++
                    stats.contentBytesDropped += recordContentBytes(record)
                } else {
                    kept.push(record)
                }
            }
            if (stats.recordsDropped > 0) {
                stats.droppedBy = 'retention_expired'
                logsRetentionExpiredRowsDroppedCounter.inc({ team_id: String(teamId) }, stats.recordsDropped)
            }
            return { kept, stats }
        },
    }
}
