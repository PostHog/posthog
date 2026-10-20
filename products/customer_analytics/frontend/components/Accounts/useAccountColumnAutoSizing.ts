import { RefObject, useLayoutEffect, useMemo, useRef, useState } from 'react'

import { objectsEqual } from 'lib/utils/objects'

import { QueryContextColumn } from '~/queries/types'

const MIN_AUTO_COLUMN_WIDTH = 80
const MAX_AUTO_COLUMN_WIDTH = 200
const MAX_SAMPLED_BODY_CELLS = 6
const MAX_RANKED_BODY_CELLS = 40
const SORT_CONTROL_ATTRIBUTE_PREFIX = 'accounts-table-sort-'

type ColumnMeasurement = {
    columnName: string
    header: HTMLTableCellElement
    bodyCells: HTMLTableCellElement[]
    signature: string
}

type WidthCacheEntry = {
    signature: string
    width: number
}

type BodyCellRankingMetadata = {
    index: number
    normalizedTextLength: number
    descendantElementCount: number
}

function getNormalizedTextLength(cell: HTMLTableCellElement): number {
    return (cell.textContent ?? '').replace(/\s+/g, ' ').trim().length
}

function getBodyCellRankingMetadata(cell: HTMLTableCellElement, index: number): BodyCellRankingMetadata {
    return {
        index,
        normalizedTextLength: getNormalizedTextLength(cell),
        descendantElementCount: cell.querySelectorAll('*').length,
    }
}

function getRankedBodyCellIndexes(cellCount: number): number[] {
    if (cellCount <= MAX_RANKED_BODY_CELLS) {
        return Array.from({ length: cellCount }, (_, index) => index)
    }

    const cellsPerBoundary = MAX_RANKED_BODY_CELLS / 2
    return [
        ...Array.from({ length: cellsPerBoundary }, (_, index) => index),
        ...Array.from({ length: cellsPerBoundary }, (_, index) => cellCount - cellsPerBoundary + index),
    ]
}

function selectBodyCellsForMeasurement(cells: HTMLTableCellElement[]): HTMLTableCellElement[] {
    if (cells.length <= MAX_SAMPLED_BODY_CELLS) {
        return cells
    }

    const selectedIndexes = new Set([0, cells.length - 1])
    const candidateMetadata = getRankedBodyCellIndexes(cells.length).map((index) =>
        getBodyCellRankingMetadata(cells[index], index)
    )
    const candidatesByTextLength = [...candidateMetadata].sort(
        (left, right) => right.normalizedTextLength - left.normalizedTextLength || left.index - right.index
    )
    const candidatesByElementCount = [...candidateMetadata].sort(
        (left, right) => right.descendantElementCount - left.descendantElementCount || left.index - right.index
    )
    const candidateRankings = [candidatesByTextLength, candidatesByElementCount]

    // Boundary candidates cover appended pages. The rankings favor long text and compound renderers without cloning every row.
    for (let rank = 0; selectedIndexes.size < MAX_SAMPLED_BODY_CELLS; rank++) {
        for (const ranking of candidateRankings) {
            const candidate = ranking[rank]
            if (candidate !== undefined) {
                selectedIndexes.add(candidate.index)
            }
            if (selectedIndexes.size === MAX_SAMPLED_BODY_CELLS) {
                break
            }
        }
    }

    return [...selectedIndexes].sort((left, right) => left - right).map((index) => cells[index])
}

function measurementSignature(header: HTMLTableCellElement, bodyCells: HTMLTableCellElement[]): string {
    return [header, ...bodyCells].map((cell) => `${cell.className}:${cell.innerHTML}`).join('\u0000')
}

function getColumnMeasurements(table: HTMLTableElement, columnNames: Set<string>): ColumnMeasurement[] {
    const headerRow = Array.from(table.tHead?.rows ?? []).find((row) =>
        row.querySelector(`[data-attr^="${SORT_CONTROL_ATTRIBUTE_PREFIX}"]`)
    )
    if (!headerRow) {
        return []
    }

    const measurements: ColumnMeasurement[] = []
    for (const header of Array.from(headerRow.cells)) {
        const sortControl = header.querySelector<HTMLElement>(`[data-attr^="${SORT_CONTROL_ATTRIBUTE_PREFIX}"]`)
        const attribute = sortControl?.getAttribute('data-attr')
        const columnName = attribute?.startsWith(SORT_CONTROL_ATTRIBUTE_PREFIX)
            ? attribute.slice(SORT_CONTROL_ATTRIBUTE_PREFIX.length)
            : undefined
        if (!columnName || !columnNames.has(columnName)) {
            continue
        }

        const cells: HTMLTableCellElement[] = []
        for (const body of Array.from(table.tBodies)) {
            for (const row of Array.from(body.rows)) {
                if (row.classList.contains('LemonTable__expansion')) {
                    continue
                }
                const cell = row.cells.item(header.cellIndex)
                if (cell && cell.colSpan === 1) {
                    cells.push(cell)
                }
            }
        }
        const bodyCells = selectBodyCellsForMeasurement(cells)
        measurements.push({
            columnName,
            header,
            bodyCells,
            signature: measurementSignature(header, bodyCells),
        })
    }
    return measurements
}

function cloneMeasurementCell(cell: HTMLTableCellElement): HTMLTableCellElement {
    const clone = cell.cloneNode(true) as HTMLTableCellElement
    clone.removeAttribute('style')
    clone.style.maxWidth = 'none'
    clone.style.whiteSpace = 'nowrap'
    clone.removeAttribute('id')
    clone.querySelectorAll('[id]').forEach((element) => element.removeAttribute('id'))
    return clone
}

function measureColumns(table: HTMLTableElement, measurements: ColumnMeasurement[]): Record<string, number> {
    const measurementTable = document.createElement('table')
    measurementTable.className = table.className
    measurementTable.removeAttribute('style')
    measurementTable.classList.remove('table-fixed')
    measurementTable.classList.add('fixed', 'invisible', 'pointer-events-none', 'table-auto', 'w-max!', 'min-w-0')
    measurementTable.inert = true
    measurementTable.setAttribute('aria-hidden', 'true')

    const sourceHeaderCells = Array.from(measurements[0]?.header.parentElement?.children ?? []).filter(
        (cell): cell is HTMLTableCellElement => cell instanceof HTMLTableCellElement
    )
    const measurementsByHeader = new Map(measurements.map((measurement) => [measurement.header, measurement]))
    const headerRow = measurementTable.createTHead().insertRow()
    for (const header of sourceHeaderCells) {
        headerRow.appendChild(cloneMeasurementCell(header))
    }

    const body = measurementTable.createTBody()
    const sampleCount = Math.max(...measurements.map(({ bodyCells }) => bodyCells.length), 0)
    for (let sampleIndex = 0; sampleIndex < sampleCount; sampleIndex++) {
        const row = body.insertRow()
        for (const header of sourceHeaderCells) {
            const cell = measurementsByHeader.get(header)?.bodyCells[sampleIndex]
            row.appendChild(cell ? cloneMeasurementCell(cell) : document.createElement('td'))
        }
    }

    table.parentElement?.appendChild(measurementTable)
    try {
        return Object.fromEntries(
            measurements.map(({ columnName, header }) => [
                columnName,
                Math.min(
                    MAX_AUTO_COLUMN_WIDTH,
                    Math.max(
                        MIN_AUTO_COLUMN_WIDTH,
                        Math.ceil(headerRow.cells[header.cellIndex].getBoundingClientRect().width)
                    )
                ),
            ])
        )
    } finally {
        measurementTable.remove()
    }
}

function getContentWidths(
    table: HTMLTableElement,
    columnNames: string[],
    widthCache: Map<string, WidthCacheEntry>
): Record<string, number> {
    const measurements = getColumnMeasurements(table, new Set(columnNames))
    const widths: Record<string, number> = {}
    const changedMeasurements: ColumnMeasurement[] = []

    for (const measurement of measurements) {
        const cached = widthCache.get(measurement.columnName)
        if (cached?.signature === measurement.signature) {
            widths[measurement.columnName] = cached.width
        } else {
            changedMeasurements.push(measurement)
        }
    }

    const measuredWidths = changedMeasurements.length > 0 ? measureColumns(table, changedMeasurements) : {}
    for (const measurement of changedMeasurements) {
        const width = measuredWidths[measurement.columnName]
        widths[measurement.columnName] = width
        widthCache.set(measurement.columnName, { signature: measurement.signature, width })
    }
    return widths
}

export function useAccountColumnAutoSizing(
    columns: Record<string, QueryContextColumn>,
    response: unknown,
    loading: boolean
): {
    tableRef: RefObject<HTMLDivElement>
    columns: Record<string, QueryContextColumn>
    hasAutoSizedColumns: boolean
} {
    const tableRef = useRef<HTMLDivElement>(null)
    const widthCache = useRef(new Map<string, WidthCacheEntry>())
    const [contentWidths, setContentWidths] = useState<Record<string, number>>({})

    useLayoutEffect(() => {
        const table = tableRef.current?.querySelector<HTMLTableElement>('.LemonTable__content > table')
        const columnNames = Object.keys(columns).filter((key) => columns[key].width === undefined)
        if (!table || loading || response === null || response === undefined || columnNames.length === 0) {
            return
        }
        const widths = getContentWidths(table, columnNames, widthCache.current)
        setContentWidths((previous) => {
            const next = { ...previous, ...widths }
            return objectsEqual(previous, next) ? previous : next
        })
    }, [columns, response, loading])

    const sizedColumns = useMemo(
        () =>
            Object.fromEntries(
                Object.entries(columns).map(([key, column]) => [
                    key,
                    { ...column, width: column.width ?? contentWidths[key] },
                ])
            ),
        [columns, contentWidths]
    )

    return {
        tableRef,
        columns: sizedColumns,
        hasAutoSizedColumns: Object.keys(columns).some(
            (key) => columns[key].width === undefined && contentWidths[key] !== undefined
        ),
    }
}
