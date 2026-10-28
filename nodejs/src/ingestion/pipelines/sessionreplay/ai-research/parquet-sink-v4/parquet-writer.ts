/** Encodes v4 index rows into a Snappy-compressed Parquet buffer, with the types of the COLUMNS table. */
import { ParquetSchema } from '@dsnp/parquetjs'

import { INDEX_COLUMNS, ParquetType, V4Column, V4Index, V4IndexRow } from './index-columns'
import { parquetRecordsToBuffer } from './parquet-buffer'

type SchemaDef = ConstructorParameters<typeof ParquetSchema>[0]

// Snappy on every column: compression is a per-field option in parquetjs, not a writer option.
function schemaDef(columns: readonly V4Column[]): SchemaDef {
    const def: Record<string, unknown> = {}
    for (const column of columns) {
        if ('repeated' in column) {
            def[column.name] = { repeated: true, fields: schemaDef(column.fields) }
        } else if ('list' in column) {
            def[column.name] = { type: column.list, repeated: true, compression: 'SNAPPY' }
        } else {
            def[column.name] = {
                type: column.type,
                compression: 'SNAPPY',
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

function toValue(type: ParquetType, value: unknown): unknown {
    return type === 'INT64' ? BigInt(value as number) : value
}

function toRecord(row: V4IndexRow, columns: readonly V4Column[]): Record<string, unknown> {
    const record: Record<string, unknown> = {}
    for (const column of columns) {
        const value = row[column.name]
        if ('repeated' in column) {
            record[column.name] = (value as V4IndexRow[]).map((item) => toRecord(item, column.fields))
        } else if ('list' in column) {
            record[column.name] = (value as unknown[]).map((item) => toValue(column.list, item))
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
        rows.map((row) => toRecord(row, columns)),
        { rowGroupSize }
    )
}
