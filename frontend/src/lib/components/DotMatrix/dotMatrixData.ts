import { DOT_MATRIX_SIZE_THRESHOLDS } from './dotMatrixPresentation'
import type {
    DotMatrixAxisItem,
    DotMatrixCell,
    DotMatrixCountBin,
    DotMatrixCountOptions,
    DotMatrixData,
    DotMatrixDataOptions,
    DotMatrixField,
} from './types'

function readField<D extends Record<string, unknown>>(datum: D, field: DotMatrixField<D>): unknown {
    return typeof field === 'function' ? field(datum) : datum[field]
}

function fieldKey(value: unknown): string | null {
    return typeof value === 'string' || (typeof value === 'number' && Number.isFinite(value)) ? String(value) : null
}

function fieldValue(value: unknown): number | null {
    if (typeof value !== 'number' && (typeof value !== 'string' || value.trim() === '')) {
        return null
    }
    const number = Number(value)
    return Number.isFinite(number) ? number : null
}

function axisIndex<T extends DotMatrixAxisItem>(items: T[] | undefined): Map<string, T> {
    const index = new Map<string, T>()
    for (const item of items ?? []) {
        if (!index.has(item.key)) {
            index.set(item.key, item)
        }
    }
    return index
}

function emptyCell<D>(rowKey: string, columnKey: string): DotMatrixCell<D> {
    return { rowKey, columnKey, values: Object.create(null) as Record<string, number>, data: [] }
}

export function normalizeDotMatrixData<D extends Record<string, unknown>>({
    data,
    fields,
    rows,
    columns,
    series,
}: DotMatrixDataOptions<D>): DotMatrixData<D> {
    const rowIndex = axisIndex(rows)
    const columnIndex = axisIndex(columns)
    const seriesIndex = axisIndex(series)
    const cells = new Map<string, Map<string, DotMatrixCell<D>>>()

    for (const datum of data) {
        const rowKey = fieldKey(readField(datum, fields.row))
        const columnKey = fieldKey(readField(datum, fields.column))
        const seriesKey = fields.series !== undefined ? fieldKey(readField(datum, fields.series)) : ''
        const value = fieldValue(readField(datum, fields.value))
        if (rowKey === null || columnKey === null || seriesKey === null || value === null) {
            continue
        }

        // Explicit axes define order and labels; new keys stay visible in first-seen order.
        if (!rowIndex.has(rowKey)) {
            rowIndex.set(rowKey, { key: rowKey })
        }
        if (!columnIndex.has(columnKey)) {
            columnIndex.set(columnKey, { key: columnKey })
        }
        if (fields.series !== undefined && !seriesIndex.has(seriesKey)) {
            seriesIndex.set(seriesKey, { key: seriesKey })
        }

        let rowCells = cells.get(rowKey)
        if (!rowCells) {
            rowCells = new Map()
            cells.set(rowKey, rowCells)
        }
        let cell = rowCells.get(columnKey)
        if (!cell) {
            cell = emptyCell(rowKey, columnKey)
            rowCells.set(columnKey, cell)
        }

        // Counts may already be aggregated, so duplicate slots replace rather than add.
        cell.values[seriesKey] = value
        cell.data.push(datum)
    }

    return {
        rows: Array.from(rowIndex.values()),
        columns: Array.from(columnIndex.values()),
        series: Array.from(seriesIndex.values()),
        cells,
        getCell: (rowKey, columnKey) => cells.get(rowKey)?.get(columnKey) ?? emptyCell(rowKey, columnKey),
    }
}

export function getDotMatrixCellCount<D>(
    cell: DotMatrixCell<D>,
    { countOf = 'activeSeries', selectedSeries = [], aggregateSelection }: DotMatrixCountOptions<D> = {}
): number | null {
    if (selectedSeries.length > 0) {
        if (!aggregateSelection) {
            return null
        }
        const value = aggregateSelection(cell, selectedSeries)
        return Number.isFinite(value) ? value : null
    }
    if (typeof countOf === 'function') {
        const value = countOf(cell)
        return Number.isFinite(value) ? value : null
    }
    const values = Object.values(cell.values)
    const value =
        countOf === 'value' ? values.reduce((sum, value) => sum + value, 0) : values.filter((value) => value > 0).length
    return Number.isFinite(value) ? value : null
}

export function toggleDotMatrixSeries(selected: string[], key: string, shift: boolean): string[] {
    if (!shift) {
        return [key]
    }
    return selected.includes(key) ? selected.filter((item) => item !== key) : [...new Set([...selected, key])]
}

export function normalizeDotMatrixSizeThresholds(thresholds: number[] = DOT_MATRIX_SIZE_THRESHOLDS): number[] {
    return [...new Set(thresholds.filter((threshold) => Number.isFinite(threshold) && threshold > 0))]
        .sort((first, second) => first - second)
        .slice(0, 3)
}

export function normalizeDotMatrixCountScale(scale: DotMatrixCountBin[]): DotMatrixCountBin[] {
    const bins = new Map<number, DotMatrixCountBin>()
    for (const bin of scale) {
        if (Number.isFinite(bin.min) && !bins.has(bin.min)) {
            bins.set(bin.min, bin)
        }
    }
    return [...bins.values()].sort((first, second) => first.min - second.min)
}

export function getDotMatrixCountBin(value: number, scale: DotMatrixCountBin[]): DotMatrixCountBin | undefined {
    if (!Number.isFinite(value) || value <= 0) {
        return undefined
    }
    return scale.reduce<DotMatrixCountBin | undefined>(
        (bin, candidate) =>
            Number.isFinite(candidate.min) && candidate.min <= value && (!bin || candidate.min > bin.min)
                ? candidate
                : bin,
        undefined
    )
}
