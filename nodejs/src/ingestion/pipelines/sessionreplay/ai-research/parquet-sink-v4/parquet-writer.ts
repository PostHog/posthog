/** Encodes v4 index rows into a zstd-compressed Parquet buffer, with the types of the COLUMNS table. */
import { ParquetSchema } from '@dsnp/parquetjs'
import { PARQUET_COMPRESSION_METHODS } from '@dsnp/parquetjs/dist/lib/compression'
import { promisify } from 'node:util'
import { constants, zstdCompress, zstdDecompress } from 'node:zlib'

import { INDEX_COLUMNS, ParquetType, V4Column, V4Index, V4IndexRow } from './index-columns'
import { parquetRecordsToBuffer } from './parquet-buffer'

type SchemaDef = ConstructorParameters<typeof ParquetSchema>[0]

const ZSTD_LEVEL = 9
const zstdCompressAsync = promisify(zstdCompress)
const zstdDecompressAsync = promisify(zstdDecompress)

// parquetjs ships no zstd codec and takes compression per field, not per writer. Its codec table is open and its Thrift enum has ZSTD, so the file records the right codec.
PARQUET_COMPRESSION_METHODS.ZSTD = {
    deflate: (value: Buffer) =>
        zstdCompressAsync(value, { params: { [constants.ZSTD_c_compressionLevel]: ZSTD_LEVEL } }),
    inflate: (value: Buffer) => zstdDecompressAsync(value),
}

// A list of structs gets the 3-level LIST layout because Athena reads a bare repeated group of several fields as null.
function schemaDef(columns: readonly V4Column[]): SchemaDef {
    const def: Record<string, unknown> = {}
    for (const column of columns) {
        if ('repeated' in column) {
            def[column.name] = {
                type: 'LIST',
                fields: { list: { repeated: true, fields: { element: { fields: schemaDef(column.fields) } } } },
            }
        } else if ('elements' in column) {
            def[column.name] = {
                type: 'LIST',
                optional: true,
                fields: {
                    list: { repeated: true, fields: { element: { type: column.elements, compression: 'ZSTD' } } },
                },
            }
        } else if ('list' in column) {
            def[column.name] = { type: column.list, repeated: true, compression: 'ZSTD' }
        } else {
            def[column.name] = {
                type: column.type,
                compression: 'ZSTD',
                ...(column.optional && { optional: true }),
                ...(column.opaque && { statistics: false }),
            }
        }
    }
    return def as SchemaDef
}

const SCHEMAS: Record<V4Index, ParquetSchema> = {
    blocks: new ParquetSchema(schemaDef(INDEX_COLUMNS.blocks)),
    images: new ParquetSchema(schemaDef(INDEX_COLUMNS.images)),
}

const compareStrings = (a: string, b: string): number => (a < b ? -1 : a > b ? 1 : 0)

const compareNumbersNullsLast = (a: number | null, b: number | null): number =>
    a === b ? 0 : a === null ? 1 : b === null ? -1 : a - b

function compareBlocks(a: V4IndexRow, b: V4IndexRow): number {
    return (
        (a.team_id as number) - (b.team_id as number) ||
        compareStrings(a.session_id as string, b.session_id as string) ||
        compareNumbersNullsLast(a.first_ts_ms as number | null, b.first_ts_ms as number | null)
    )
}

/** Puts a session's blocks next to each other, so its repeated session and window ids compress to almost nothing. */
function inFileOrder(index: V4Index, rows: readonly V4IndexRow[]): readonly V4IndexRow[] {
    return index === 'blocks' ? [...rows].sort(compareBlocks) : rows
}

function toValue(type: ParquetType, value: unknown): unknown {
    return type === 'INT64' ? BigInt(value as number) : value
}

function toRecord(row: V4IndexRow, columns: readonly V4Column[]): Record<string, unknown> {
    const record: Record<string, unknown> = {}
    for (const column of columns) {
        const value = row[column.name]
        if ('repeated' in column) {
            record[column.name] = {
                list: (value as V4IndexRow[]).map((item) => ({ element: toRecord(item, column.fields) })),
            }
        } else if ('list' in column) {
            record[column.name] = (value as unknown[]).map((item) => toValue(column.list, item))
        } else if ('elements' in column) {
            record[column.name] =
                value === null || value === undefined
                    ? null
                    : { list: (value as unknown[]).map((item) => ({ element: toValue(column.elements, item) })) }
        } else if (value === null || value === undefined) {
            record[column.name] = null
        } else {
            record[column.name] = toValue(column.type, value)
        }
    }
    return record
}

export function indexRowsToParquet(index: V4Index, rows: readonly V4IndexRow[], rowGroupSize: number): Promise<Buffer> {
    const columns = INDEX_COLUMNS[index]
    return parquetRecordsToBuffer(
        SCHEMAS[index],
        inFileOrder(index, rows).map((row) => toRecord(row, columns)),
        { rowGroupSize }
    )
}
