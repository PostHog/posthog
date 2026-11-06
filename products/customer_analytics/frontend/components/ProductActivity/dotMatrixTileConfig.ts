export const DOT_MATRIX_WEEK_OPTIONS = [4, 8, 12, 26] as const
export type DotMatrixWeeks = (typeof DOT_MATRIX_WEEK_OPTIONS)[number]
const DEFAULT_WEEKS: DotMatrixWeeks = 8

// Matches ACCOUNT_VIEW_CONFIG_MAX_BYTES in the backend's account view validation.
export const DOT_MATRIX_CONFIG_MAX_BYTES = 16_384

// The backend measures json.dumps output, which writes every UTF-16 unit outside printable ASCII as a 6-byte \\uXXXX.
export function getDotMatrixConfigBytes(config: Record<string, unknown>): number {
    const json = JSON.stringify(config)
    let bytes = 0
    for (let index = 0; index < json.length; index++) {
        bytes += json.charCodeAt(index) > 0x7e ? 6 : 1
    }
    return bytes
}

export interface DotMatrixSourceMapping {
    row: string
    rowLabel?: string
    column: string
    series?: string
    value?: string
    // Identifies a person, so people in several series are counted once.
    user?: string
}

export type DotMatrixPresetSourceKind = 'usage_metrics' | 'product_usage'

export type DotMatrixTileSource =
    | { kind: DotMatrixPresetSourceKind }
    | { kind: 'hogql'; query: string; mapping: DotMatrixSourceMapping }

export interface DotMatrixTileConfig {
    mode: 'dots' | 'count'
    weeks: DotMatrixWeeks
    selectedSeries: string[]
    source?: DotMatrixTileSource | null
}

const MAPPING_KEYS = new Set(['row', 'column', 'series', 'value', 'user', 'rowLabel'])

function isColumnName(value: unknown): value is string {
    return typeof value === 'string' && value.length > 0 && value.length <= 128
}

function getDotMatrixSourceMapping(mapping: unknown): DotMatrixSourceMapping | null {
    if (!mapping || typeof mapping !== 'object' || Array.isArray(mapping)) {
        return null
    }
    const { row, column, series, value, user, rowLabel } = mapping as Record<string, unknown>
    if (
        Object.keys(mapping).some((key) => !MAPPING_KEYS.has(key)) ||
        !isColumnName(row) ||
        !isColumnName(column) ||
        (series !== undefined && !isColumnName(series)) ||
        (value !== undefined && !isColumnName(value)) ||
        (user !== undefined && !isColumnName(user)) ||
        (rowLabel !== undefined && !isColumnName(rowLabel))
    ) {
        return null
    }
    return {
        row,
        column,
        ...(series ? { series } : {}),
        ...(value ? { value } : {}),
        ...(user ? { user } : {}),
        ...(rowLabel ? { rowLabel } : {}),
    }
}

export function getDotMatrixTileSource(source: unknown): DotMatrixTileSource | null {
    if (!source || typeof source !== 'object' || Array.isArray(source)) {
        return null
    }
    const { kind, query, mapping } = source as Record<string, unknown>
    if (kind === 'usage_metrics' || kind === 'product_usage') {
        return { kind }
    }
    if (kind !== 'hogql' || typeof query !== 'string' || !query.trim()) {
        return null
    }
    const sourceMapping = getDotMatrixSourceMapping(mapping)
    return sourceMapping ? { kind, query, mapping: sourceMapping } : null
}

export function getDotMatrixTileConfig(config?: Record<string, unknown>): DotMatrixTileConfig {
    const selectedSeries = config?.selectedSeries
    const weeks = DOT_MATRIX_WEEK_OPTIONS.find((option) => option === config?.weeks) ?? DEFAULT_WEEKS
    const source = getDotMatrixTileSource(config?.source)
    return {
        mode: config?.mode === 'count' ? 'count' : 'dots',
        weeks,
        selectedSeries:
            Array.isArray(selectedSeries) &&
            selectedSeries.length <= 64 &&
            selectedSeries.every((key) => typeof key === 'string' && key.length > 0 && key.length <= 128)
                ? [...new Set(selectedSeries)]
                : [],
        // An absent source belongs to a legacy tile; an explicit empty source must never run a query.
        ...(config && Object.hasOwn(config, 'source') ? { source } : {}),
    }
}
