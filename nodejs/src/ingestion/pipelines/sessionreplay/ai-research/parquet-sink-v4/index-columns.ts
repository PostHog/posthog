/**
 * The columns of the two v4 index files, in file order, with parquetjs types. This table drives the row validator and
 * the Parquet writer, as `ml-mirror/block-metadata-columns.ts` does for v3. Kept free of the Parquet dependency so the
 * message-parsing path does not pull it in.
 */

export type V4Index = 'blocks' | 'images'

export type ParquetType = 'UTF8' | 'BOOLEAN' | 'INT32' | 'INT64'

export interface V4LeafColumn {
    name: string
    type: ParquetType
    /** Nullable column: it can be null or absent on a row. */
    optional?: boolean
    /** Sealed bytes with no useful order. Min and max statistics would copy each long value into the file metadata. */
    opaque?: boolean
}

/** A repeated group of required leaves; Parquet readers see it as a non-null list of structs. */
export interface V4RepeatedColumn {
    name: string
    repeated: true
    fields: readonly V4LeafColumn[]
}

/** A repeated leaf; Parquet readers see it as a non-null list of non-null values. */
export interface V4ListColumn {
    name: string
    list: ParquetType
}

export type V4Column = V4LeafColumn | V4RepeatedColumn | V4ListColumn

const required = (type: ParquetType, ...names: string[]): V4LeafColumn[] => names.map((name) => ({ name, type }))
const optional = (type: ParquetType, ...names: string[]): V4LeafColumn[] =>
    names.map((name) => ({ name, type, optional: true }))

export const MOMENT_COLUMNS: readonly V4LeafColumn[] = [
    ...required('UTF8', 'kind', 'window_id'),
    ...required('INT64', 'ts_ms'),
    ...required('INT32', 'event_index'),
]

export const IMAGE_INDEX_COLUMNS: readonly V4Column[] = [
    ...required('INT64', 'team_id'),
    ...required('UTF8', 'key_month', 'image_ref', 'pack_s3_key'),
    ...required('INT64', 'byte_start', 'byte_end'),
    ...required('UTF8', 'mime'),
    ...required('INT64', 'byte_size'),
]

export const BLOCK_INDEX_COLUMNS: readonly V4Column[] = [
    ...required('INT64', 'team_id'),
    ...required('UTF8', 'session_id', 'key_month', 'block_s3_key', 'topic'),
    ...required('INT32', 'partition'),
    ...required('INT64', 'start_offset', 'end_offset', 'flush_end_offset'),
    ...required('INT32', 'flush_row_count', 'flush_row_index'),
    ...required('UTF8', 'flush_id'),
    ...required('INT64', 'flushed_at_ms', 'block_byte_start', 'block_byte_end'),
    ...optional('INT64', 'first_ts_ms', 'last_ts_ms'),
    ...required('INT64', 'event_count', 'byte_size'),
    ...optional('UTF8', 'snapshot_source', 'snapshot_library', 'host'),
    ...required(
        'INT32',
        'full_snapshots',
        'events_before_first_full_snapshot',
        'orphan_mutations',
        'decode_failures',
        'dom_nodes',
        'remote_stylesheets',
        'inline_stylesheets',
        'iframes',
        'canvases',
        'videos',
        'shadow_roots'
    ),
    ...required('INT64', 'max_gap_ms', 'active_ms', 'dom_text_chars'),
    ...required('BOOLEAN', 'cold_start', 'node_cap_reached', 'moments_truncated', 'touch_input'),
    ...required(
        'INT32',
        'clicks',
        'mouse_interactions',
        'rage_clicks',
        'dead_clicks',
        'keypresses',
        'scrolls',
        'mouse_moves',
        'touches',
        'touch_moves',
        'selections',
        'media_events',
        'viewport_resizes',
        'navigations',
        'console_errors',
        'console_warnings',
        'network_requests',
        'network_failures',
        'images_extracted',
        'images_inline',
        'image_urls'
    ),
    ...required('INT64', 'image_bytes', 'written_jsonl_bytes', 'max_written_event_bytes'),
    ...optional('INT32', 'viewport_width', 'viewport_height'),
    ...optional('INT64', 'viewport_ts_ms'),
    { name: 'moments', repeated: true, fields: MOMENT_COLUMNS },
    { name: 'url_fingerprints', list: 'UTF8' },
    { name: 'window_ids', list: 'UTF8' },
    { name: 'urls', type: 'UTF8', optional: true, opaque: true },
    ...required('BOOLEAN', 'urls_truncated'),
]

export const INDEX_COLUMNS: Record<V4Index, readonly V4Column[]> = {
    blocks: BLOCK_INDEX_COLUMNS,
    images: IMAGE_INDEX_COLUMNS,
}

export type V4IndexRow = Record<string, unknown>

const INT32_MIN = -(2 ** 31)
const INT32_MAX = 2 ** 31 - 1

// JSON numbers above 2^53 lose precision on parse, so an INT64 column takes only safe integers.
function isEncodableValue(type: ParquetType, value: unknown): boolean {
    switch (type) {
        case 'UTF8':
            return typeof value === 'string'
        case 'BOOLEAN':
            return typeof value === 'boolean'
        case 'INT32':
            return Number.isInteger(value) && (value as number) >= INT32_MIN && (value as number) <= INT32_MAX
        case 'INT64':
            return Number.isSafeInteger(value)
    }
}

/** The selected columns of a row, or the first column whose value is missing or does not fit its type. */
export type IndexRowSelection = { row: V4IndexRow } | { invalidColumn: string }

function selectColumns(value: unknown, columns: readonly V4Column[], prefix = ''): IndexRowSelection {
    if (typeof value !== 'object' || value === null || Array.isArray(value)) {
        return { invalidColumn: prefix ? prefix.slice(0, -1) : 'row' }
    }
    const source = value as Record<string, unknown>
    const row: V4IndexRow = {}
    for (const column of columns) {
        const field = source[column.name]
        const invalid = { invalidColumn: `${prefix}${column.name}` }
        if ('repeated' in column) {
            if (!Array.isArray(field)) {
                return invalid
            }
            const items: V4IndexRow[] = []
            for (const item of field) {
                const selected = selectColumns(item, column.fields, `${prefix}${column.name}.`)
                if (!('row' in selected)) {
                    return selected
                }
                items.push(selected.row)
            }
            row[column.name] = items
        } else if ('list' in column) {
            if (!Array.isArray(field) || !field.every((item) => isEncodableValue(column.list, item))) {
                return invalid
            }
            row[column.name] = field
        } else if (field === null || field === undefined) {
            if (!column.optional) {
                return invalid
            }
            row[column.name] = null
        } else if (isEncodableValue(column.type, field)) {
            row[column.name] = field
        } else {
            return invalid
        }
    }
    return { row }
}

/**
 * Returns the row's index columns, or the first column that is missing or does not fit its type. Keys that are not
 * columns are left out, as the v3 sink does. A bad row must not reach the writer, which would fail the whole flush.
 */
export function selectIndexRow(index: V4Index, value: unknown): IndexRowSelection {
    return selectColumns(value, INDEX_COLUMNS[index])
}
