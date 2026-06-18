import { lemonToast } from '@posthog/lemon-ui'
import {
    type Series,
    type TimeSeriesLineChartConfig,
    type TooltipContext,
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

/** Per-series data threaded through quill's `series.meta` so the tooltip render prop can format
 *  and label each row without re-deriving it from the raw query result. */
export interface SqlLineSeriesMeta {
    settings: AxisSeriesSettings | undefined
}

export const isAreaSeries = (visualizationType: ChartDisplayType, settings: AxisSeriesSettings | undefined): boolean =>
    visualizationType === ChartDisplayType.ActionsAreaGraph || settings?.display?.displayType === 'area'

const getSeriesLabel = (series: SqlLineYSeries): string => ('name' in series ? series.name : series.column.name)

const getSeriesKey = (series: SqlLineYSeries, index: number): string =>
    'breakdownValue' in series ? series.breakdownValue : `${series.column.name}-${index}`

/**
 * Plain line/area charts — including goal lines — render here. Trend lines, mixed line/bar series,
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
    if (yData?.some((series) => series.settings?.display?.trendLine)) {
        return false
    }
    // quill applies a single tick formatter/scale to both gutters, so a right axis can't honor its
    // own settings yet — fall back to legacy rather than silently dropping those prefs.
    if (yData?.some((series) => series.settings?.display?.yAxisPosition === 'right')) {
        return false
    }
    return true
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

export function buildSeries(yData: SqlLineYSeries[], visualizationType: ChartDisplayType): Series<SqlLineSeriesMeta>[] {
    return yData.map((series, index) => {
        const settings = series.settings
        const color = settings?.display?.color

        return {
            key: getSeriesKey(series, index),
            label: getSeriesLabel(series),
            // null -> NaN so quill draws a gap rather than a zero.
            data: series.data.map((value) => (value == null ? NaN : value)),
            // Carry per-series settings into the tooltip render prop (formatting + label overrides).
            meta: { settings },
            // Only pin an explicit color; otherwise let quill assign palette colors by index.
            ...(color ? { color } : {}),
            ...(isAreaSeries(visualizationType, settings) ? { fill: { opacity: AREA_FILL_OPACITY } } : {}),
        }
    })
}

export interface SqlLineTooltipRow {
    key: string
    name: string
    color: string
    value: string
    rawValue: number
}

export interface SqlLineTooltipModel {
    label: string
    rows: SqlLineTooltipRow[]
    totalLabel: string | null
}

/** Tooltip series name: an explicit display label wins, else the series' own label (legacy parity). */
const resolveSeriesName = (series: Series<SqlLineSeriesMeta>): string =>
    series.meta?.settings?.display?.label || series.label

/**
 * Pure shape of the rich tooltip the legacy chart.js path renders, derived from quill's hover
 * {@link TooltipContext}. Mirrors `LegacyLineGraph`: drops empty points, sorts rows by value
 * descending, and appends a total row summing the non-percent series. Rendering lives in
 * {@link SqlLineGraphTooltip}.
 */
export function buildSqlLineTooltipModel(
    context: TooltipContext<SqlLineSeriesMeta>,
    chartSettings: ChartSettings
): SqlLineTooltipModel {
    // null data points arrive as NaN (see buildSeries) — drop them, as the legacy path drops nulls.
    const present = context.seriesData.filter(({ value }) => !Number.isNaN(value))

    const rows: SqlLineTooltipRow[] = present.map(({ series, value, color }) => ({
        key: series.key,
        name: resolveSeriesName(series),
        color,
        value: String(formatDataWithSettings(value, series.meta?.settings) ?? value),
        rawValue: value,
    }))

    if (rows.length > 1) {
        rows.sort((a, b) => b.rawValue - a.rawValue)
    }

    // Total sums the non-percent series in original series order, formatted like the first of them.
    const totalParts = present.filter(({ series }) => series.meta?.settings?.formatting?.style !== 'percent')
    let totalLabel: string | null = null
    if (totalParts.length > 1 && chartSettings.showTotalRow !== false) {
        const totalRawValue = totalParts.reduce((acc, { value }) => acc + value, 0)
        const firstSettings = totalParts[0]?.series.meta?.settings
        totalLabel = String(formatDataWithSettings(totalRawValue, firstSettings) ?? totalRawValue)
    }

    return { label: context.label, rows, totalLabel }
}

interface BuildConfigArgs {
    xData: AxisSeries<string>
    chartSettings: ChartSettings
    timezone: string
    goalLines?: GoalLine[]
}

export function buildLineChartConfig({
    xData,
    chartSettings,
    timezone,
    goalLines,
}: BuildConfigArgs): TimeSeriesLineChartConfig {
    const isDateAxis = xData.column.type.name === 'DATE' || xData.column.type.name === 'DATETIME'
    const yAxis = chartSettings.leftYAxisSettings

    return {
        xAxis: {
            label: chartSettings.xAxisLabel,
            tickFormatter: isDateAxis ? createXAxisTickCallback({ allDays: xData.data, timezone }) : undefined,
            hide: chartSettings.showXAxisTicks === false,
        },
        yAxis: {
            label: yAxis?.label,
            scale: yAxis?.scale === 'logarithmic' ? 'log' : 'linear',
            showGrid: yAxis?.showGridLines ?? true,
            hide: yAxis?.showTicks === false,
        },
        goalLines: schemaGoalLinesToConfigs(goalLines),
        tooltip: { enabled: true, pinnable: true },
    }
}
