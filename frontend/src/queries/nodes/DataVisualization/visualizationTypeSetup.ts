import { ChartSettings, DataVisualizationNode, HeatmapSettings } from '~/queries/schema/schema-general'
import { ChartDisplayType } from '~/types'

import { deriveDefaultAxes, getAutoVisualizationType } from './columnUtils'
import { getAutoBoxPlotSettings } from './Components/Charts/sqlBoxPlotAdapter'
import { Column, defaultAxisSettings } from './types'

const isNumerical = (columns: Column[], name: string | undefined): boolean =>
    !!name && !!columns.find((column) => column.name === name)?.type.isNumerical

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

export function applyVisualizationType(
    query: DataVisualizationNode,
    visualizationType: ChartDisplayType,
    columns: Column[],
    rowCount: number
): DataVisualizationNode {
    const numericalColumns = columns.filter((column) => column.type.isNumerical)
    const chartSettings: ChartSettings = { ...query.chartSettings }

    const columnNames = new Set(columns.map((column) => column.name))
    const invalidX = chartSettings.xAxis !== undefined && !columnNames.has(chartSettings.xAxis.column)
    const invalidY =
        chartSettings.yAxis?.some(
            (series) => !columns.find((column) => column.name === series.column)?.type.isNumerical
        ) ?? false

    if (columns.length > 0 && (invalidX || invalidY)) {
        chartSettings.xAxis = undefined
        chartSettings.yAxis = undefined
    }

    // An empty yAxis records that the user deleted every series, so only absent axes are seeded.
    if (chartSettings.xAxis === undefined && chartSettings.yAxis === undefined) {
        const seeded = deriveDefaultAxes(columns)
        if (seeded.yAxis.length > 0) {
            chartSettings.yAxis = seeded.yAxis.map((column) => ({ column, settings: defaultAxisSettings() }))
        }
        if (seeded.xAxis) {
            chartSettings.xAxis = { column: seeded.xAxis }
        }
    }

    const selectedXAxis = chartSettings.xAxis?.column ?? null
    let yAxis = chartSettings.yAxis ? [...chartSettings.yAxis] : []
    const yAxisNames = yAxis.map((series) => series.column)

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

    if (visualizationType === ChartDisplayType.BoxPlot) {
        chartSettings.boxPlot = getAutoBoxPlotSettings(columns, chartSettings.boxPlot)
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

    // Preserve the distinction between cleared series and axes that have never been initialized.
    if (chartSettings.yAxis !== undefined) {
        chartSettings.yAxis = yAxis
    }

    return { ...query, display: visualizationType, chartSettings }
}
