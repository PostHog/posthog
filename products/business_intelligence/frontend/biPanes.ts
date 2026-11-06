import { DataColorTheme, getSeriesColor } from 'lib/colors'
import { getColorFromToken } from 'scenes/dataThemeLogic'

import { buildSeries, getSeriesKey } from '~/queries/nodes/DataVisualization/Components/Charts/sqlLineGraphAdapter'
import { resolveSQLReferenceLines } from '~/queries/nodes/DataVisualization/Components/Charts/sqlReferenceLines'
import {
    AxisBreakdownSeries,
    getBreakdownValueKey,
} from '~/queries/nodes/DataVisualization/Components/seriesBreakdownLogic'
import { AxisSeries, Column } from '~/queries/nodes/DataVisualization/dataVisualizationLogic'
import { BIConfig, BIField } from '~/queries/schema/schema-business-intelligence'
import { ChartSettings, GoalLine } from '~/queries/schema/schema-general'
import { ChartDisplayType } from '~/types'

import { getBIFieldPillLabel, getBIResultDimensions, isDateTimeBIField } from './biEditorTypes'
import { createBIMemberDisplayLookup, createBIMemberLabelLookup } from './biMemberAliases'
import { getBIPaneFields } from './biPaneConfig'
import { biNumericValue, getBIResultMeasures } from './biResultPresentation'

export const MAX_BI_PANES = 24
const MAX_PANE_LABELS = 1000
const MAX_PANE_SERIES = 50

export interface BIPane {
    key: string
    title: string
    xData: AxisSeries<string>
    yData: AxisBreakdownSeries<number | null>[]
    records: Map<string, Record<string, unknown>>
    goalLines: GoalLine[]
}

export interface BIPaneModel {
    panes: BIPane[]
    labels: Map<string, string>
    warnings: string[]
    error?: string
    valueDomain?: { min: number; max: number }
}

const valueKey = (value: unknown): string => JSON.stringify(value ?? null)

function paneMemberLabel(config: BIConfig): (field: BIField, value: unknown) => string {
    const displayLabel = createBIMemberDisplayLookup(config)
    const defaultLabel = createBIMemberLabelLookup(config)
    return (field: BIField, value: unknown): string => {
        const alias = displayLabel(field, value)
        if (alias !== undefined) {
            return alias
        }
        if (field.datePart === 'quarter' && typeof value === 'number' && value >= 1 && value <= 4) {
            return `Q${value}`
        }
        if (field.dateBucket === 'year' && typeof value === 'string' && /^\d{4}-\d{2}-\d{2}/.test(value)) {
            return value.slice(0, 4)
        }
        return defaultLabel(field, value)
    }
}

function sharedValueDomain(
    panes: BIPane[],
    chartType: ChartDisplayType,
    settings: ChartSettings
): BIPaneModel['valueDomain'] {
    const values: number[] = []
    for (const pane of panes) {
        const series = buildSeries(pane.yData, chartType)
        values.push(...series.flatMap((item) => item.data).filter(Number.isFinite))
        values.push(
            ...resolveSQLReferenceLines(pane.goalLines, series)
                .map((line) => line.value)
                .filter(Number.isFinite)
        )
        if (chartType === ChartDisplayType.ActionsStackedBar) {
            for (let index = 0; index < pane.xData.data.length; index++) {
                const marks = series.map((item) => item.data[index]).filter(Number.isFinite)
                values.push(
                    marks.filter((value) => value > 0).reduce((sum, value) => sum + value, 0),
                    marks.filter((value) => value < 0).reduce((sum, value) => sum + value, 0)
                )
            }
        }
    }
    const log = settings.leftYAxisSettings?.scale === 'logarithmic'
    const finite = log ? values.filter((value) => value > 0) : values
    if (finite.length) {
        let min = finite.reduce((a, b) => Math.min(a, b))
        let max = finite.reduce((a, b) => Math.max(a, b))
        if (
            !log &&
            ((settings.leftYAxisSettings?.startAtZero ?? settings.yAxisAtZero ?? true) ||
                [
                    ChartDisplayType.ActionsBar,
                    ChartDisplayType.ActionsBarValue,
                    ChartDisplayType.ActionsStackedBar,
                ].includes(chartType))
        ) {
            min = Math.min(0, min)
            max = Math.max(0, max)
        }
        if (min === max) {
            max = max === 0 ? 1 : max + Math.abs(max) * 0.1
            min = log ? min / 1.1 : min
        }
        return { min, max }
    }
    return undefined
}

export function buildBIPanes(
    config: BIConfig,
    settings: ChartSettings,
    columns: Column[],
    rows: unknown[][],
    goalLines: GoalLine[] = settings.goalLines ?? [],
    theme: DataColorTheme | null = null
): BIPaneModel {
    const model: BIPaneModel = { panes: [], labels: new Map(), warnings: [] }
    const dimensions = getBIResultDimensions(config)
    const paneFields = getBIPaneFields(config)
    const paneIds = new Set(paneFields.map((field) => field.id))
    const chartDimensions = dimensions.filter(({ field }) => !paneIds.has(field.id))
    if (!paneFields.length || !chartDimensions.length || chartDimensions.length > 2) {
        return { ...model, error: 'Keep one axis dimension and, optionally, one color dimension outside panes.' }
    }
    if (config.compareFilter?.compare) {
        return { ...model, error: 'Turn off period comparison to use panes.' }
    }
    const color = chartDimensions.find(({ field }) => field.id === config.colorBy)
    const axis =
        chartDimensions.find(({ field, column }) => field !== color?.field && column === settings.xAxis?.column) ??
        chartDimensions.find(({ field }) => field !== color?.field && isDateTimeBIField(field)) ??
        chartDimensions.find(({ field }) => field !== color?.field)
    if (!axis) {
        return { ...model, error: 'Keep an axis dimension outside panes and Color.' }
    }
    const breakdown = color ?? chartDimensions.find((dimension) => dimension !== axis)
    const xColumn = columns.find((column) => column.name === axis.column)
    const paneColumns = paneFields.map((field) =>
        columns.find(
            (column) => column.name === dimensions.find((dimension) => dimension.field.id === field.id)?.column
        )
    )
    const colorColumn = breakdown && columns.find((column) => column.name === breakdown.column)
    const measures = getBIResultMeasures(config, settings).map((measure) => ({
        ...measure,
        index: columns.find((column) => column.name === measure.column)?.dataIndex,
    }))
    if (
        !xColumn ||
        paneColumns.some((column) => !column) ||
        (breakdown && !colorColumn) ||
        measures.some((measure) => measure.index === undefined)
    ) {
        return { ...model, error: 'The returned columns do not match these panes. Run the worksheet again.' }
    }
    const memberLabel = paneMemberLabel(config)
    const groupingIndex = columns.find((column) => column.name === 'bi_grouping')?.dataIndex
    const data = groupingIndex === undefined ? rows : rows.filter((row) => Number(row[groupingIndex]) === 0)
    const groups = new Map<string, { values: unknown[]; rows: unknown[][] }>()
    const xValues = new Map<string, unknown>()
    const colors = new Map<string, unknown>()
    for (const row of data) {
        const values = paneColumns.map((column) => row[column!.dataIndex])
        const key = valueKey(values)
        const group = groups.get(key) ?? { values, rows: [] }
        group.rows.push(row)
        groups.set(key, group)
        xValues.set(valueKey(row[xColumn.dataIndex]), row[xColumn.dataIndex])
        const category = colorColumn ? row[colorColumn.dataIndex] : null
        colors.set(valueKey(category), category)
    }
    let xEntries = [...xValues]
    if (!config.sort && (isDateTimeBIField(axis.field) || axis.field.datePart)) {
        xEntries.sort(([, a], [, b]) =>
            typeof a === 'number' && typeof b === 'number' ? a - b : String(a).localeCompare(String(b))
        )
    }
    if (groups.size > MAX_BI_PANES) {
        model.warnings.push(
            `Showing the first ${MAX_BI_PANES} of ${groups.size} panes in result order. Narrow the filters to see the rest.`
        )
    }
    if (xEntries.length > MAX_PANE_LABELS) {
        model.warnings.push(
            `Showing the first ${MAX_PANE_LABELS} axis values per pane. Narrow the filters or use a coarser date interval.`
        )
        xEntries = xEntries.slice(0, MAX_PANE_LABELS)
    }
    const colorEntries = [...colors].sort(([a], [b]) => a.localeCompare(b))
    if (colorEntries.length * measures.length > MAX_PANE_SERIES) {
        return {
            ...model,
            error: 'Panes support up to 50 measure and color series. Narrow the filters or remove a measure.',
        }
    }
    const dateAxis = isDateTimeBIField(axis.field)
    const labelKey = (value: unknown): string =>
        dateAxis && value !== null && value !== undefined ? String(value) : valueKey(value)
    for (const [, value] of xEntries) {
        model.labels.set(labelKey(value), memberLabel(axis.field, value))
    }
    for (const [key, group] of [...groups].slice(0, MAX_BI_PANES)) {
        const records = new Map<string, Record<string, unknown>>()
        const rowRecords = new Map<unknown[], Record<string, unknown>>()
        const cells = new Map(
            group.rows.map((row) => [
                valueKey([row[xColumn.dataIndex], colorColumn ? row[colorColumn.dataIndex] : null]),
                row,
            ])
        )
        if (cells.size !== group.rows.length) {
            return {
                ...model,
                panes: [],
                error: 'More than one result group occupies a pane mark. Add the remaining dimensions to panes or Color.',
            }
        }
        const yData = measures.flatMap((measure) =>
            colorEntries.map(([colorKey, category]): AxisBreakdownSeries<number | null> => {
                const hash = [...colorKey].reduce(
                    (hash, character) => (Math.imul(hash, 31) + character.charCodeAt(0)) >>> 0,
                    0
                )
                const customToken = settings.resultCustomizations?.[getBreakdownValueKey(category)]?.color
                const series: AxisBreakdownSeries<number | null> = {
                    name: valueKey([measure.column, colorKey]),
                    breakdownValue: getBreakdownValueKey(category),
                    data: [],
                    settings: {
                        ...measure.settings,
                        display: {
                            ...measure.settings?.display,
                            label: breakdown
                                ? [measures.length > 1 ? measure.label : null, memberLabel(breakdown.field, category)]
                                      .filter(Boolean)
                                      .join(' · ')
                                : measure.label,
                            color:
                                config.colorBy === null
                                    ? getSeriesColor(0)
                                    : breakdown
                                      ? customToken && theme
                                          ? getColorFromToken(theme, customToken)
                                          : getSeriesColor(hash)
                                      : measure.settings?.display?.color,
                        },
                    },
                }
                series.data = xEntries.map(([, x], index) => {
                    const row = cells.get(valueKey([x, category]))
                    if (row) {
                        let record = rowRecords.get(row)
                        if (!record) {
                            record = Object.fromEntries(columns.map((column) => [column.name, row[column.dataIndex]]))
                            rowRecords.set(row, record)
                        }
                        records.set(valueKey([getSeriesKey(series, 0), index]), record)
                    }
                    const numeric = row ? biNumericValue(row[measure.index!]) : null
                    const value = numeric ?? (settings.showNullsAsZero ? 0 : null)
                    return value === null ? null : value * (measure.settings?.formatting?.style === 'percent' ? 100 : 1)
                })
                return series
            })
        )
        model.panes.push({
            key,
            title: paneFields
                .map((field, index) => `${getBIFieldPillLabel(field)}: ${memberLabel(field, group.values[index])}`)
                .join(' › '),
            xData: { column: xColumn, data: xEntries.map(([, value]) => labelKey(value)) },
            yData,
            records,
            goalLines,
        })
    }
    const percent = config.chartType === ChartDisplayType.ActionsStackedBar && settings.stackBars100 === true
    if (
        config.panes?.referenceLines === 'worksheet' &&
        goalLines.some((line) => line.calculation && line.calculation !== 'fixed')
    ) {
        const series =
            model.panes[0]?.yData.map((item) => {
                const [column, colorKey] = JSON.parse(item.name) as [string, string]
                const measure = measures.find((measure) => measure.column === column)!
                return {
                    ...item,
                    data: data
                        .filter((row) => valueKey(colorColumn ? row[colorColumn.dataIndex] : null) === colorKey)
                        .map((row) => {
                            const value = biNumericValue(row[measure.index!]) ?? (settings.showNullsAsZero ? 0 : null)
                            return value === null
                                ? null
                                : value * (measure.settings?.formatting?.style === 'percent' ? 100 : 1)
                        }),
                }
            }) ?? []
        const resolved = resolveSQLReferenceLines(goalLines, buildSeries(series, config.chartType), percent).map(
            (line) => ({ ...line, calculation: 'fixed' as const })
        )
        model.panes = model.panes.map((pane) => ({ ...pane, goalLines: resolved }))
    }
    if (!config.panes?.independentAxes && !percent) {
        const hasRightAxis = measures.some((measure) => measure.settings?.display?.yAxisPosition === 'right')
        if (hasRightAxis) {
            model.warnings.push('Panes with a secondary value axis use independent scales.')
        } else {
            model.valueDomain = sharedValueDomain(model.panes, config.chartType, settings)
        }
    }
    return model
}
