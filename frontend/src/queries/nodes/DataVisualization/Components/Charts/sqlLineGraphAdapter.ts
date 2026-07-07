import { lemonToast } from '@posthog/lemon-ui'
import {
    type AxisLinesConfig,
    type ChartLegendConfig,
    type Series,
    type SeriesType,
    type TimeSeriesBarChartConfig,
    type TimeSeriesComboChartConfig,
    type TimeSeriesLineChartConfig,
    type TooltipConfig,
    type TooltipContext,
    type TrendLineConfig,
    type ValueLabelsConfig,
    type XAxisConfig,
    type YAxisConfig,
    createXAxisTickCallback,
} from '@posthog/quill-charts'

import { dayjs } from 'lib/dayjs'

import { ChartSettings, GoalLine, YAxisSettings } from '~/queries/schema/schema-general'
import { ChartDisplayType } from '~/types'

import { schemaGoalLinesToConfigs } from 'products/product_analytics/frontend/insights/trends/shared/goalLinesAdapter'

import { AxisSeries, AxisSeriesSettings, formatDataWithSettings } from '../../dataVisualizationLogic'
import { AxisBreakdownSeries } from '../seriesBreakdownLogic'
import { LineGraphProps } from './LineGraph'

export const MAX_SERIES = 200

/** Matches the legacy path's `hexToRGBA(seriesColor, 0.5)` area fill. */
export const AREA_FILL_OPACITY = 0.5

export type SqlLineYSeries = AxisSeries<number | null> | AxisBreakdownSeries<number | null>

export const isAreaSeries = (visualizationType: ChartDisplayType, settings: AxisSeriesSettings | undefined): boolean =>
    visualizationType === ChartDisplayType.ActionsAreaGraph || settings?.display?.displayType === 'area'

/** Per-series quill `type` that drives mixed-type rendering on {@link ComboChart}. */
export function seriesDisplayType(
    visualizationType: ChartDisplayType,
    settings: AxisSeriesSettings | undefined
): SeriesType {
    const displayType = settings?.display?.displayType
    if (displayType === 'bar') {
        return 'bar'
    }
    if (displayType === 'line') {
        return 'line'
    }
    if (displayType === 'area') {
        return 'area'
    }
    if (visualizationType === ChartDisplayType.ActionsBar || visualizationType === ChartDisplayType.ActionsStackedBar) {
        return 'bar'
    }
    if (visualizationType === ChartDisplayType.ActionsAreaGraph) {
        return 'area'
    }
    return 'line'
}

/** True when the series resolve to a mix of bar and line/area — the case neither the line-only nor
 *  the bar-only quill path can render, so it routes to {@link SqlComboGraph}. */
export function hasMixedSeriesTypes(
    yData: NonNullable<LineGraphProps['yData']>,
    visualizationType: ChartDisplayType
): boolean {
    let hasBar = false
    let hasLineLike = false
    for (const series of yData) {
        if (seriesDisplayType(visualizationType, series.settings) === 'bar') {
            hasBar = true
        } else {
            hasLineLike = true
        }
        if (hasBar && hasLineLike) {
            return true
        }
    }
    return false
}

/** Honors a column's custom display label, falling back to the breakdown value / column name —
 *  matches the legacy renderer (`LineGraph.tsx`). `||` so a blank label falls through. */
const getSeriesLabel = (series: SqlLineYSeries): string =>
    series.settings?.display?.label || ('name' in series ? series.name : series.column.name)

const getSeriesKey = (series: SqlLineYSeries, index: number): string =>
    'breakdownValue' in series ? series.breakdownValue : `${series.column.name}-${index}`

/** Shares {@link getSeriesKey} with {@link buildSeries} so each trend line's `seriesKey` matches its source series. */
export function buildTrendLineConfigs(ySeriesData: SqlLineYSeries[] | null | undefined): TrendLineConfig[] {
    if (!ySeriesData) {
        return []
    }
    return ySeriesData.reduce<TrendLineConfig[]>((configs, series, index) => {
        if (series.settings?.display?.trendLine) {
            configs.push({ seriesKey: getSeriesKey(series, index), kind: 'linear' })
        }
        return configs
    }, [])
}

/**
 * Plain line/area charts — including goal lines, trend lines, and right y-axis series — render here.
 * Series that mix a bar with a line/area route to {@link canRenderSqlComboGraph}; other mixes fall
 * back to the legacy chart.js path.
 */
export function canRenderSqlLineGraph(props: LineGraphProps): boolean {
    const { visualizationType, yData } = props

    if (
        visualizationType !== ChartDisplayType.ActionsLineGraph &&
        visualizationType !== ChartDisplayType.ActionsAreaGraph
    ) {
        return false
    }
    if (yData?.some((series) => series.settings?.display?.displayType === 'bar')) {
        return false
    }
    return true
}

export function canRenderSqlBarGraph(props: LineGraphProps): boolean {
    const { visualizationType, yData } = props

    if (visualizationType !== ChartDisplayType.ActionsBar && visualizationType !== ChartDisplayType.ActionsStackedBar) {
        return false
    }
    if (
        yData?.some((series) => {
            const displayType = series.settings?.display?.displayType
            return displayType === 'line' || displayType === 'area'
        })
    ) {
        return false
    }
    return true
}

/**
 * Mixed bar + line/area series render on quill's {@link TimeSeriesComboChart}. Percent-stacked
 * bars are supported as long as every line/area series is routed to the right axis — one sharing
 * the bars' axis can't be reconciled with the bars' [0, 1] percent scale, so that case falls back.
 */
export function canRenderSqlComboGraph(props: LineGraphProps): boolean {
    const { visualizationType, yData, chartSettings } = props

    if (
        visualizationType !== ChartDisplayType.ActionsLineGraph &&
        visualizationType !== ChartDisplayType.ActionsAreaGraph &&
        visualizationType !== ChartDisplayType.ActionsBar &&
        visualizationType !== ChartDisplayType.ActionsStackedBar
    ) {
        return false
    }
    if (!yData || !hasMixedSeriesTypes(yData, visualizationType)) {
        return false
    }
    // Percent-stacked bars clamp their axis to [0, 1] — a line/area series sharing that same axis
    // would plot its raw values off-scale with no way to reconcile the two domains. Only allow a
    // percent-stack combo when every non-bar series is routed to the right axis instead.
    if (
        visualizationType === ChartDisplayType.ActionsStackedBar &&
        chartSettings.stackBars100 &&
        yData.some(
            (series) => seriesDisplayType(visualizationType, series.settings) !== 'bar' && !isRightAxisSeries(series)
        )
    ) {
        return false
    }
    return true
}

export function barLayoutForDisplay(
    visualizationType: ChartDisplayType,
    chartSettings: ChartSettings
): NonNullable<TimeSeriesBarChartConfig['barLayout']> {
    if (visualizationType === ChartDisplayType.ActionsStackedBar) {
        return chartSettings.stackBars100 ? 'percent' : 'stacked'
    }
    return 'grouped'
}

/** Bar layout for the combo path. */
export function comboBarLayoutForDisplay(
    visualizationType: ChartDisplayType,
    chartSettings: ChartSettings
): NonNullable<TimeSeriesComboChartConfig['barLayout']> {
    if (visualizationType === ChartDisplayType.ActionsStackedBar) {
        return chartSettings.stackBars100 ? 'percent' : 'stacked'
    }
    return 'grouped'
}

/** Returns true when {@link MAX_SERIES} is exceeded and the user should be warned (not on dashboards). */
export function exceedsMaxSeries(yData: LineGraphProps['yData'], dashboardId: LineGraphProps['dashboardId']): boolean {
    return !!yData && yData.length > MAX_SERIES && !dashboardId
}

export function warnTooManySeries(count: number): void {
    lemonToast.warning(
        `This breakdown has too many series (${count}). Only showing top ${MAX_SERIES} series in the chart. All series are still available in the table below.`
    )
}

/** Pure cap to {@link MAX_SERIES}; warn separately via {@link exceedsMaxSeries}/{@link warnTooManySeries}. */
export function capYSeriesData(yData: LineGraphProps['yData']): SqlLineYSeries[] | null {
    if (!yData) {
        return null
    }
    return yData.length > MAX_SERIES ? yData.slice(0, MAX_SERIES) : yData
}

/** Per-series display settings carried into quill's `series.meta` so the tooltip can format each
 *  row with its own column's currency/duration/percent/prefix/suffix settings. */
export interface SqlLineSeriesMeta {
    settings?: AxisSeriesSettings
}

export function buildSeries(yData: SqlLineYSeries[], visualizationType: ChartDisplayType): Series<SqlLineSeriesMeta>[] {
    return yData.map((series, index) => {
        const settings = series.settings
        const color = settings?.display?.color
        const type = seriesDisplayType(visualizationType, settings)

        return {
            key: getSeriesKey(series, index),
            label: getSeriesLabel(series),
            // null -> NaN so quill draws a gap rather than a zero.
            data: series.data.map((value) => (value == null ? NaN : value)),
            meta: { settings },
            // Per-series type; ignored by the single-type line/bar charts, read by ComboChart.
            type,
            // Only pin an explicit color; otherwise let quill assign palette colors by index.
            ...(color ? { color } : {}),
            ...(settings?.display?.yAxisPosition === 'right' ? { yAxisId: 'right' } : {}),
            ...(type !== 'bar' && isAreaSeries(visualizationType, settings)
                ? { fill: { opacity: AREA_FILL_OPACITY } }
                : {}),
        }
    })
}

/** Formats a tooltip value with a column's display settings. */
export function formatSqlSeriesValue(value: number, settings?: AxisSeriesSettings): string {
    return String(formatDataWithSettings(value, settings) ?? value)
}

const isRightAxisSeries = (series: SqlLineYSeries): boolean => series.settings?.display?.yAxisPosition === 'right'

/** Series assigned to a given gutter — tick formatting reads the first series on that axis, so each
 *  gutter formats from a column actually on it rather than a blind `series[0]`. */
const seriesForAxis = (
    ySeriesData: SqlLineYSeries[] | null | undefined,
    position: 'left' | 'right'
): SqlLineYSeries[] => (ySeriesData ?? []).filter((series) => isRightAxisSeries(series) === (position === 'right'))

/** True when a column carries formatting that should override quill's default numeric axis ticks —
 *  a non-default `style`, a prefix/suffix, or an explicit decimal-place count. Default settings fall
 *  through so the axis keeps quill's human-friendly auto-formatting. */
export function hasAxisTickFormatting(settings?: AxisSeriesSettings): boolean {
    const formatting = settings?.formatting
    if (!formatting) {
        return false
    }
    return (
        (formatting.style != null && formatting.style !== 'none') ||
        !!formatting.prefix ||
        !!formatting.suffix ||
        formatting.decimalPlaces != null
    )
}

/** Built-in tooltip for the line + combo SQL charts: each row formatted by its column's settings
 *  (from `series.meta`), plus an optional total row. */
export function buildSqlTooltipConfig(
    chartSettings: ChartSettings,
    ySeriesData?: SqlLineYSeries[] | null
): TooltipConfig {
    const totalSettings = ySeriesData?.[0]?.settings
    return {
        enabled: true,
        pinnable: true,
        placement: 'cursor',
        sortedByValue: true,
        valueFormatter: (value: number, entry: TooltipContext['seriesData'][number]) =>
            formatSqlSeriesValue(value, (entry.series.meta as SqlLineSeriesMeta | undefined)?.settings),
        showTotal: chartSettings.showTotalRow !== false,
        totalFormatter: (value: number) => formatSqlSeriesValue(value, totalSettings),
    }
}

/** Returns a tooltip label formatter for date/datetime x-axes, or undefined for non-date axes. */
function buildSqlDateLabelFormatter(
    xData: AxisSeries<string>,
    timezone: string
): ((label: string) => string) | undefined {
    const typeName = xData.column.type.name
    if (typeName === 'DATETIME') {
        return (label: string) => dayjs(label).tz(timezone).format('MMM D, HH:mm')
    }
    if (typeName === 'DATE') {
        return (label: string) => dayjs(label).format('MMM D, YYYY')
    }
    return undefined
}

interface BuildConfigArgs {
    xData: AxisSeries<string>
    chartSettings: ChartSettings
    timezone: string
    goalLines?: GoalLine[]
    ySeriesData?: SqlLineYSeries[] | null
}

export interface BuildBarConfigArgs extends BuildConfigArgs {
    visualizationType: ChartDisplayType
}

function buildXAxisConfig(xData: AxisSeries<string>, chartSettings: ChartSettings, timezone: string): XAxisConfig {
    const isDateAxis = xData.column.type.name === 'DATE' || xData.column.type.name === 'DATETIME'

    return {
        label: chartSettings.xAxisLabel,
        tickFormatter: isDateAxis ? createXAxisTickCallback({ allDays: xData.data, timezone }) : undefined,
        hide: chartSettings.showXAxisTicks === false,
    }
}

/**
 * One y-axis config from its `YAxisSettings` plus the series on that axis. Tick formatting reads the
 * first series on the gutter (the same per-column settings the tooltip uses), and "start at zero"
 * follows legacy: a linear axis begins at 0 unless explicitly turned off (`yAxisAtZero` fallback).
 * Percent-stacked bars (`forceLinear`) skip both — the axis shows a 0–100% scale, not column values.
 */
function buildYAxisConfig(
    yAxis: YAxisSettings | undefined,
    axisSeries: SqlLineYSeries[],
    yAxisAtZero: boolean | undefined,
    { forceLinear = false, id, position }: { forceLinear?: boolean; id?: string; position?: 'left' | 'right' } = {}
): YAxisConfig {
    const isLog = !forceLinear && yAxis?.scale === 'logarithmic'
    const tickSettings = axisSeries[0]?.settings
    const tickFormatter =
        !forceLinear && hasAxisTickFormatting(tickSettings)
            ? (value: number): string => formatSqlSeriesValue(value, tickSettings)
            : undefined

    return {
        ...(id ? { id } : {}),
        ...(position ? { position } : {}),
        label: yAxis?.label,
        scale: isLog ? 'log' : 'linear',
        showGrid: yAxis?.showGridLines ?? true,
        hide: yAxis?.showTicks === false,
        tickFormatter,
        // Quill ignores startAtZero on a log scale; floatBaseline (the false case) is line-only, so
        // bars/combo keep their zero baseline regardless.
        startAtZero: forceLinear || !isLog ? (yAxis?.startAtZero ?? yAxisAtZero ?? true) : undefined,
    }
}

function buildLegendConfig(chartSettings: ChartSettings): ChartLegendConfig {
    return { show: chartSettings.showLegend ?? false, position: 'top', interactive: true }
}

/** The X/Y axis-border toggles map onto quill's per-edge axis lines — undefined when both are on
 *  (the default), so the app-level style default still applies. */
function buildAxisLinesConfig(chartSettings: ChartSettings): AxisLinesConfig | undefined {
    const x = chartSettings.showXAxisBorder ?? true
    const y = chartSettings.showYAxisBorder ?? true
    return x && y ? undefined : { x, y }
}

/**
 * "Show values on series" — each on-series label formats with its own column's settings, reusing the
 * tooltip's {@link formatSqlSeriesValue} path so labels read identically to the tooltip. `seriesIndex`
 * aligns with `ySeriesData` because {@link buildSeries} preserves order and quill keeps hidden series
 * in place (excluded, not removed). `context.rawValue` is the unscaled value (the `value` arg becomes a
 * 0–1 fraction in percent-stacked bars), so labels always show the real number.
 */
function buildValueLabelsConfig(
    chartSettings: ChartSettings,
    ySeriesData: SqlLineYSeries[] | null | undefined
): ValueLabelsConfig | undefined {
    if (!chartSettings.showValuesOnSeries) {
        return undefined
    }
    return {
        formatter: (_value, seriesIndex, _dataIndex, context) =>
            formatSqlSeriesValue(context.rawValue, ySeriesData?.[seriesIndex]?.settings),
    }
}

export function buildLineChartConfig({
    xData,
    chartSettings,
    timezone,
    goalLines,
    ySeriesData,
}: BuildConfigArgs): TimeSeriesLineChartConfig {
    const leftSeries = seriesForAxis(ySeriesData, 'left')
    const rightSeries = seriesForAxis(ySeriesData, 'right')
    const labelFormatter = buildSqlDateLabelFormatter(xData, timezone)

    return {
        xAxis: buildXAxisConfig(xData, chartSettings, timezone),
        // Emit a per-axis array only when a series actually targets the right axis — otherwise keep
        // the single-object form so single-axis charts render unchanged. Each gutter formats and
        // starts-at-zero from a column on that axis.
        yAxis:
            rightSeries.length > 0
                ? [
                      buildYAxisConfig(chartSettings.leftYAxisSettings, leftSeries, chartSettings.yAxisAtZero, {
                          id: 'left',
                          position: 'left',
                      }),
                      buildYAxisConfig(chartSettings.rightYAxisSettings, rightSeries, chartSettings.yAxisAtZero, {
                          id: 'right',
                          position: 'right',
                      }),
                  ]
                : buildYAxisConfig(chartSettings.leftYAxisSettings, leftSeries, chartSettings.yAxisAtZero),
        goalLines: schemaGoalLinesToConfigs(goalLines),
        showAxisLines: buildAxisLinesConfig(chartSettings),
        trendLines: buildTrendLineConfigs(ySeriesData),
        legend: buildLegendConfig(chartSettings),
        valueLabels: buildValueLabelsConfig(chartSettings, ySeriesData),
        tooltip: {
            ...buildSqlTooltipConfig(chartSettings, ySeriesData),
            ...(labelFormatter ? { labelFormatter } : {}),
        },
    }
}

export function buildBarChartConfig({
    xData,
    chartSettings,
    timezone,
    goalLines,
    visualizationType,
    ySeriesData,
}: BuildBarConfigArgs): TimeSeriesBarChartConfig & { yAxis?: YAxisConfig } {
    const barLayout = barLayoutForDisplay(visualizationType, chartSettings)
    const labelFormatter = buildSqlDateLabelFormatter(xData, timezone)
    const leftSeries = seriesForAxis(ySeriesData, 'left')
    const rightSeries = seriesForAxis(ySeriesData, 'right')

    return {
        xAxis: buildXAxisConfig(xData, chartSettings, timezone),
        yAxis:
            rightSeries.length > 0
                ? [
                      buildYAxisConfig(chartSettings.leftYAxisSettings, leftSeries, chartSettings.yAxisAtZero, {
                          id: 'left',
                          position: 'left',
                          forceLinear: barLayout === 'percent',
                      }),
                      buildYAxisConfig(chartSettings.rightYAxisSettings, rightSeries, chartSettings.yAxisAtZero, {
                          id: 'right',
                          position: 'right',
                          forceLinear: barLayout === 'percent',
                      }),
                  ]
                : buildYAxisConfig(chartSettings.leftYAxisSettings, leftSeries, chartSettings.yAxisAtZero, {
                      forceLinear: barLayout === 'percent',
                  }),
        goalLines: schemaGoalLinesToConfigs(goalLines),
        showAxisLines: buildAxisLinesConfig(chartSettings),
        barLayout,
        // Percent bars scale against a [0, 1] domain; trend lines plot raw series values, so they'd
        // render off-scale and invisible.
        trendLines: barLayout === 'percent' ? [] : buildTrendLineConfigs(ySeriesData),
        legend: buildLegendConfig(chartSettings),
        valueLabels: buildValueLabelsConfig(chartSettings, ySeriesData),
        tooltip: {
            ...buildSqlTooltipConfig(chartSettings, ySeriesData),
            ...(labelFormatter ? { labelFormatter } : {}),
        },
    }
}

export function buildComboChartConfig({
    xData,
    chartSettings,
    timezone,
    goalLines,
    visualizationType,
    ySeriesData,
}: BuildBarConfigArgs): TimeSeriesComboChartConfig & { yAxis?: YAxisConfig } {
    const labelFormatter = buildSqlDateLabelFormatter(xData, timezone)

    const leftSeries = seriesForAxis(ySeriesData, 'left')
    const rightSeries = seriesForAxis(ySeriesData, 'right')
    const barLayout = comboBarLayoutForDisplay(visualizationType, chartSettings)
    const isPercent = barLayout === 'percent'

    return {
        xAxis: buildXAxisConfig(xData, chartSettings, timezone),
        yAxis:
            rightSeries.length > 0
                ? [
                      buildYAxisConfig(chartSettings.leftYAxisSettings, leftSeries, chartSettings.yAxisAtZero, {
                          id: 'left',
                          position: 'left',
                          forceLinear: isPercent,
                      }),
                      buildYAxisConfig(chartSettings.rightYAxisSettings, rightSeries, chartSettings.yAxisAtZero, {
                          id: 'right',
                          position: 'right',
                          forceLinear: isPercent,
                      }),
                  ]
                : buildYAxisConfig(chartSettings.leftYAxisSettings, leftSeries, chartSettings.yAxisAtZero, {
                      forceLinear: isPercent,
                  }),
        goalLines: schemaGoalLinesToConfigs(goalLines),
        showAxisLines: buildAxisLinesConfig(chartSettings),
        barLayout,
        // Percent bars scale against a [0, 1] domain; trend lines plot raw series values, so they'd
        // render off-scale and invisible.
        trendLines: isPercent ? [] : buildTrendLineConfigs(ySeriesData),
        legend: buildLegendConfig(chartSettings),
        valueLabels: buildValueLabelsConfig(chartSettings, ySeriesData),
        tooltip: {
            ...buildSqlTooltipConfig(chartSettings, ySeriesData),
            ...(labelFormatter ? { labelFormatter } : {}),
        },
    }
}
