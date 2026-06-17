import { lemonToast } from '@posthog/lemon-ui'
import {
    type ChartTheme,
    type Series,
    type TimeSeriesLineChartConfig,
    createXAxisTickCallback,
} from '@posthog/quill-charts'

import { getGraphColors, getSeriesColor, getSeriesColorPalette } from 'lib/colors'

import { ChartSettings } from '~/queries/schema/schema-general'
import { ChartDisplayType } from '~/types'

import { AxisSeries, AxisSeriesSettings } from '../../dataVisualizationLogic'
import { AxisBreakdownSeries } from '../seriesBreakdownLogic'
import { LineGraphProps } from './LineGraph'

/** Cap shared with the legacy chart.js path — keep both in sync. */
export const MAX_SERIES = 200

/** Y series accepted by the chart: either a plain axis series or a breakdown series. */
export type SqlLineYSeries = AxisSeries<number | null> | AxisBreakdownSeries<number | null>

/** Original per-series settings carried into the tooltip so it can format values. */
export interface SqlLineSeriesMeta {
    settings?: AxisSeriesSettings
}

const isAreaSeries = (visualizationType: ChartDisplayType, settings: AxisSeriesSettings | undefined): boolean =>
    visualizationType === ChartDisplayType.ActionsAreaGraph || settings?.display?.displayType === 'area'

const getSeriesLabel = (series: SqlLineYSeries): string => ('name' in series ? series.name : series.column.name)

const getSeriesKey = (series: SqlLineYSeries, index: number): string =>
    'breakdownValue' in series ? series.breakdownValue : `${series.column.name}-${index}`

/**
 * Whether the SQL line graph can faithfully render these inputs via @posthog/quill-charts. Plain
 * line/area charts — including dual y-axis — are handled here; goal lines, trend lines, and mixed
 * line/bar series aren't ported yet, so those fall back to the legacy chart.js path rather than
 * dropping the feature.
 */
export function canRenderSqlLineGraph(props: LineGraphProps): boolean {
    const { visualizationType, yData, goalLines } = props

    if (
        visualizationType !== ChartDisplayType.ActionsLineGraph &&
        visualizationType !== ChartDisplayType.ActionsAreaGraph
    ) {
        return false
    }

    // A per-series `bar` display inside a line/area graph is a mixed chart — out of scope here.
    if (yData?.some((series) => series.settings?.display?.displayType === 'bar')) {
        return false
    }

    // TODO(PR3/PR4): goal lines and trend lines aren't ported yet — don't silently drop them.
    if (goalLines && goalLines.length > 0) {
        return false
    }
    if (yData?.some((series) => series.settings?.display?.trendLine)) {
        return false
    }

    return true
}

/**
 * Apply the {@link MAX_SERIES} cap, warning once (outside dashboards) when it bites — mirrors the
 * legacy LineGraph behavior so the table below the chart stays the source of truth for all series.
 */
export function capYSeriesData(
    yData: LineGraphProps['yData'],
    dashboardId: LineGraphProps['dashboardId']
): SqlLineYSeries[] | null {
    if (!yData) {
        return null
    }
    if (yData.length > MAX_SERIES) {
        if (!dashboardId) {
            lemonToast.warning(
                `This breakdown has too many series (${yData.length}). Only showing top ${MAX_SERIES} series in the chart. All series are still available in the table below.`
            )
        }
        return yData.slice(0, MAX_SERIES)
    }
    return yData
}

/**
 * Map the capped y series to quill `Series`, carrying color, area fill, dual y-axis assignment, and
 * the original settings (for the tooltip).
 */
export function buildSeries(yData: SqlLineYSeries[], visualizationType: ChartDisplayType): Series<SqlLineSeriesMeta>[] {
    return yData.map((series, index) => {
        const settings = series.settings
        const color = settings?.display?.color ?? getSeriesColor(index)
        const hasAreaFill = isAreaSeries(visualizationType, settings)
        // quill auto-places the default axis on the left and the next distinct axis on the right
        // (see `orderedAxisPositions`), so leaving left-axis series unset keeps them on the left.
        const yAxisId = settings?.display?.yAxisPosition === 'right' ? 'right' : undefined

        return {
            key: getSeriesKey(series, index),
            label: getSeriesLabel(series),
            // Nulls become NaN so quill draws a gap (the chart.js null behavior) rather than a 0.
            data: series.data.map((value) => (value == null ? NaN : value)),
            color,
            meta: { settings },
            ...(yAxisId ? { yAxisId } : {}),
            ...(hasAreaFill ? { fill: { opacity: 0.5 } } : {}),
        }
    })
}

/** Build a quill {@link ChartTheme} from the app's graph color tokens. */
export function buildChartTheme(): ChartTheme {
    const colors = getGraphColors()
    return {
        colors: getSeriesColorPalette(),
        axisColor: colors.axisLabel ?? undefined,
        gridColor: colors.axisLine ?? undefined,
        crosshairColor: colors.crosshair ?? undefined,
        tooltipBackground: colors.tooltipBackground ?? undefined,
        tooltipColor: colors.tooltipBody ?? undefined,
    }
}

interface BuildConfigArgs {
    xData: AxisSeries<string>
    chartSettings: ChartSettings
    timezone: string
}

/** Map the existing chart settings onto quill's TimeSeriesLineChart config. */
export function buildLineChartConfig({ xData, chartSettings, timezone }: BuildConfigArgs): TimeSeriesLineChartConfig {
    const isDateAxis = xData.column.type.name === 'DATE' || xData.column.type.name === 'DATETIME'
    const tickFormatter = isDateAxis ? createXAxisTickCallback({ allDays: xData.data, timezone }) : undefined

    // With dual axes, quill applies one tick formatter/label to both gutters — per-axis label and
    // scale (left vs right) can't be set independently yet, so we use the left axis settings.
    const yAxis = chartSettings.leftYAxisSettings

    return {
        xAxis: {
            label: chartSettings.xAxisLabel,
            tickFormatter,
            hide: chartSettings.showXAxisTicks === false,
        },
        yAxis: {
            label: yAxis?.label,
            scale: yAxis?.scale === 'logarithmic' ? 'log' : 'linear',
            showGrid: yAxis?.showGridLines ?? true,
            hide: yAxis?.showTicks === false,
            // TODO(PR5): `startAtZero`/`yAxisAtZero` — TimeSeriesLineChartConfig doesn't expose a
            //   value domain to pin the baseline at zero (the LineChart `valueDomain` isn't surfaced).
        },
        // Pinning matches the legacy click-to-pin behavior; the tooltip *content* is the render prop.
        tooltip: { enabled: true, pinnable: true },
        // TODO(PR2/PR3/PR4): rich LemonTable tooltip, goal lines, trend lines, datalabels (value
        //   labels), stackBars100, shift-to-highlight (bar-only) — later PRs.
    }
}
