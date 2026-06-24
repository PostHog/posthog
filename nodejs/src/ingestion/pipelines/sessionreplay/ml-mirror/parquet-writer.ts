/** Encodes block-metadata rows into a Snappy-compressed Parquet buffer for upload to the ML bucket. */
import { ParquetSchema, ParquetWriter } from '@dsnp/parquetjs'
import { Writable } from 'stream'

import { MlBlockMetadataRow } from './block-metadata-row'

type SchemaDef = ConstructorParameters<typeof ParquetSchema>[0]

const BASE_FIELDS: SchemaDef = {
    session_id: { type: 'UTF8' },
    team_id: { type: 'UTF8' },
    distinct_id: { type: 'UTF8' },
    block_url: { type: 'UTF8' },
    block_s3_key: { type: 'UTF8' },
    block_byte_start: { type: 'INT64', optional: true },
    block_byte_end: { type: 'INT64', optional: true },
    block_length: { type: 'INT64' },
    first_ts: { type: 'TIMESTAMP_MILLIS' },
    last_ts: { type: 'TIMESTAMP_MILLIS' },
    event_count: { type: 'INT32' },
    message_count: { type: 'INT32' },
    click_count: { type: 'INT32' },
    keypress_count: { type: 'INT32' },
    mouse_activity_count: { type: 'INT32' },
    active_milliseconds: { type: 'INT32' },
    console_log_count: { type: 'INT32' },
    console_warn_count: { type: 'INT32' },
    console_error_count: { type: 'INT32' },
    size: { type: 'INT64' },
    first_url: { type: 'UTF8', optional: true },
    urls: { type: 'UTF8', repeated: true },
    snapshot_source: { type: 'UTF8', optional: true },
    snapshot_library: { type: 'UTF8', optional: true },
    retention_period_days: { type: 'INT32', optional: true },
}

// Snappy on every column — compression is a per-field option in parquetjs, not a writer option.
const SCHEMA = new ParquetSchema(
    Object.fromEntries(
        Object.entries(BASE_FIELDS).map(([name, def]) => [name, { ...def, compression: 'SNAPPY' }])
    ) as SchemaDef
)

const bigintOrNull = (n: number | null): bigint | null => (n === null ? null : BigInt(Math.trunc(n)))

function toParquetRecord(row: MlBlockMetadataRow): Record<string, unknown> {
    return {
        session_id: row.session_id,
        team_id: row.team_id,
        distinct_id: row.distinct_id,
        block_url: row.block_url,
        block_s3_key: row.block_s3_key,
        block_byte_start: bigintOrNull(row.block_byte_start),
        block_byte_end: bigintOrNull(row.block_byte_end),
        block_length: BigInt(Math.trunc(row.block_length)),
        first_ts: new Date(row.first_ts_ms),
        last_ts: new Date(row.last_ts_ms),
        event_count: row.event_count,
        message_count: row.message_count,
        click_count: row.click_count,
        keypress_count: row.keypress_count,
        mouse_activity_count: row.mouse_activity_count,
        active_milliseconds: row.active_milliseconds,
        console_log_count: row.console_log_count,
        console_warn_count: row.console_warn_count,
        console_error_count: row.console_error_count,
        size: BigInt(Math.trunc(row.size)),
        first_url: row.first_url,
        urls: row.urls,
        snapshot_source: row.snapshot_source,
        snapshot_library: row.snapshot_library,
        retention_period_days: row.retention_period_days,
    }
}

export async function rowsToParquetBuffer(rows: MlBlockMetadataRow[]): Promise<Buffer> {
    const chunks: Buffer[] = []
    const sink = new Writable({
        write(chunk: Buffer, _encoding, callback) {
            chunks.push(chunk)
            callback()
        },
    })
    // parquetjs types want an fs.WriteStream, but it only calls write/end/on at runtime, which Writable provides.
    const writer = await ParquetWriter.openStream(
        SCHEMA,
        sink as unknown as Parameters<typeof ParquetWriter.openStream>[1]
    )
    for (const row of rows) {
        await writer.appendRow(toParquetRecord(row))
    }
    await writer.close()
    return Buffer.concat(chunks)
}
