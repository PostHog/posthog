import { ParquetSchema } from '@dsnp/parquetjs'

import { ReplayIndexEntrySchema } from '~/ingestion/pipelines/sessionreplay/shared/metadata/replay-index-entry'
import { parquetRecordsToBuffer } from '~/ingestion/pipelines/sessionreplay/shared/parquet'

import { MlBlockMetadataRow } from './block-metadata-row'
import { MlParquetSinkMetrics } from './metrics'

const DAY_MS = 86_400_000
const schema = new ParquetSchema({
    team_id: { type: 'UTF8', compression: 'SNAPPY' },
    session_id: { type: 'UTF8', compression: 'SNAPPY' },
    window_id: { type: 'UTF8', compression: 'SNAPPY' },
    kind: { type: 'UTF8', compression: 'SNAPPY' },
    session_start_ts_ms: { type: 'DOUBLE', compression: 'SNAPPY' },
    event_ts_ms: { type: 'DOUBLE', compression: 'SNAPPY' },
    block_index_truncated: { type: 'BOOLEAN', compression: 'SNAPPY' },
    event_index: { type: 'INT32', compression: 'SNAPPY' },
    full_snapshot_ts_ms: { type: 'DOUBLE', optional: true, compression: 'SNAPPY' },
    root_types: { type: 'UTF8', repeated: true, compression: 'SNAPPY' },
    url: { type: 'UTF8', optional: true, compression: 'SNAPPY' },
    block_s3_key: { type: 'UTF8', compression: 'SNAPPY' },
    block_byte_start: { type: 'DOUBLE', optional: true, compression: 'SNAPPY' },
    block_byte_end: { type: 'DOUBLE', optional: true, compression: 'SNAPPY' },
})

export function replayIndexPartitions(rows: MlBlockMetadataRow[]): Map<string, Record<string, unknown>[]> {
    const partitions = new Map<string, Record<string, unknown>[]>()
    for (const row of rows) {
        if (row.replay_index_truncated) {
            MlParquetSinkMetrics.incReplayIndexSkipped('truncated_block')
        }
        if (!Array.isArray(row.replay_index_entries) || row.replay_index_entries.length === 0) {
            continue
        }
        const started = row.session_start_ts_ms
        if (
            typeof started !== 'number' ||
            !Number.isSafeInteger(started) ||
            started <= 0 ||
            started > 0xffffffffffff ||
            started > row.last_ts_ms ||
            row.last_ts_ms - started > 7 * DAY_MS
        ) {
            MlParquetSinkMetrics.incReplayIndexSkipped('session_start')
            continue
        }
        const date = new Date(started).toISOString().slice(0, 10)
        for (const value of row.replay_index_entries) {
            const result = ReplayIndexEntrySchema.safeParse(value)
            if (
                !result.success ||
                result.data.eventIndex >= row.event_count ||
                result.data.eventTimestamp < row.first_ts_ms ||
                result.data.eventTimestamp > row.last_ts_ms
            ) {
                MlParquetSinkMetrics.incReplayIndexSkipped('invalid_entry')
                continue
            }
            const entry = result.data
            const key = `kind=${entry.kind}/session_start_date=${date}`
            let records = partitions.get(key)
            if (!records) {
                records = []
                partitions.set(key, records)
            }
            records.push({
                team_id: row.team_id,
                session_id: row.session_id,
                window_id: entry.windowId,
                kind: entry.kind,
                session_start_ts_ms: started,
                event_ts_ms: entry.eventTimestamp,
                event_index: entry.eventIndex,
                block_index_truncated: row.replay_index_truncated === true,
                full_snapshot_ts_ms: entry.fullSnapshotTimestamp ?? null,
                root_types: entry.rootTypes ?? [],
                url: entry.url ?? null,
                block_s3_key: row.block_s3_key,
                block_byte_start: row.block_byte_start,
                block_byte_end: row.block_byte_end,
            })
        }
    }
    return partitions
}

export function replayIndexToParquetBuffer(records: Record<string, unknown>[]): Promise<Buffer> {
    return parquetRecordsToBuffer(schema, records)
}
