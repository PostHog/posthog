import {
    type AxisLinesConfig,
    type ChartLegendConfig,
    type GoalLineConfig,
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

import {
    type AxisSeriesSettings,
    formatDataWithSettings,
} from '~/queries/nodes/DataVisualization/dataVisualizationLogic'
import { ChartSettings, GoalLine, YAxisSettings } from '~/queries/schema/schema-general'
import { ChartDisplayType } from '~/types'

/**
 * Maps a saved insight's tabular axis series + `ChartSettings` onto quill's time-series charts:
 * per-series types and dispatch (line vs bar vs combo), series building, and the line/bar/combo
 * chart configs (axes, tooltip, legend, goal/trend lines, value labels). Structural series types
 * keep it decoupled from any single host — SQL insights and customer analytics both render through
 * it; the per-column settings semantics (`AxisSeriesSettings`, `formatDataWithSettings`) stay owned
 * by data viz.
 */

export const MAX_SERIES = 200

/** Matches the legacy path's `hexToRGBA(seriesColor, 0.5)` area fill. */
export const AREA_FILL_OPACITY = 0.5

/** A plain y-axis column series — the data viz `AxisSeries` shape, reduced to what charts read. */
export interface ChartAxisSeries<T> {
    column: { name: string }
    data: T[]
    settings?: AxisSeriesSettings
}

/** A series derived from a series breakdown — named by breakdown value, with no source column. */
export interface ChartBreakdownSeries<T> {
    name: string
    /** Stable key derived from the raw breakdown column value. */
    breakdownValue: string
    data: T[]
    settings?: AxisSeriesSettings
}

export type ChartYSeries = ChartAxisSeries<number | null> | ChartBreakdownSeries<number | null>

/** The x-axis column; `column.type.name` distinguishes date/datetime axes for tick formatting. */
export interface ChartXSeries {
    column: { name: string; type: { name: string } }
    data: string[]
}

/** The slice of a chart's props the render-dispatch predicates read. */
export interface TimeSeriesChartInput {
    visualizationType: ChartDisplayType
    yData?: ChartYSeries[] | null
    chartSettings: ChartSettings
}

export const isAreaSeries = (visualizationType: ChartDisplayType, settings: AxisSeriesSettings | undefined): boolean =>
    visualizationType === ChartDisplayType.ActionsAreaGraph || settings?.display?.displayType === 'area'

/** Per-series quill `type` that drives mixed-type rendering on the combo chart. */
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
 *  the bar-only quill path can render, so it routes to the combo chart. */
export function hasMixedSeriesTypes(yData: ChartYSeries[], visualizationType: ChartDisplayType): boolean {
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
const getSeriesLabel = (series: ChartYSeries): string =>
    series.settings?.display?.label || ('name' in series ? series.name : series.column.name)

const getSeriesKey = (series: ChartYSeries, index: number): string =>
    'breakdownValue' in series ? series.breakdownValue : `${series.column.name}-${index}`

/** Shares {@link getSeriesKey} with {@link buildChartSeries} so each trend line's `seriesKey` matches its source series. */
export function buildTrendLineConfigs(ySeriesData: ChartYSeries[] | null | undefined): TrendLineConfig[] {
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
 * Series that mix a bar with a line/area route to {@link canRenderTimeSeriesComboChart}; hosts
 * decide what other mixes fall back to.
 */
export function canRenderTimeSeriesLineChart(props: TimeSeriesChartInput): boolean {
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

export function canRenderTimeSeriesBarChart(props: TimeSeriesChartInput): boolean {
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
export function canRenderTimeSeriesComboChart(props: TimeSeriesChartInput): boolean {
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

/** Pure cap to {@link MAX_SERIES} so a query with an excessive yAxis can't build unbounded chart
 *  work. Identity when under the cap, so memoized consumers keep a stable reference. Generic over
 *  the array type (not the element) so a union of series arrays keeps its type through the cap. */
export function capYSeriesData<T extends readonly unknown[]>(yData: T | null | undefined): T | null {
    if (!yData) {
        return null
    }
    return yData.length > MAX_SERIES ? (yData.slice(0, MAX_SERIES) as unknown as T) : yData
}

/** Per-series display settings carried into quill's `series.meta` so the tooltip can format each
 *  row with its own column's currency/duration/percent/prefix/suffix settings. */
export interface ChartSeriesMeta {
    settings?: AxisSeriesSettings
}

export function buildChartSeries(
    yData: ChartYSeries[],
    visualizationType: ChartDisplayType
): Series<ChartSeriesMeta>[] {
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
            // A percent-styled column doesn't sum meaningfully with the other columns, so keep it
            // out of the tooltip's total row (matches the legacy renderer).
            ...(settings?.formatting?.style === 'percent' ? { visibility: { total: false } } : {}),
            // Only pin an explicit color; otherwise let quill assign palette colors by index.
            ...(color ? { color } : {}),
            ...(settings?.display?.yAxisPosition === 'right' ? { yAxisId: 'right' } : {}),
            ...(type !== 'bar' && isAreaSeries(visualizationType, settings)
                ? { fill: { opacity: AREA_FILL_OPACITY } }
                : {}),
        }
    })
}

/** Formats a chart display value (tooltip rows/total, value labels, custom axis ticks) with a
 *  column's display settings. Values without an explicit style or decimal-place count are capped
 *  at 3 fraction digits — a computed column (e.g. a ratio) otherwise renders with full float
 *  precision (`22.222222222222`). The results table keeps full precision on purpose; this rounding
 *  is chart-display only. */
export function formatSeriesValue(value: number, settings?: AxisSeriesSettings): string {
    const formatting = settings?.formatting
    // Styled values round inside formatDataWithSettings. Unstyled values are capped here — at the
    // column's explicit decimalPlaces when set (formatDataWithSettings skips a falsy 0, so a
    // zero-decimal column would otherwise keep its fraction digits), else at 3. Prefix/suffix
    // don't round, so they don't opt out.
    const hasStyle = !!formatting && (formatting.style ?? 'none') !== 'none'
    const display = hasStyle || !Number.isFinite(value) ? value : Number(value.toFixed(formatting?.decimalPlaces ?? 3))
    return String(formatDataWithSettings(display, settings) ?? display)
}

const isRightAxisSeries = (series: ChartYSeries): boolean => series.settings?.display?.yAxisPosition === 'right'

/** Series assigned to a given gutter — tick formatting reads the first series on that axis, so each
 *  gutter formats from a column actually on it rather than a blind `series[0]`. */
const seriesForAxis = (ySeriesData: ChartYSeries[] | null | undefined, position: 'left' | 'right'): ChartYSeries[] =>
    (ySeriesData ?? []).filter((series) => isRightAxisSeries(series) === (position === 'right'))

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

/** Built-in tooltip for the line + combo charts: each row formatted by its column's settings
 *  (from `series.meta`), plus an optional total row. */
export function buildTooltipConfig(chartSettings: ChartSettings, ySeriesData?: ChartYSeries[] | null): TooltipConfig {
    // The total sums the non-percent columns (percent columns are excluded via
    // `visibility.total` in buildChartSeries), so it must format with a column that's actually in
    // the sum — a blind `[0]` borrows a percent column's style and renders a sum of counts as
    // "15,061.4%". Matches the legacy renderer's first-summable-column choice.
    const totalSettings = ySeriesData?.find((series) => series.settings?.formatting?.style !== 'percent')?.settings
    return {
        enabled: true,
        pinnable: true,
        placement: 'cursor',
        sortedByValue: true,
        valueFormatter: (value: number, entry: TooltipContext['seriesData'][number]) =>
            formatSeriesValue(value, (entry.series.meta as ChartSeriesMeta | undefined)?.settings),
        showTotal: chartSettings.showTotalRow !== false,
        totalFormatter: (value: number) => formatSeriesValue(value, totalSettings),
    }
}

/** Returns a tooltip label formatter for date/datetime x-axes, or undefined for non-date axes. */
function buildDateLabelFormatter(xData: ChartXSeries, timezone: string): ((label: string) => string) | undefined {
    const typeName = xData.column.type.name
    if (typeName === 'DATETIME') {
        return (label: string) => dayjs(label).tz(timezone).format('MMM D, HH:mm')
    }
    if (typeName === 'DATE') {
        return (label: string) => dayjs(label).format('MMM D, YYYY')
    }
    return undefined
}

export interface BuildConfigArgs {
    xData: ChartXSeries
    chartSettings: ChartSettings
    timezone: string
    goalLines?: GoalLine[]
    ySeriesData?: ChartYSeries[] | null
}

export interface BuildBarConfigArgs extends BuildConfigArgs {
    visualizationType: ChartDisplayType
}

function goalLinesToConfigs(goalLines: GoalLine[] | null | undefined): GoalLineConfig[] | undefined {
    if (!goalLines?.length) {
        return undefined
    }
    return goalLines.map((line) => ({
        value: line.value,
        label: line.label,
        displayLabel: line.displayLabel,
        color: line.borderColor,
        labelPosition: line.position,
        displayIfCrossed: line.displayIfCrossed,
    }))
}

function buildXAxisConfig(xData: ChartXSeries, chartSettings: ChartSettings, timezone: string): XAxisConfig {
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
    axisSeries: ChartYSeries[],
    yAxisAtZero: boolean | undefined,
    { forceLinear = false, id, position }: { forceLinear?: boolean; id?: string; position?: 'left' | 'right' } = {}
): YAxisConfig {
    const isLog = !forceLinear && yAxis?.scale === 'logarithmic'
    const tickSettings = axisSeries[0]?.settings
    const tickFormatter =
        !forceLinear && hasAxisTickFormatting(tickSettings)
            ? (value: number): string => formatSeriesValue(value, tickSettings)
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
 * tooltip's {@link formatSeriesValue} path so labels read identically to the tooltip. `seriesIndex`
 * aligns with `ySeriesData` because {@link buildChartSeries} preserves order and quill keeps hidden
 * series in place (excluded, not removed). `context.rawValue` is the unscaled value (the `value` arg
 * becomes a 0–1 fraction in percent-stacked bars), so labels always show the real number.
 */
function buildValueLabelsConfig(
    chartSettings: ChartSettings,
    ySeriesData: ChartYSeries[] | null | undefined
): ValueLabelsConfig | undefined {
    if (!chartSettings.showValuesOnSeries) {
        return undefined
    }
    return {
        formatter: (_value, seriesIndex, _dataIndex, context) =>
            formatSeriesValue(context.rawValue, ySeriesData?.[seriesIndex]?.settings),
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
    const labelFormatter = buildDateLabelFormatter(xData, timezone)

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
        goalLines: goalLinesToConfigs(goalLines),
        showAxisLines: buildAxisLinesConfig(chartSettings),
        trendLines: buildTrendLineConfigs(ySeriesData),
        legend: buildLegendConfig(chartSettings),
        valueLabels: buildValueLabelsConfig(chartSettings, ySeriesData),
        tooltip: {
            ...buildTooltipConfig(chartSettings, ySeriesData),
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
    const labelFormatter = buildDateLabelFormatter(xData, timezone)
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
        goalLines: goalLinesToConfigs(goalLines),
        showAxisLines: buildAxisLinesConfig(chartSettings),
        barLayout,
        // Stacked bars must preserve negative values (results can be negative) so they render
        // below the zero baseline instead of being clamped to 0. Only the stacked layout stacks.
        divergingStack: barLayout === 'stacked',
        // Percent bars scale against a [0, 1] domain; trend lines plot raw series values, so they'd
        // render off-scale and invisible.
        trendLines: barLayout === 'percent' ? [] : buildTrendLineConfigs(ySeriesData),
        legend: buildLegendConfig(chartSettings),
        valueLabels: buildValueLabelsConfig(chartSettings, ySeriesData),
        tooltip: {
            ...buildTooltipConfig(chartSettings, ySeriesData),
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
    const labelFormatter = buildDateLabelFormatter(xData, timezone)

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
        goalLines: goalLinesToConfigs(goalLines),
        showAxisLines: buildAxisLinesConfig(chartSettings),
        barLayout,
        // Stacked bars must preserve negative values (results can be negative) so they render
        // below the zero baseline instead of being clamped to 0 — mirrors buildBarChartConfig.
        divergingStack: barLayout === 'stacked',
        // Percent bars scale against a [0, 1] domain; trend lines plot raw series values, so they'd
        // render off-scale and invisible.
        trendLines: isPercent ? [] : buildTrendLineConfigs(ySeriesData),
        legend: buildLegendConfig(chartSettings),
        valueLabels: buildValueLabelsConfig(chartSettings, ySeriesData),
        tooltip: {
            ...buildTooltipConfig(chartSettings, ySeriesData),
            ...(labelFormatter ? { labelFormatter } : {}),
        },
    }
}
