import type { HogQLQueryResponse } from '~/queries/schema/schema-general'

import type { AccountActivityMatrixDatum, AccountActivityMatrixProps } from './accountActivityMatrix'
import type { DotMatrixSourceMapping } from './dotMatrixTileConfig'

export const DEFAULT_MATRIX_QUERY: string = `SELECT
    person_id AS row,
    toString(toStartOfWeek(timestamp)) AS column,
    event AS series,
    count() AS value
FROM events
WHERE {filters}
GROUP BY row, column, series
ORDER BY column, row, series
LIMIT 1000`

export const DEFAULT_MATRIX_MAPPING: DotMatrixSourceMapping = {
    row: 'row',
    column: 'column',
    series: 'series',
    value: 'value',
}

// normalizeDotMatrixData allocates rows x columns cells, so these bound the work before any rendering.
export const DOT_MATRIX_MAX_ROWS = 500
export const DOT_MATRIX_MAX_COLUMNS = 104
// The saved selection accepts up to 64 series keys.
export const DOT_MATRIX_MAX_SERIES = 64

export function getHogQLMappingError(response: HogQLQueryResponse, mapping: DotMatrixSourceMapping): string | null {
    const columns = response.columns ?? []
    if (!columns.length || columns.some((name) => typeof name !== 'string' || !name || name.length > 128)) {
        return 'Give each result column a name of up to 128 characters with AS, then run the query again.'
    }
    if (new Set(columns).size !== columns.length) {
        return 'Give each result column a unique name with AS, then run the query again.'
    }
    if (!mapping.row || !mapping.column) {
        return 'Choose the row and column fields.'
    }
    if (Object.values(mapping).some((name) => !columns.includes(name))) {
        return 'A mapped column is missing from the result. Update the mapping.'
    }
    return null
}

function getBoundNotice(axes: { noun: string; shown: number; total: number }[]): string | null {
    const parts = axes
        .filter(({ shown, total }) => shown < total)
        .map(({ noun, shown, total }) => `${shown} of ${total} ${noun}`)
    if (!parts.length) {
        return null
    }
    const list = parts.length > 1 ? `${parts.slice(0, -1).join(', ')} and ${parts[parts.length - 1]}` : parts[0]
    return `Showing ${list}. Narrow the query to see the rest.`
}

function axisKey(value: unknown): string | null {
    return (typeof value === 'string' && value.length > 0) || (typeof value === 'number' && Number.isFinite(value))
        ? String(value)
        : null
}

export function getHogQLActivityMatrix(
    response: HogQLQueryResponse,
    mapping: DotMatrixSourceMapping
): { props: AccountActivityMatrixProps | null; error: string | null; notices: string[] } {
    const error = getHogQLMappingError(response, mapping)
    if (error) {
        return { props: null, error, notices: [] }
    }
    const index = (name: string): number => response.columns!.indexOf(name)
    const cells = new Map<string, AccountActivityMatrixDatum>()
    const rowKeys = new Set<string>()
    const columnKeys = new Set<string>()
    const seriesKeys = new Set<string>()
    for (const record of response.results) {
        const row = axisKey(record[index(mapping.row)])
        const column = axisKey(record[index(mapping.column)])
        const series = mapping.series ? axisKey(record[index(mapping.series)]) : 'value'
        const value = mapping.value ? record[index(mapping.value)] : 1
        if (
            row === null ||
            column === null ||
            series === null ||
            typeof value !== 'number' ||
            !Number.isFinite(value) ||
            value < 0
        ) {
            return {
                props: null,
                error: 'Rows, columns and series need non-empty text or numbers. Values need finite, non-negative numbers.',
                notices: [],
            }
        }
        rowKeys.add(row)
        columnKeys.add(column)
        seriesKeys.add(series)
        const key = JSON.stringify([row, column, series])
        const previous = cells.get(key)
        cells.set(key, { row, column, series, value: (previous?.value ?? 0) + value })
    }
    const rows = [...rowKeys].slice(0, DOT_MATRIX_MAX_ROWS)
    const columns = [...columnKeys].slice(0, DOT_MATRIX_MAX_COLUMNS)
    const series = [...seriesKeys].slice(0, DOT_MATRIX_MAX_SERIES)
    const shownRows = new Set(rows)
    const shownColumns = new Set(columns)
    const shownSeries = new Set(series)
    const data = [...cells.values()].filter(
        (cell) => shownRows.has(cell.row) && shownColumns.has(cell.column) && shownSeries.has(cell.series)
    )
    const boundNotice = getBoundNotice([
        { noun: 'rows', shown: rows.length, total: rowKeys.size },
        { noun: 'columns', shown: columns.length, total: columnKeys.size },
        { noun: 'series', shown: series.length, total: seriesKeys.size },
    ])
    return {
        error: null,
        notices: boundNotice ? [boundNotice] : [],
        props: {
            data,
            rows: rows.map((key) => ({ key })),
            columns: columns.map((key) => ({ key })),
            series: series.map((key) => ({ key })),
            fields: { row: 'row', column: 'column', series: 'series', value: 'value' },
            rowHeader: { title: mapping.row },
            sizeThresholds: [data.reduce((min, { value }) => (value > 0 ? Math.min(min, value) : min), 1), 5, 10],
            aggregateSelection: (cell, selected) => selected.reduce((sum, key) => sum + (cell.values[key] ?? 0), 0),
            legend: { itemLabel: 'series', valueLabel: mapping.value ?? 'Rows', countLabel: 'Total value' },
        },
    }
}
