import type { DotMatrixCell } from 'lib/components/DotMatrix/types'
import { hashCodeForString } from 'lib/utils/strings'

import type { HogQLQueryResponse } from '~/queries/schema/schema-general'

import type { AccountActivityMatrixDatum, AccountActivityMatrixProps } from './accountActivityMatrix'
import type { DotMatrixSourceMapping } from './dotMatrixTileConfig'

export const DEFAULT_MATRIX_QUERY: string = `SELECT
    person_id AS row,
    coalesce(nullIf(person.properties.email, ''), nullIf(person.properties.name, ''), toString(person_id)) AS row_label,
    toString(toStartOfWeek(timestamp, {week_start_day})) AS column,
    event AS series,
    count() AS value
FROM events
WHERE {filters}
GROUP BY row, row_label, column, series
ORDER BY column DESC, row, series
LIMIT 1000`

export const DEFAULT_MATRIX_MAPPING: DotMatrixSourceMapping = {
    row: 'row',
    rowLabel: 'row_label',
    column: 'column',
    series: 'series',
    value: 'value',
}

export function inferHogQLMatrixMapping(columns: string[], mapping: DotMatrixSourceMapping): DotMatrixSourceMapping {
    if (columns.includes(mapping.row) && columns.includes(mapping.column)) {
        return Object.fromEntries(
            Object.entries(mapping).filter(([, name]) => columns.includes(name))
        ) as unknown as DotMatrixSourceMapping
    }
    const named = (...names: string[]): string | undefined =>
        columns.find((column) => names.includes(column.toLowerCase()))
    const row = named('row', 'person', 'person_id', 'user', 'user_id', 'account', 'account_id') ?? columns[0] ?? ''
    const column =
        named('column', 'week', 'date', 'day', 'month', 'bucket', 'period', 'timestamp') ??
        columns.find((name) => name !== row) ??
        ''
    const rowLabel = named('row_label', 'email', 'name', 'label')
    const remaining = columns.filter((name) => name !== row && name !== column && name !== rowLabel)
    const series =
        named('series', 'feature', 'product', 'event', 'category') ?? (remaining.length >= 2 ? remaining[0] : undefined)
    const value = named('value', 'amount', 'count', 'total', 'users') ?? remaining.find((name) => name !== series)
    return {
        row,
        column,
        ...(rowLabel ? { rowLabel } : {}),
        ...(series ? { series } : {}),
        ...(value ? { value } : {}),
    }
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

const SERIES_KEY_MAX_LENGTH = 128

// Saved selections reject keys over 128 characters. Keys must stay stable across runs for a selection to keep applying.
function getSeriesAxisItem(value: string): { key: string; label?: string } {
    if (value.length <= SERIES_KEY_MAX_LENGTH) {
        return { key: value }
    }
    return {
        key: `${value.slice(0, 100)}~${value.length.toString(36)}~${hashCodeForString(value).toString(36)}`,
        label: `${value.slice(0, SERIES_KEY_MAX_LENGTH - 1)}…`,
    }
}

const ISO_DATE = /^\d{4}-\d{2}(-\d{2}([T ]\d{2}:\d{2}(:\d{2}(\.\d+)?)?(Z|[+-]\d{2}(:?\d{2})?)?)?)?$/
const NUMBER = /^-?\d+(\.\d+)?$/

function getSortValue(key: string): number {
    return NUMBER.test(key) ? Number(key) : ISO_DATE.test(key) ? Date.parse(key.replace(' ', 'T')) : NaN
}

// Numbers and ISO dates read left to right in time order. Anything else keeps the order the query chose.
function getSortedColumns(keys: string[]): string[] | null {
    const allNumbers = keys.every((key) => NUMBER.test(key))
    const allDates = keys.every((key) => ISO_DATE.test(key))
    const values = new Map(keys.map((key) => [key, getSortValue(key)]))
    if ((!allNumbers && !allDates) || [...values.values()].some(Number.isNaN)) {
        return null
    }
    return [...keys].sort((first, second) => values.get(first)! - values.get(second)!)
}

const LIMIT_TOKENS = /'(?:[^'\\]|\\.)*'|"(?:[^"\\]|\\.)*"|`(?:[^`\\]|\\.)*`|--[^\n]*|\/\*[\s\S]*?\*\/|[(),]|[\w.]+/g

// The outermost LIMIT count, skipping strings, comments, subqueries and LIMIT n BY.
function getOuterLimit(query: string): number | null {
    let depth = 0
    const outer: string[] = []
    for (const [token] of query.matchAll(LIMIT_TOKENS)) {
        if (token === '(' || token === ')') {
            depth += token === '(' ? 1 : -1
        } else if (depth === 0 && !/^(?:['"`]|--|\/\*)/.test(token)) {
            outer.push(token.toUpperCase())
        }
    }
    const start = outer.lastIndexOf('LIMIT')
    if (start === -1) {
        return null
    }
    const [first, next, second, afterSecond] = outer.slice(start + 1)
    const count = next === ',' ? second : first
    const following = next === ',' ? afterSecond : next
    return /^\d+$/.test(count ?? '') && following !== 'BY' ? Number(count) : null
}

// hasMore is only set when the server added its own LIMIT, so a query's explicit LIMIT has to be read here.
// It's a heuristic: a result of exactly LIMIT rows may also be complete, so the wording stays "may".
export function getHogQLLimitNotice(response: HogQLQueryResponse, query: string): string | null {
    const limit = getOuterLimit(response.hogql ?? query)
    return limit !== null && limit > 0 && response.results.length === limit
        ? `The query returned exactly its LIMIT of ${limit} rows, so some data may be missing. Raise the LIMIT to check.`
        : null
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

type PeopleByCell = Map<string, Map<string, Set<string>>>

function countPeople(
    people: PeopleByCell,
    cell: DotMatrixCell<AccountActivityMatrixDatum>,
    selected?: string[]
): number {
    const seen = new Set<string>()
    for (const [series, users] of people.get(JSON.stringify([cell.rowKey, cell.columnKey])) ?? []) {
        if (!selected || selected.includes(series)) {
            users.forEach((user) => seen.add(user))
        }
    }
    return seen.size
}

function getLegend(mapping: DotMatrixSourceMapping): AccountActivityMatrixProps['legend'] {
    const showing = (count: number): string => `Showing ${count} series`
    if (mapping.user) {
        return {
            itemLabel: 'series',
            valueLabel: mapping.value ?? 'People',
            countLabel: 'People',
            selectionLabel: (count, mode) => (mode === 'count' ? `People in ${count} selected series` : showing(count)),
        }
    }
    // A generic value can't be deduplicated, so the label says what the number is: a sum.
    const name = mapping.value ?? 'rows'
    return {
        itemLabel: 'series',
        valueLabel: mapping.value ?? 'Rows',
        countLabel: `Sum of ${name}`,
        selectionLabel: (count, mode) =>
            mode === 'count'
                ? `Sum of ${name} across ${count} series. Map a user column to count each person once.`
                : showing(count),
    }
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
    const people: PeopleByCell = new Map()
    let skipped = 0
    const rowKeys = new Set<string>()
    const rowLabels = new Map<string, string>()
    const columnKeys = new Set<string>()
    const seriesItems = new Map<string, { key: string; label?: string }>()
    for (const record of response.results) {
        const row = axisKey(record[index(mapping.row)])
        const column = axisKey(record[index(mapping.column)])
        const seriesValue = mapping.series ? axisKey(record[index(mapping.series)]) : 'value'
        const value = mapping.value ? record[index(mapping.value)] : 1
        const user = mapping.user ? axisKey(record[index(mapping.user)]) : null
        if (
            row === null ||
            column === null ||
            seriesValue === null ||
            (mapping.user && user === null) ||
            typeof value !== 'number' ||
            !Number.isFinite(value) ||
            value < 0
        ) {
            skipped += 1
            continue
        }
        rowKeys.add(row)
        if (mapping.rowLabel) {
            rowLabels.set(row, axisKey(record[index(mapping.rowLabel)]) ?? rowLabels.get(row) ?? row)
        }
        columnKeys.add(column)
        const seriesItem = getSeriesAxisItem(seriesValue)
        const series = seriesItem.key
        seriesItems.set(series, seriesItem)
        const key = JSON.stringify([row, column, series])
        const previous = cells.get(key)
        let users: Set<string> | undefined
        if (user !== null) {
            const cellKey = JSON.stringify([row, column])
            const cellPeople = people.get(cellKey) ?? new Map<string, Set<string>>()
            people.set(cellKey, cellPeople)
            users = cellPeople.get(series) ?? new Set<string>()
            cellPeople.set(series, users)
            if (value > 0) {
                users.add(user)
            }
        }
        const total = users && !mapping.value ? users.size : (previous?.value ?? 0) + value
        cells.set(key, { row, column, series, value: total })
    }
    if (skipped > 0 && skipped === response.results.length) {
        return {
            props: null,
            error: 'Rows, columns and series need non-empty text or numbers. Values need finite, non-negative numbers.',
            notices: [],
        }
    }
    const rows = [...rowKeys].slice(0, DOT_MATRIX_MAX_ROWS)
    const sortedColumns = getSortedColumns([...columnKeys])
    const columns = sortedColumns
        ? sortedColumns.slice(-DOT_MATRIX_MAX_COLUMNS)
        : [...columnKeys].slice(0, DOT_MATRIX_MAX_COLUMNS)
    const series = [...seriesItems.values()].slice(0, DOT_MATRIX_MAX_SERIES)
    const shownRows = new Set(rows)
    const shownColumns = new Set(columns)
    const shownSeries = new Set(series.map(({ key }) => key))
    const data = [...cells.values()].filter(
        (cell) => shownRows.has(cell.row) && shownColumns.has(cell.column) && shownSeries.has(cell.series)
    )
    const boundNotice = getBoundNotice([
        { noun: 'rows', shown: rows.length, total: rowKeys.size },
        { noun: 'columns', shown: columns.length, total: columnKeys.size },
        { noun: 'series', shown: series.length, total: seriesItems.size },
    ])
    return {
        error: null,
        notices: [
            ...(skipped
                ? [`Skipped ${skipped} result ${skipped === 1 ? 'row' : 'rows'} with a missing or invalid value.`]
                : []),
            ...(boundNotice ? [boundNotice] : []),
        ],
        props: {
            data,
            rows: rows.map((key) => ({ key, ...(mapping.rowLabel ? { label: rowLabels.get(key) ?? key } : {}) })),
            columns: columns.map((key) => ({ key })),
            series,
            fields: { row: 'row', column: 'column', series: 'series', value: 'value' },
            rowHeader: {
                title:
                    mapping.rowLabel === 'row_label'
                        ? 'Person'
                        : (mapping.rowLabel ?? mapping.row)
                              .replace(/_/g, ' ')
                              .replace(/^./, (letter) => letter.toUpperCase()),
            },
            sizeThresholds: [data.reduce((min, { value }) => (value > 0 ? Math.min(min, value) : min), 1), 5, 10],
            aggregateSelection: mapping.user
                ? (cell, selected) => countPeople(people, cell, selected)
                : (cell, selected) => selected.reduce((sum, key) => sum + (cell.values[key] ?? 0), 0),
            ...(mapping.user ? { countOf: (cell) => countPeople(people, cell) } : {}),
            legend: getLegend(mapping),
        },
    }
}
