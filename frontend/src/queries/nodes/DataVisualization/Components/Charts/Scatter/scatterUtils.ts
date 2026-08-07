import { ScatterSettings } from '~/queries/schema/schema-general'

export interface ScatterPoint {
    x: number
    y: number
    label: string | null
    // exact source text for the tooltip — plotting coerces to a JS number, which loses precision
    // for Int64/UInt64 aggregates beyond Number.MAX_SAFE_INTEGER
    xDisplay: string
    yDisplay: string
}

export interface ScatterData {
    points: ScatterPoint[]
    skippedRowCount: number
}

const parseNumericValue = (value: unknown): number | null => {
    if (value === null || value === undefined || (typeof value === 'string' && value.trim() === '')) {
        return null
    }

    // isFinite also rejects NaN and ±Infinity, which would wreck the axis range
    const numericValue = Number(value)
    if (!Number.isFinite(numericValue)) {
        return null
    }

    return numericValue
}

const formatDisplayValue = (value: unknown, numericValue: number): string => {
    // Int64/UInt64 columns arrive as numeric strings; keep their exact digits when the magnitude
    // exceeds the JS safe-integer range, otherwise Number(value) has already rounded them
    if (typeof value === 'string' && Math.abs(numericValue) > Number.MAX_SAFE_INTEGER) {
        return value.trim()
    }
    return numericValue.toLocaleString()
}

export const describeSkippedRows = (skippedRowCount: number, hasLogScale: boolean): string => {
    if (skippedRowCount === 0) {
        return ''
    }

    return `${skippedRowCount} row${skippedRowCount === 1 ? ' was' : 's were'} skipped because the X or Y value is missing or not numeric${
        hasLogScale ? ', or not positive on a logarithmic scale' : ''
    }.`
}

export const buildScatterData = (
    rows: any[],
    settings: Pick<ScatterSettings, 'xAxisColumn' | 'yAxisColumn' | 'labelColumn' | 'xLogScale' | 'yLogScale'>,
    columnIndexes: Record<string, number>
): ScatterData => {
    const xIndex = columnIndexes[settings.xAxisColumn ?? '']
    const yIndex = columnIndexes[settings.yAxisColumn ?? '']
    const labelIndex = settings.labelColumn ? columnIndexes[settings.labelColumn] : undefined

    if (xIndex === undefined || yIndex === undefined) {
        return { points: [], skippedRowCount: 0 }
    }

    const points: ScatterPoint[] = []
    let skippedRowCount = 0

    rows.forEach((row) => {
        const x = parseNumericValue(row[xIndex])
        const y = parseNumericValue(row[yIndex])

        if (
            x === null ||
            y === null ||
            // a logarithmic axis can't place non-positive values — count them as skipped instead
            // of letting Chart.js drop them silently
            (settings.xLogScale && x <= 0) ||
            (settings.yLogScale && y <= 0)
        ) {
            skippedRowCount += 1
            return
        }

        const labelValue = labelIndex !== undefined ? row[labelIndex] : null
        points.push({
            x,
            y,
            label: labelValue === null || labelValue === undefined ? null : String(labelValue),
            xDisplay: formatDisplayValue(row[xIndex], x),
            yDisplay: formatDisplayValue(row[yIndex], y),
        })
    })

    return { points, skippedRowCount }
}
