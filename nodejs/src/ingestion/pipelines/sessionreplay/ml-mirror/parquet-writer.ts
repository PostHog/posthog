/** Encodes block-metadata rows into a Snappy-compressed Parquet buffer for upload to the ML bucket. */
import { ParquetSchema, ParquetWriter } from '@dsnp/parquetjs'
import { Writable } from 'stream'

import { COLUMNS } from './block-metadata-columns'
import { MlBlockMetadataRow } from './block-metadata-row'

type SchemaDef = ConstructorParameters<typeof ParquetSchema>[0]

// Schema and record mapping both derive from the single COLUMNS table (which also drives the row validator).
// Snappy on every column — compression is a per-field option in parquetjs, not a writer option.
const SCHEMA = new ParquetSchema(
    Object.fromEntries(
        COLUMNS.map((col) => {
            const def: Record<string, unknown> = { type: col.type, compression: 'SNAPPY' }
            if (col.optional) {
                def.optional = true
            }
            if (col.repeated) {
                def.repeated = true
            }
            return [col.parquet, def]
        })
    ) as SchemaDef
)

const bigintOrNull = (n: unknown): bigint | null =>
    n === null || n === undefined ? null : BigInt(Math.trunc(n as number))

function toParquetRecord(row: MlBlockMetadataRow): Record<string, unknown> {
    const record: Record<string, unknown> = {}
    const r = row as unknown as Record<string, unknown>
    for (const col of COLUMNS) {
        const value = r[col.row]
        if (col.type === 'TIMESTAMP_MILLIS') {
            record[col.parquet] = new Date(value as number)
        } else if (col.type === 'INT64') {
            record[col.parquet] = bigintOrNull(value)
        } else {
            record[col.parquet] = value
        }
    }
    return record
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
