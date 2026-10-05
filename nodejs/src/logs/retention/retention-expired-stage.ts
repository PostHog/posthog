import { Counter } from 'prom-client'

import type { LogRecord } from '~/logs/log-record-avro'
import { EMPTY_STAGE_DROP_STATS, type PipelineStage, recordContentBytes } from '~/logs/pipeline/log-processing-pipeline'

const MICROS_PER_DAY = 86_400_000_000

export const RETENTION_EXPIRED_STAGE_NAME = 'retention_expired'

function isPastRetention(timestampMicros: number, retentionDays: number, nowMicros: number): boolean {
    return timestampMicros + retentionDays * MICROS_PER_DAY <= nowMicros
}

export const logsRetentionExpiredRowsDroppedCounter = new Counter({
    name: 'logs_ingestion_retention_expired_rows_dropped_total',
    help: 'Log rows dropped because their timestamp plus their retention was already in the past when they arrived.',
    labelNames: ['team_id'],
})

/**
 * A message without the header comes from a capture-logs build older than the header, and that build
 * still accepts `backfill_days`, so its rows can be old. Skipping the check for it is safe only while
 * ClickHouse counts expiry from the ingest time. Every capture-logs instance must send the header
 * before ClickHouse counts expiry from the row timestamp.
 */
export function canHoldExpiredRow(
    minTimestampMicros: number | undefined,
    shortestRetentionDays: number,
    nowMicros: number
): boolean {
    if (minTimestampMicros === undefined) {
        return false
    }
    return isPastRetention(minTimestampMicros, shortestRetentionDays, nowMicros)
}

/**
 * Keep this fallback the same as `original_expiry_timestamp` in `kafka_logs34_avro_mv`: the row's
 * `retention_days` when it is above 0, else the batch `retention-days` header, which carries the team
 * default. If the two disagree, this drops rows that ClickHouse would keep, or writes rows that it
 * treats as expired.
 */
function isExpired(record: LogRecord, defaultRetentionDays: number, nowMicros: number): boolean {
    if (record.timestamp === null) {
        return false
    }
    const rowRetentionDays = record.retention_days ?? 0
    const retentionDays = rowRetentionDays > 0 ? rowRetentionDays : defaultRetentionDays
    return isPastRetention(record.timestamp, retentionDays, nowMicros)
}

export function makeRetentionExpiredStage(
    teamId: number,
    defaultRetentionDays: number,
    nowMicros: number
): PipelineStage {
    return {
        kind: 'filter',
        name: RETENTION_EXPIRED_STAGE_NAME,
        run: (records) => {
            const stats = EMPTY_STAGE_DROP_STATS()
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
                logsRetentionExpiredRowsDroppedCounter.inc({ team_id: String(teamId) }, stats.recordsDropped)
            }
            return { kept, stats }
        },
    }
}
