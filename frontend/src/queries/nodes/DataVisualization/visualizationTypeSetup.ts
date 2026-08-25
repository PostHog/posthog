import { ChartSettings, DataVisualizationNode, HeatmapSettings } from '~/queries/schema/schema-general'
import { ChartDisplayType } from '~/types'

import { deriveDefaultAxes, getAutoVisualizationType } from './columnUtils'
import { Column, defaultAxisSettings } from './types'

/**
 * The setup a chart type needs beyond its `display`, as a change to the query.
 *
 * `dataVisualizationLogic.setVisualizationType` performs the same setup through its own actions,
 * because the editor keeps axis state locally. A surface with no such state — a dashboard card,
 * which renders its query read-only — applies the result here instead. Both answer to these rules,
 * so the same pick produces the same chart wherever it is made, and `visualizationTypeSetup.test.ts`
 * holds the two together.
 */

const isNumerical = (columns: Column[], name: string | undefined): boolean =>
    !!name && !!columns.find((column) => column.name === name)?.type.isNumerical

/** All columns numeric means nothing is left to label the x axis, so the first one moves there. */
export function shouldPromoteFirstNumericToX(
    columns: Column[],
    numericalColumns: Column[],
    selectedXAxis: string | null,
    selectedYAxisNames: string[]
): boolean {
    if (selectedXAxis !== null || columns.length < 2 || numericalColumns.length < 2) {
        return false
    }
    if (!columns.every((column) => column.type.isNumerical)) {
        return false
    }
    if (selectedYAxisNames.length !== numericalColumns.length) {
        return false
    }
    const names = new Set(selectedYAxisNames)
    return numericalColumns.every((column) => names.has(column.name))
}

/**
 * A scatter plots two measures against each other, so its x axis has to hold a numeric column.
 * Returns the column that should sit there: the current one when it is already numeric, otherwise
 * one that is not already a y series, so the chart is not left with nothing on either axis. Null
 * when a scatter cannot be plotted at all.
 */
export function resolveScatterXAxisColumn(
    columns: Column[],
    numericalColumns: Column[],
    selectedXAxis: string | null,
    selectedYAxisNames: string[]
): Column | null {
    if (numericalColumns.length < 2) {
        return null
    }
    if (isNumerical(columns, selectedXAxis ?? undefined)) {
        return columns.find((column) => column.name === selectedXAxis) ?? null
    }
    const names = new Set(selectedYAxisNames)
    return numericalColumns.find((column) => !names.has(column.name)) ?? numericalColumns[0]
}

/** The heatmap column roles no rule can infer from a type alone, filled only where still unset. */
export function getHeatmapAutoSettings(columns: Column[], heatmapSettings: HeatmapSettings): Partial<HeatmapSettings> {
    const stringColumns = columns.filter((column) => column.type.name === 'STRING')
    const numericalColumns = columns.filter((column) => column.type.isNumerical)
    const next: Partial<HeatmapSettings> = {}

    if (!heatmapSettings.xAxisColumn && stringColumns[0]) {
        next.xAxisColumn = stringColumns[0].name
    }
    if (!heatmapSettings.yAxisColumn && stringColumns[1]) {
        next.yAxisColumn = stringColumns[1].name
    }
    if (!heatmapSettings.valueColumn && numericalColumns[0]) {
        next.valueColumn = numericalColumns[0].name
    }
    return next
}

/**
 * The query a pick produces: the display, plus whatever else that type needs to draw.
 *
 * Seeds the axes first, which the editor gets from the subscription that runs when its columns
 * arrive, then applies the per-type setup. A card has neither, so it needs both to land on the same
 * query. `rowCount` resolves what Auto means here, which is all Auto reads of the result.
 */
export function applyVisualizationType(
    query: DataVisualizationNode,
    visualizationType: ChartDisplayType,
    columns: Column[],
    rowCount: number
): DataVisualizationNode {
    const numericalColumns = columns.filter((column) => column.type.isNumerical)
    const chartSettings: ChartSettings = { ...query.chartSettings }

    // The editor's columns subscription drops the axes when one names a column the result no longer
    // has, or a y series that is not numeric, and re-seeds from scratch. A card is handed the saved
    // query rather than that repaired one, so it has to do the same before deciding anything.
    const columnNames = new Set(columns.map((column) => column.name))
    const invalidX = chartSettings.xAxis !== undefined && !columnNames.has(chartSettings.xAxis.column)
    const invalidY =
        chartSettings.yAxis?.some(
            (series) => !columns.find((column) => column.name === series.column)?.type.isNumerical
        ) ?? false

    if (invalidX || invalidY) {
        chartSettings.xAxis = undefined
        chartSettings.yAxis = undefined
    }

    // Matches the editor, which seeds only when neither axis has been set. An empty yAxis is a user
    // who deleted every series, not an unset one, so it is left alone.
    if (chartSettings.xAxis === undefined && chartSettings.yAxis === undefined) {
        const seeded = deriveDefaultAxes(columns)
        chartSettings.yAxis = seeded.yAxis.map((column) => ({ column, settings: defaultAxisSettings() }))
        if (seeded.xAxis) {
            chartSettings.xAxis = { column: seeded.xAxis }
        }
    }

    const selectedXAxis = chartSettings.xAxis?.column ?? null
    let yAxis = chartSettings.yAxis ? [...chartSettings.yAxis] : []
    const yAxisNames = yAxis.map((series) => series.column)

    // A newly picked pie labels its slices. One loaded with the type already set never reaches here,
    // so it keeps the legacy value-on-slice default.
    if (visualizationType === ChartDisplayType.ActionsPie && chartSettings.pie?.sliceContent === undefined) {
        chartSettings.pie = { ...chartSettings.pie, sliceContent: 'labels' }
    }

    if (
        [ChartDisplayType.ActionsLineGraph, ChartDisplayType.ActionsAreaGraph].includes(visualizationType) &&
        shouldPromoteFirstNumericToX(columns, numericalColumns, selectedXAxis, yAxisNames)
    ) {
        const [xAxisColumn] = numericalColumns
        chartSettings.xAxis = { column: xAxisColumn.name }
        yAxis = yAxis.filter((series) => series.column !== xAxisColumn.name)
    }

    if (visualizationType === ChartDisplayType.ScatterPlot) {
        const xAxisColumn = resolveScatterXAxisColumn(columns, numericalColumns, selectedXAxis, yAxisNames)
        if (xAxisColumn) {
            chartSettings.xAxis = { column: xAxisColumn.name }
            yAxis = yAxis.filter((series) => series.column !== xAxisColumn.name)
        }
    }

    const isAutoHeatmap =
        visualizationType === ChartDisplayType.Auto &&
        getAutoVisualizationType(columns, rowCount) === ChartDisplayType.TwoDimensionalHeatmap

    if (visualizationType === ChartDisplayType.TwoDimensionalHeatmap || isAutoHeatmap) {
        const heatmap = chartSettings.heatmap ?? {}
        const autoSettings = getHeatmapAutoSettings(columns, heatmap)
        if (Object.keys(autoSettings).length > 0) {
            chartSettings.heatmap = { ...heatmap, ...autoSettings }
        }
    }

    // Always written, matching the editor: a query carrying `yAxis: []` means the series were
    // cleared, while an absent key means they were never set and get seeded on the next load.
    chartSettings.yAxis = yAxis

    return { ...query, display: visualizationType, chartSettings }
}
