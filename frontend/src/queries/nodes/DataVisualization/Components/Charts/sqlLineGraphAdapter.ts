import { lemonToast } from '@posthog/lemon-ui'
import {
    type ChartLegendConfig,
    type Series,
    type TimeSeriesBarChartConfig,
    type TimeSeriesLineChartConfig,
    type TrendLineConfig,
    type XAxisConfig,
    type YAxisConfig,
    createXAxisTickCallback,
} from '@posthog/quill-charts'

import { ChartSettings, GoalLine } from '~/queries/schema/schema-general'
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

const getSeriesLabel = (series: SqlLineYSeries): string => ('name' in series ? series.name : series.column.name)

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
 * Plain line/area charts — including goal lines and trend lines — render here. Mixed line/bar series
 * and right y-axis series aren't ported yet, so those fall back to the legacy chart.js path.
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
    // quill applies a single tick formatter/scale to both gutters, so a right axis can't honor its
    // own settings yet — fall back to legacy rather than silently dropping those prefs.
    if (yData?.some((series) => series.settings?.display?.yAxisPosition === 'right')) {
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
    // quill's TimeSeriesBarChart has no trend-line support yet — fall back until it does.
    if (yData?.some((series) => series.settings?.display?.trendLine)) {
        return false
    }
    if (yData?.some((series) => series.settings?.display?.yAxisPosition === 'right')) {
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

        return {
            key: getSeriesKey(series, index),
            label: getSeriesLabel(series),
            // null -> NaN so quill draws a gap rather than a zero.
            data: series.data.map((value) => (value == null ? NaN : value)),
            meta: { settings },
            // Only pin an explicit color; otherwise let quill assign palette colors by index.
            ...(color ? { color } : {}),
            ...(isAreaSeries(visualizationType, settings) ? { fill: { opacity: AREA_FILL_OPACITY } } : {}),
        }
    })
}

/** Formats a tooltip value with a column's display settings. */
export function formatSqlSeriesValue(value: number, settings?: AxisSeriesSettings): string {
    return String(formatDataWithSettings(value, settings) ?? value)
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

function buildYAxisConfig(
    chartSettings: ChartSettings,
    { forceLinear = false }: { forceLinear?: boolean } = {}
): YAxisConfig {
    const yAxis = chartSettings.leftYAxisSettings

    return {
        label: yAxis?.label,
        scale: !forceLinear && yAxis?.scale === 'logarithmic' ? 'log' : 'linear',
        showGrid: yAxis?.showGridLines ?? true,
        hide: yAxis?.showTicks === false,
    }
}

function buildLegendConfig(chartSettings: ChartSettings): ChartLegendConfig {
    return { show: chartSettings.showLegend ?? false, position: 'top', interactive: true }
}

export function buildLineChartConfig({
    xData,
    chartSettings,
    timezone,
    goalLines,
    ySeriesData,
}: BuildConfigArgs): TimeSeriesLineChartConfig {
    return {
        xAxis: buildXAxisConfig(xData, chartSettings, timezone),
        yAxis: buildYAxisConfig(chartSettings),
        goalLines: schemaGoalLinesToConfigs(goalLines),
        trendLines: buildTrendLineConfigs(ySeriesData),
        legend: buildLegendConfig(chartSettings),
        tooltip: { enabled: true, pinnable: true },
    }
}

export function buildBarChartConfig({
    xData,
    chartSettings,
    timezone,
    goalLines,
    visualizationType,
}: BuildBarConfigArgs): TimeSeriesBarChartConfig {
    const barLayout = barLayoutForDisplay(visualizationType, chartSettings)

    return {
        xAxis: buildXAxisConfig(xData, chartSettings, timezone),
        yAxis: buildYAxisConfig(chartSettings, { forceLinear: barLayout === 'percent' }),
        goalLines: schemaGoalLinesToConfigs(goalLines),
        barLayout,
        legend: buildLegendConfig(chartSettings),
        tooltip: { enabled: true, pinnable: true },
    }
}
