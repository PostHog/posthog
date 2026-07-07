/** One anonymized block's metadata as a flat row for the ML Parquet dataset; ids are pseudonyms. */
import { SessionBlockMetadata } from '~/ingestion/pipelines/sessionreplay/shared/metadata/session-block-metadata'

import { PSEUDONYM_DISTINCT_ID, PSEUDONYM_SESSION, PSEUDONYM_TEAM, pseudonymize } from './pseudonymize'

export interface MlBlockMetadataRow {
    session_id: string
    team_id: string
    distinct_id: string
    block_url: string
    block_s3_key: string
    block_byte_start: number | null
    block_byte_end: number | null
    block_length: number
    first_ts_ms: number
    last_ts_ms: number
    event_count: number
    message_count: number
    click_count: number
    keypress_count: number
    mouse_activity_count: number
    active_milliseconds: number
    console_log_count: number
    console_warn_count: number
    console_error_count: number
    size: number
    first_url: string | null
    urls: string[]
    snapshot_source: string | null
    snapshot_library: string | null
    retention_period_days: number | null
}

const RANGE_MARKER = '?range=bytes='

/** Splits a `s3://bucket/key?range=bytes=start-end` block URL into the object key and byte range. */
export function parseBlockUrl(blockUrl: string): { key: string; start: number | null; end: number | null } {
    const idx = blockUrl.indexOf(RANGE_MARKER)
    if (idx < 0) {
        return { key: blockUrl, start: null, end: null }
    }
    const key = blockUrl.slice(0, idx)
    const [startStr, endStr] = blockUrl.slice(idx + RANGE_MARKER.length).split('-')
    const start = Number(startStr)
    const end = Number(endStr)
    return { key, start: Number.isFinite(start) ? start : null, end: Number.isFinite(end) ? end : null }
}

/** Maps a flush's block metadata to a row, or null for deletion/no-op markers that reference no block. */
export function toBlockMetadataRow(block: SessionBlockMetadata, secret: string | Buffer): MlBlockMetadataRow | null {
    if (!block.blockUrl || block.isDeleted) {
        return null
    }
    const { key, start, end } = parseBlockUrl(block.blockUrl)
    return {
        session_id: pseudonymize(secret, PSEUDONYM_SESSION, block.sessionId),
        team_id: pseudonymize(secret, PSEUDONYM_TEAM, String(block.teamId)),
        distinct_id: pseudonymize(secret, PSEUDONYM_DISTINCT_ID, block.distinctId),
        block_url: block.blockUrl,
        block_s3_key: key,
        block_byte_start: start,
        block_byte_end: end,
        block_length: block.blockLength,
        first_ts_ms: block.startDateTime.toMillis(),
        last_ts_ms: block.endDateTime.toMillis(),
        event_count: block.eventCount,
        message_count: block.messageCount,
        click_count: block.clickCount,
        keypress_count: block.keypressCount,
        mouse_activity_count: block.mouseActivityCount,
        active_milliseconds: block.activeMilliseconds,
        console_log_count: block.consoleLogCount,
        console_warn_count: block.consoleWarnCount,
        console_error_count: block.consoleErrorCount,
        size: block.size,
        first_url: block.firstUrl,
        urls: block.urls ?? [],
        snapshot_source: block.snapshotSource,
        snapshot_library: block.snapshotLibrary,
        retention_period_days: block.retentionPeriodDays,
    }
}
