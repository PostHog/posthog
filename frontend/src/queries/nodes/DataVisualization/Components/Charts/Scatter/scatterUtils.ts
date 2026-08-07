import { ScatterSettings } from '~/queries/schema/schema-general'

export interface ScatterPoint {
    x: number
    y: number
    label: string | null
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
        })
    })

    return { points, skippedRowCount }
}
