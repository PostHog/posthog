/** Single source of truth for the ML block-metadata columns: drives the Parquet schema, the row→record
 *  mapping (in parquet-writer.ts), and the poison-row validator below. Kept free of the Parquet dependency
 *  so the message-parsing path doesn't pull it in. */
import { isRawTeamId } from '~/ingestion/pipelines/sessionreplay/ml-mirror-image-scrub/content-ref'

import { MlBlockMetadataRow } from './block-metadata-row'

export type ParquetType = 'UTF8' | 'INT32' | 'INT64' | 'TIMESTAMP_MILLIS'

export interface BlockMetadataColumn {
    /** Field name on the JSON wire row (MlBlockMetadataRow). */
    row: keyof MlBlockMetadataRow
    /** Column name in the Parquet schema; differs from `row` only for the renamed timestamps. */
    parquet: string
    type: ParquetType
    /** Nullable column — not required to be present or typed on a parsed row. */
    optional?: boolean
    /** Repeated UTF8 column (string array). */
    repeated?: boolean
}

export const COLUMNS: BlockMetadataColumn[] = [
    { row: 'session_id', parquet: 'session_id', type: 'UTF8' },
    { row: 'team_id', parquet: 'team_id', type: 'UTF8' },
    { row: 'block_url', parquet: 'block_url', type: 'UTF8' },
    { row: 'block_s3_key', parquet: 'block_s3_key', type: 'UTF8' },
    { row: 'block_byte_start', parquet: 'block_byte_start', type: 'INT64', optional: true },
    { row: 'block_byte_end', parquet: 'block_byte_end', type: 'INT64', optional: true },
    { row: 'block_length', parquet: 'block_length', type: 'INT64' },
    { row: 'first_ts_ms', parquet: 'first_ts', type: 'TIMESTAMP_MILLIS' },
    { row: 'last_ts_ms', parquet: 'last_ts', type: 'TIMESTAMP_MILLIS' },
    { row: 'event_count', parquet: 'event_count', type: 'INT32' },
    { row: 'message_count', parquet: 'message_count', type: 'INT32' },
    { row: 'click_count', parquet: 'click_count', type: 'INT32' },
    { row: 'keypress_count', parquet: 'keypress_count', type: 'INT32' },
    { row: 'mouse_activity_count', parquet: 'mouse_activity_count', type: 'INT32' },
    { row: 'active_milliseconds', parquet: 'active_milliseconds', type: 'INT32' },
    { row: 'console_log_count', parquet: 'console_log_count', type: 'INT32' },
    { row: 'console_warn_count', parquet: 'console_warn_count', type: 'INT32' },
    { row: 'console_error_count', parquet: 'console_error_count', type: 'INT32' },
    { row: 'size', parquet: 'size', type: 'INT64' },
    { row: 'first_url', parquet: 'first_url', type: 'UTF8', optional: true },
    { row: 'urls', parquet: 'urls', type: 'UTF8', repeated: true },
    { row: 'snapshot_source', parquet: 'snapshot_source', type: 'UTF8', optional: true },
    { row: 'snapshot_library', parquet: 'snapshot_library', type: 'UTF8', optional: true },
    { row: 'retention_period_days', parquet: 'retention_period_days', type: 'INT32', optional: true },
]

/** Guards against a poison row crashing the Parquet writer (e.g. `BigInt(undefined)`); our producer always emits these. */
export function isWellFormedRow(row: unknown): row is MlBlockMetadataRow {
    if (typeof row !== 'object' || row === null) {
        return false
    }
    const r = row as Record<string, unknown>
    if (r.format_version !== undefined && (r.format_version !== 2 || !isRawTeamId(r.team_id))) {
        return false
    }
    for (const col of COLUMNS) {
        const value = r[col.row]
        if (col.optional && (value === null || value === undefined)) {
            continue
        }
        const encodable = col.repeated
            ? Array.isArray(value) && value.every((item) => isEncodableValue(col.type, item))
            : isEncodableValue(col.type, value)
        if (!encodable) {
            return false
        }
    }
    return true
}

const INT32_MIN = -(2 ** 31)
const INT32_MAX = 2 ** 31 - 1
// ECMAScript time values stop at 8.64e15 ms either side of the epoch, so a larger timestamp becomes an Invalid Date.
const MAX_TIME_VALUE_MS = 8.64e15

function isEncodableValue(type: ParquetType, value: unknown): boolean {
    if (type === 'UTF8') {
        return typeof value === 'string'
    }
    if (typeof value !== 'number' || !Number.isFinite(value)) {
        return false
    }
    if (type === 'INT32') {
        return Number.isInteger(value) && value >= INT32_MIN && value <= INT32_MAX
    }
    if (type === 'INT64') {
        return Number.isSafeInteger(value)
    }
    return Math.abs(value) <= MAX_TIME_VALUE_MS
}

export function selectBlockMetadataFields(row: MlBlockMetadataRow): MlBlockMetadataRow {
    return Object.fromEntries(
        [
            ...COLUMNS.map(({ row: field }) => field),
            'format_version',
            'session_start_ts_ms',
            'replay_index_entries',
            'replay_index_truncated',
        ]
            .filter((field) => Object.hasOwn(row, field))
            .map((field) => [field, row[field as keyof MlBlockMetadataRow]])
    ) as unknown as MlBlockMetadataRow
}
