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
    AxisSeries,
    AxisSeriesSettings,
    formatDataWithSettings,
} from '~/queries/nodes/DataVisualization/dataVisualizationLogic'
import { ChartSettings, GoalLine, YAxisSettings } from '~/queries/schema/schema-general'
import { ChartDisplayType } from '~/types'

/** Matches the insight renderer's area fill. */
const AREA_FILL_OPACITY = 0.5

export type BillingYSeries = AxisSeries<number | null>

/**
 * The slice of a saved insight's chart definition the billing tabs render. Series breakdowns are
 * excluded upstream (`canRenderBillingChart`), so the y series are always plain axis columns.
 */
export interface BillingChartProps {
    xData: AxisSeries<string> | null
    yData: BillingYSeries[]
    visualizationType: ChartDisplayType
    chartSettings: ChartSettings
    goalLines?: GoalLine[]
}

export interface BillingSeriesMeta {
    settings?: AxisSeriesSettings
}

const isAreaSeries = (visualizationType: ChartDisplayType, settings: AxisSeriesSettings | undefined): boolean =>
    visualizationType === ChartDisplayType.ActionsAreaGraph || settings?.display?.displayType === 'area'

const isRightAxisSeries = (series: BillingYSeries): boolean => series.settings?.display?.yAxisPosition === 'right'

/** Per-series quill type — a column can override the chart-wide display type. */
export function billingSeriesType(
    visualizationType: ChartDisplayType,
    settings: AxisSeriesSettings | undefined
): SeriesType {
    const displayType = settings?.display?.displayType
    if (displayType === 'bar' || displayType === 'line' || displayType === 'area') {
        return displayType
    }
    if (visualizationType === ChartDisplayType.ActionsBar || visualizationType === ChartDisplayType.ActionsStackedBar) {
        return 'bar'
    }
    if (visualizationType === ChartDisplayType.ActionsAreaGraph) {
        return 'area'
    }
    return 'line'
}

/** True when the series resolve to a mix of bar and line/area — the case neither single-type chart
 *  can render. */
function hasMixedSeriesTypes(yData: BillingYSeries[], visualizationType: ChartDisplayType): boolean {
    let hasBar = false
    let hasLineLike = false
    for (const series of yData) {
        if (billingSeriesType(visualizationType, series.settings) === 'bar') {
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

/**
 * Mixed bar + line/area series render on the combo chart. Percent-stacked bars are supported only
 * when every line/area series is routed to the right axis — one sharing the bars' axis can't be
 * reconciled with their [0, 1] percent scale, so that case falls through to the line renderer.
 */
export function canRenderBillingComboChart({ yData, visualizationType, chartSettings }: BillingChartProps): boolean {
    if (!hasMixedSeriesTypes(yData, visualizationType)) {
        return false
    }
    if (
        visualizationType === ChartDisplayType.ActionsStackedBar &&
        chartSettings.stackBars100 &&
        yData.some(
            (series) => billingSeriesType(visualizationType, series.settings) !== 'bar' && !isRightAxisSeries(series)
        )
    ) {
        return false
    }
    return true
}

export function canRenderBillingBarChart({ yData, visualizationType }: BillingChartProps): boolean {
    if (visualizationType !== ChartDisplayType.ActionsBar && visualizationType !== ChartDisplayType.ActionsStackedBar) {
        return false
    }
    return !yData.some((series) => {
        const displayType = series.settings?.display?.displayType
        return displayType === 'line' || displayType === 'area'
    })
}

const getSeriesLabel = (series: BillingYSeries): string => series.settings?.display?.label || series.column.name

export function buildBillingSeries(
    yData: BillingYSeries[],
    visualizationType: ChartDisplayType
): Series<BillingSeriesMeta>[] {
    return yData.map((series, index) => {
        const settings = series.settings
        const color = settings?.display?.color
        const type = billingSeriesType(visualizationType, settings)

        return {
            key: `${series.column.name}-${index}`,
            label: getSeriesLabel(series),
            // null -> NaN so quill draws a gap rather than a zero.
            data: series.data.map((value) => (value == null ? NaN : value)),
            meta: { settings },
            type,
            // A percent column doesn't sum meaningfully with the others, so keep it out of the total.
            ...(settings?.formatting?.style === 'percent' ? { visibility: { total: false } } : {}),
            ...(color ? { color } : {}),
            ...(settings?.display?.yAxisPosition === 'right' ? { yAxisId: 'right' } : {}),
            ...(type !== 'bar' && isAreaSeries(visualizationType, settings)
                ? { fill: { opacity: AREA_FILL_OPACITY } }
                : {}),
        }
    })
}

/** Formats a chart display value with its column's settings. Values without an explicit style or
 *  decimal-place count are capped at 3 fraction digits, so a computed column doesn't render with
 *  full float precision. */
export function formatBillingValue(value: number, settings?: AxisSeriesSettings): string {
    const formatting = settings?.formatting
    const hasStyle = !!formatting && (formatting.style ?? 'none') !== 'none'
    const display = hasStyle || !Number.isFinite(value) ? value : Number(value.toFixed(formatting?.decimalPlaces ?? 3))
    return String(formatDataWithSettings(display, settings) ?? display)
}

const seriesForAxis = (yData: BillingYSeries[], position: 'left' | 'right'): BillingYSeries[] =>
    yData.filter((series) => isRightAxisSeries(series) === (position === 'right'))

/** True when a column carries formatting that should override quill's default numeric axis ticks. */
function hasAxisTickFormatting(settings?: AxisSeriesSettings): boolean {
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

function buildTooltipConfig(chartSettings: ChartSettings, yData: BillingYSeries[]): TooltipConfig {
    // Percent columns are excluded from the total via `visibility.total`, so the total must format
    // with a column that's actually in the sum rather than a blind `[0]`.
    const totalSettings = yData.find((series) => series.settings?.formatting?.style !== 'percent')?.settings
    return {
        enabled: true,
        pinnable: true,
        placement: 'cursor',
        sortedByValue: true,
        valueFormatter: (value: number, entry: TooltipContext['seriesData'][number]) =>
            formatBillingValue(value, (entry.series.meta as BillingSeriesMeta | undefined)?.settings),
        showTotal: chartSettings.showTotalRow !== false,
        totalFormatter: (value: number) => formatBillingValue(value, totalSettings),
    }
}

function buildDateLabelFormatter(xData: AxisSeries<string>, timezone: string): ((label: string) => string) | undefined {
    const typeName = xData.column.type.name
    if (typeName === 'DATETIME') {
        return (label: string) => dayjs(label).tz(timezone).format('MMM D, HH:mm')
    }
    if (typeName === 'DATE') {
        return (label: string) => dayjs(label).format('MMM D, YYYY')
    }
    return undefined
}

function buildXAxisConfig(xData: AxisSeries<string>, chartSettings: ChartSettings, timezone: string): XAxisConfig {
    const isDateAxis = xData.column.type.name === 'DATE' || xData.column.type.name === 'DATETIME'
    return {
        label: chartSettings.xAxisLabel,
        tickFormatter: isDateAxis ? createXAxisTickCallback({ allDays: xData.data, timezone }) : undefined,
        hide: chartSettings.showXAxisTicks === false,
    }
}

/** One y-axis from its settings plus the series on that gutter. Tick formatting reads the first
 *  series on the axis, so each gutter formats from a column actually on it. Percent-stacked bars
 *  (`forceLinear`) skip both — that axis shows a 0-100% scale, not column values. */
function buildYAxisConfig(
    yAxis: YAxisSettings | undefined,
    axisSeries: BillingYSeries[],
    yAxisAtZero: boolean | undefined,
    { forceLinear = false, id, position }: { forceLinear?: boolean; id?: string; position?: 'left' | 'right' } = {}
): YAxisConfig {
    const isLog = !forceLinear && yAxis?.scale === 'logarithmic'
    const tickSettings = axisSeries[0]?.settings
    const tickFormatter =
        !forceLinear && hasAxisTickFormatting(tickSettings)
            ? (value: number): string => formatBillingValue(value, tickSettings)
            : undefined

    return {
        ...(id ? { id } : {}),
        ...(position ? { position } : {}),
        label: yAxis?.label,
        scale: isLog ? 'log' : 'linear',
        showGrid: yAxis?.showGridLines ?? true,
        hide: yAxis?.showTicks === false,
        tickFormatter,
        startAtZero: forceLinear || !isLog ? (yAxis?.startAtZero ?? yAxisAtZero ?? true) : undefined,
    }
}

/** Emits the per-axis array form only when a series actually targets the right gutter, so
 *  single-axis charts keep the single-object form. */
function buildYAxis(
    yData: BillingYSeries[],
    chartSettings: ChartSettings,
    forceLinear: boolean
): YAxisConfig | YAxisConfig[] {
    const leftSeries = seriesForAxis(yData, 'left')
    const rightSeries = seriesForAxis(yData, 'right')

    if (rightSeries.length === 0) {
        return buildYAxisConfig(chartSettings.leftYAxisSettings, leftSeries, chartSettings.yAxisAtZero, {
            forceLinear,
        })
    }
    return [
        buildYAxisConfig(chartSettings.leftYAxisSettings, leftSeries, chartSettings.yAxisAtZero, {
            id: 'left',
            position: 'left',
            forceLinear,
        }),
        buildYAxisConfig(chartSettings.rightYAxisSettings, rightSeries, chartSettings.yAxisAtZero, {
            id: 'right',
            position: 'right',
            forceLinear,
        }),
    ]
}

function buildLegendConfig(chartSettings: ChartSettings): ChartLegendConfig {
    return { show: chartSettings.showLegend ?? false, position: 'top', interactive: true }
}

/** Undefined when both edges are on (the default), so the app-level style default still applies. */
function buildAxisLinesConfig(chartSettings: ChartSettings): AxisLinesConfig | undefined {
    const x = chartSettings.showXAxisBorder ?? true
    const y = chartSettings.showYAxisBorder ?? true
    return x && y ? undefined : { x, y }
}

function buildValueLabelsConfig(chartSettings: ChartSettings, yData: BillingYSeries[]): ValueLabelsConfig | undefined {
    if (!chartSettings.showValuesOnSeries) {
        return undefined
    }
    // `context.rawValue` is the unscaled value — `value` becomes a 0-1 fraction on percent stacks.
    return {
        formatter: (_value, seriesIndex, _dataIndex, context) =>
            formatBillingValue(context.rawValue, yData[seriesIndex]?.settings),
    }
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

export interface BuildConfigArgs {
    xData: AxisSeries<string>
    yData: BillingYSeries[]
    visualizationType: ChartDisplayType
    chartSettings: ChartSettings
    timezone: string
    goalLines?: GoalLine[]
}

function buildGoalLineConfigs(goalLines: GoalLine[] | null | undefined): GoalLineConfig[] | undefined {
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

/** Shares the key scheme with {@link buildBillingSeries} so each trend line matches its source series. */
function buildTrendLineConfigs(yData: BillingYSeries[]): TrendLineConfig[] {
    return yData.reduce<TrendLineConfig[]>((configs, series, index) => {
        if (series.settings?.display?.trendLine) {
            configs.push({ seriesKey: `${series.column.name}-${index}`, kind: 'linear' })
        }
        return configs
    }, [])
}

function buildSharedConfig({
    xData,
    yData,
    chartSettings,
    timezone,
    goalLines,
    forceLinear,
}: Omit<BuildConfigArgs, 'visualizationType'> & { forceLinear: boolean }): {
    xAxis: XAxisConfig
    yAxis: YAxisConfig | YAxisConfig[]
    goalLines: GoalLineConfig[] | undefined
    showAxisLines: AxisLinesConfig | undefined
    trendLines: TrendLineConfig[]
    legend: ChartLegendConfig
    valueLabels: ValueLabelsConfig | undefined
    tooltip: TooltipConfig
} {
    const labelFormatter = buildDateLabelFormatter(xData, timezone)
    return {
        xAxis: buildXAxisConfig(xData, chartSettings, timezone),
        yAxis: buildYAxis(yData, chartSettings, forceLinear),
        goalLines: buildGoalLineConfigs(goalLines),
        showAxisLines: buildAxisLinesConfig(chartSettings),
        // Percent bars scale against a [0, 1] domain; trend lines plot raw values, so they'd render
        // off-scale and invisible.
        trendLines: forceLinear ? [] : buildTrendLineConfigs(yData),
        legend: buildLegendConfig(chartSettings),
        valueLabels: buildValueLabelsConfig(chartSettings, yData),
        tooltip: {
            ...buildTooltipConfig(chartSettings, yData),
            ...(labelFormatter ? { labelFormatter } : {}),
        },
    }
}

export function buildBillingLineChartConfig(args: BuildConfigArgs): TimeSeriesLineChartConfig {
    return buildSharedConfig({ ...args, forceLinear: false })
}

export function buildBillingBarChartConfig(args: BuildConfigArgs): TimeSeriesBarChartConfig {
    const barLayout = barLayoutForDisplay(args.visualizationType, args.chartSettings)
    return {
        ...buildSharedConfig({ ...args, forceLinear: barLayout === 'percent' }),
        barLayout,
        // Stacked bars must keep negative values below the baseline instead of clamping them to 0.
        divergingStack: barLayout === 'stacked',
    }
}

export function buildBillingComboChartConfig(args: BuildConfigArgs): TimeSeriesComboChartConfig {
    const barLayout = barLayoutForDisplay(args.visualizationType, args.chartSettings)
    return {
        ...buildSharedConfig({ ...args, forceLinear: barLayout === 'percent' }),
        barLayout,
        divergingStack: barLayout === 'stacked',
    }
}
