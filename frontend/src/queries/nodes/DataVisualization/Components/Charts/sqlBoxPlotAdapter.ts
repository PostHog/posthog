import type { BoxPlotDatum, BoxPlotSeries } from '@posthog/quill-charts'

import { BoxPlotSettings } from '~/queries/schema/schema-general'

interface BoxPlotColumn {
    name: string
    dataIndex: number
    type: { isNumerical: boolean }
}

export type SqlBoxPlotSkippedRowReason = 'missingStatistic' | 'invalidOrder' | 'meanOutsideRange'

export interface SqlBoxPlotModel {
    labels: string[]
    series: BoxPlotSeries[]
    error: string | null
    skippedRows: Record<SqlBoxPlotSkippedRowReason, number>
}

export type BoxPlotStatisticColumn = keyof Pick<
    BoxPlotSettings,
    'minColumn' | 'p25Column' | 'medianColumn' | 'meanColumn' | 'p75Column' | 'maxColumn'
>

type BoxPlotValue = keyof Pick<BoxPlotDatum, 'min' | 'p25' | 'median' | 'mean' | 'p75' | 'max'>

export const BOX_PLOT_STATISTICS: {
    setting: BoxPlotStatisticColumn
    value: BoxPlotValue
    label: string
    aliases: string[]
}[] = [
    { setting: 'minColumn', value: 'min', label: 'Minimum', aliases: ['min', 'minimum'] },
    { setting: 'p25Column', value: 'p25', label: '25th percentile', aliases: ['p25', 'q1'] },
    { setting: 'medianColumn', value: 'median', label: 'Median', aliases: ['median', 'p50'] },
    { setting: 'meanColumn', value: 'mean', label: 'Mean', aliases: ['mean', 'avg', 'average'] },
    { setting: 'p75Column', value: 'p75', label: '75th percentile', aliases: ['p75', 'q3'] },
    { setting: 'maxColumn', value: 'max', label: 'Maximum', aliases: ['max', 'maximum'] },
]

const MAX_BOX_PLOT_CELLS = 10_000
// The cell cap alone permits thousands of series under a single X-axis value, so limit series
// independently because each one adds a legend row and per-hover work. Matches MAX_SERIES in
// sqlLineGraphAdapter.
const MAX_BOX_PLOT_SERIES = 200

const emptySkippedRows = (): Record<SqlBoxPlotSkippedRowReason, number> => ({
    missingStatistic: 0,
    invalidOrder: 0,
    meanOutsideRange: 0,
})

const emptyModel = (error: string | null = null): SqlBoxPlotModel => ({
    labels: [],
    series: [],
    error,
    skippedRows: emptySkippedRows(),
})

const findColumn = (
    columns: BoxPlotColumn[],
    name: string | null | undefined,
    numerical = false
): BoxPlotColumn | undefined => {
    if (!name) {
        return undefined
    }
    return columns.find((column) => column.name === name && (!numerical || column.type.isNumerical))
}

const findAliasedColumn = (columns: BoxPlotColumn[], aliases: string[], numerical = false): BoxPlotColumn | undefined =>
    columns.find((column) => aliases.includes(column.name.toLowerCase()) && (!numerical || column.type.isNumerical))

export const getAutoBoxPlotSettings = (columns: BoxPlotColumn[], current: BoxPlotSettings = {}): BoxPlotSettings => {
    const next = { ...current }

    if (current.xAxisColumn !== null && !findColumn(columns, current.xAxisColumn)) {
        next.xAxisColumn = findAliasedColumn(columns, ['label', 'bucket', 'date', 'day'])?.name
    }
    if (current.seriesColumn !== null && !findColumn(columns, current.seriesColumn)) {
        next.seriesColumn = findAliasedColumn(columns, ['series', 'breakdown'])?.name
    }

    for (const statistic of BOX_PLOT_STATISTICS) {
        if (!findColumn(columns, current[statistic.setting], true)) {
            next[statistic.setting] = findAliasedColumn(columns, statistic.aliases, true)?.name
        }
    }

    return next
}

const groupingIdentity = (value: unknown): string => JSON.stringify([typeof value, value ?? null])

const finiteNumber = (value: unknown): number | null => {
    if (value === null || value === undefined || value === '') {
        return null
    }
    const number = typeof value === 'number' ? value : Number(value)
    return Number.isFinite(number) ? number : null
}

export const buildSqlBoxPlotModel = (
    rows: unknown[][],
    columns: BoxPlotColumn[],
    settings: BoxPlotSettings
): SqlBoxPlotModel => {
    const statisticColumns = BOX_PLOT_STATISTICS.map((statistic) => ({
        ...statistic,
        column: findColumn(columns, settings[statistic.setting], true),
    }))
    const missingStatistic = statisticColumns.find(({ column }) => !column)
    if (missingStatistic) {
        return emptyModel(`Select a column for ${missingStatistic.label}.`)
    }

    if (rows.length === 0) {
        return emptyModel()
    }

    const xAxisColumn = findColumn(columns, settings.xAxisColumn)
    const seriesColumn = findColumn(columns, settings.seriesColumn)
    if (!xAxisColumn && !seriesColumn && rows.length > 1) {
        return emptyModel('Select an X-axis column when the query returns more than one row.')
    }

    const labels: string[] = []
    const labelSet = new Set<string>()
    const seriesLabels: string[] = []
    const seriesLabelSet = new Set<string>()
    const dataBySeries = new Map<string, Map<string, BoxPlotSeries['data'][number]>>()
    const skippedRows = emptySkippedRows()
    const xIdentityByLabel = new Map<string, string>()
    const seriesIdentityByLabel = new Map<string, string>()
    const rowByPair = new Map<string, number>()

    for (const [rowIndex, row] of rows.entries()) {
        const nullableValues = Object.fromEntries(
            statisticColumns.map((statistic) => [statistic.value, finiteNumber(row[statistic.column!.dataIndex])])
        ) as Record<BoxPlotValue, number | null>
        if (Object.values(nullableValues).some((value) => value === null)) {
            skippedRows.missingStatistic++
            continue
        }

        const values = nullableValues as Record<BoxPlotValue, number>
        if (
            !(
                values.min <= values.p25 &&
                values.p25 <= values.median &&
                values.median <= values.p75 &&
                values.p75 <= values.max
            )
        ) {
            skippedRows.invalidOrder++
            continue
        }
        if (values.mean < values.min || values.mean > values.max) {
            skippedRows.meanOutsideRange++
            continue
        }

        const xValue = xAxisColumn ? row[xAxisColumn.dataIndex] : 'Distribution'
        const seriesValue = seriesColumn ? row[seriesColumn.dataIndex] : 'Distribution'
        const label = String(xValue ?? '[No value]')
        const seriesLabel = String(seriesValue ?? '[No value]')
        const xIdentity = groupingIdentity(xValue)
        const seriesIdentity = groupingIdentity(seriesValue)

        if (xIdentityByLabel.has(label) && xIdentityByLabel.get(label) !== xIdentity) {
            return emptyModel(
                `Row ${rowIndex + 1} has an X-axis value that displays as "${label}", but another value uses the same label. Cast them to distinct strings in SQL.`
            )
        }
        if (seriesIdentityByLabel.has(seriesLabel) && seriesIdentityByLabel.get(seriesLabel) !== seriesIdentity) {
            return emptyModel(
                `Row ${rowIndex + 1} has a series value that displays as "${seriesLabel}", but another value uses the same label. Cast them to distinct strings in SQL.`
            )
        }
        xIdentityByLabel.set(label, xIdentity)
        seriesIdentityByLabel.set(seriesLabel, seriesIdentity)

        const pairKey = JSON.stringify([xIdentity, seriesIdentity])
        const previousRow = rowByPair.get(pairKey)
        if (previousRow !== undefined) {
            return emptyModel(
                `Rows ${previousRow + 1} and ${rowIndex + 1} use the same X-axis and series values. Return one row for each box.`
            )
        }
        rowByPair.set(pairKey, rowIndex)

        if (!labelSet.has(label)) {
            labels.push(label)
            labelSet.add(label)
        }
        if (!seriesLabelSet.has(seriesLabel)) {
            seriesLabels.push(seriesLabel)
            seriesLabelSet.add(seriesLabel)
            if (seriesLabelSet.size > MAX_BOX_PLOT_SERIES) {
                return emptyModel(
                    'The box plot has too many series. Reduce the number of distinct series values in the query result.'
                )
            }
        }
        if (labelSet.size * seriesLabelSet.size > MAX_BOX_PLOT_CELLS) {
            return emptyModel('The box plot has too many X-axis and series combinations. Reduce the query result.')
        }

        const iqr = values.p75 - values.p25
        const excludeOutliers = settings.excludeOutliers !== false
        const datum = {
            ...values,
            min: excludeOutliers ? Math.max(values.min, values.p25 - 1.5 * iqr) : values.min,
            max: excludeOutliers ? Math.min(values.max, values.p75 + 1.5 * iqr) : values.max,
        }
        const seriesData = dataBySeries.get(seriesLabel) ?? new Map()
        seriesData.set(label, datum)
        dataBySeries.set(seriesLabel, seriesData)
    }

    return {
        labels,
        series: seriesLabels.map((seriesLabel) => ({
            key: seriesLabel,
            label: seriesLabel,
            data: labels.map((label) => dataBySeries.get(seriesLabel)?.get(label) ?? null),
        })),
        error: null,
        skippedRows,
    }
}
