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

function axisKey(value: unknown): string | null {
    return (typeof value === 'string' && value.length > 0) || (typeof value === 'number' && Number.isFinite(value))
        ? String(value)
        : null
}

export function getHogQLActivityMatrix(
    response: HogQLQueryResponse,
    mapping: DotMatrixSourceMapping
): { props: AccountActivityMatrixProps | null; error: string | null } {
    const error = getHogQLMappingError(response, mapping)
    if (error) {
        return { props: null, error }
    }
    const index = (name: string): number => response.columns!.indexOf(name)
    const cells = new Map<string, AccountActivityMatrixDatum>()
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
            }
        }
        const key = JSON.stringify([row, column, series])
        const previous = cells.get(key)
        cells.set(key, { row, column, series, value: (previous?.value ?? 0) + value })
    }
    const data = [...cells.values()]
    return {
        error: null,
        props: {
            data,
            fields: { row: 'row', column: 'column', series: 'series', value: 'value' },
            rowHeader: { title: mapping.row },
            sizeThresholds: [data.reduce((min, { value }) => (value > 0 ? Math.min(min, value) : min), 1), 5, 10],
            aggregateSelection: (cell, selected) => selected.reduce((sum, key) => sum + (cell.values[key] ?? 0), 0),
            legend: { itemLabel: 'series', valueLabel: mapping.value ?? 'Rows', countLabel: 'Total value' },
        },
    }
}
