/** Parses block-metadata Kafka messages (JSON rows produced by MlBlockMetadataSink) back into rows. */
import { parseJSON } from '~/common/utils/json-parse'
import { logger } from '~/common/utils/logger'

import { MlBlockMetadataRow } from './block-metadata-row'

const STRING_FIELDS: (keyof MlBlockMetadataRow)[] = [
    'session_id',
    'team_id',
    'distinct_id',
    'block_url',
    'block_s3_key',
]
const NUMBER_FIELDS: (keyof MlBlockMetadataRow)[] = [
    'block_length',
    'first_ts_ms',
    'last_ts_ms',
    'event_count',
    'message_count',
    'click_count',
    'keypress_count',
    'mouse_activity_count',
    'active_milliseconds',
    'console_log_count',
    'console_warn_count',
    'console_error_count',
    'size',
]

/** Guards against a poison row crashing the Parquet writer (e.g. `BigInt(undefined)`); our producer always emits these. */
function isWellFormedRow(row: unknown): row is MlBlockMetadataRow {
    if (typeof row !== 'object' || row === null) {
        return false
    }
    const r = row as Record<string, unknown>
    if (!Array.isArray(r.urls)) {
        return false
    }
    return (
        STRING_FIELDS.every((field) => typeof r[field] === 'string') &&
        NUMBER_FIELDS.every((field) => typeof r[field] === 'number' && Number.isFinite(r[field]))
    )
}

export function parseBlockMetadataMessages(messages: readonly { value: Buffer | null }[]): MlBlockMetadataRow[] {
    const rows: MlBlockMetadataRow[] = []
    for (const message of messages) {
        if (!message.value) {
            continue
        }
        let row: unknown
        try {
            row = parseJSON(message.value.toString('utf8'))
        } catch (error) {
            // Skip malformed rows rather than wedge the partition; they're rare and non-fatal for training data.
            logger.warn('🪶', 'ml_parquet_metadata_parse_failed', { error: String(error) })
            continue
        }
        if (!isWellFormedRow(row)) {
            logger.warn('🪶', 'ml_parquet_metadata_row_invalid')
            continue
        }
        rows.push(row)
    }
    return rows
}
