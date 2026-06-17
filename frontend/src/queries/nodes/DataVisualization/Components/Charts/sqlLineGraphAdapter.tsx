import { lemonToast } from '@posthog/lemon-ui'
import { type Series, type TimeSeriesLineChartConfig, createXAxisTickCallback } from '@posthog/quill-charts'

import { getSeriesColor } from 'lib/colors'

import { ChartSettings, GoalLine } from '~/queries/schema/schema-general'
import { ChartDisplayType } from '~/types'

import { schemaGoalLinesToConfigs } from 'products/product_analytics/frontend/insights/trends/shared/goalLinesAdapter'

import { AxisSeries, AxisSeriesSettings } from '../../dataVisualizationLogic'
import { AxisBreakdownSeries } from '../seriesBreakdownLogic'
import { LineGraphProps } from './LineGraph'

/** Cap shared with the legacy chart.js path. */
export const MAX_SERIES = 200

export type SqlLineYSeries = AxisSeries<number | null> | AxisBreakdownSeries<number | null>

const isAreaSeries = (visualizationType: ChartDisplayType, settings: AxisSeriesSettings | undefined): boolean =>
    visualizationType === ChartDisplayType.ActionsAreaGraph || settings?.display?.displayType === 'area'

const getSeriesLabel = (series: SqlLineYSeries): string => ('name' in series ? series.name : series.column.name)

const getSeriesKey = (series: SqlLineYSeries, index: number): string =>
    'breakdownValue' in series ? series.breakdownValue : `${series.column.name}-${index}`

/**
 * Plain line/area charts — including dual y-axis and goal lines — render here. Trend lines and mixed
 * line/bar series aren't ported yet, so those fall back to the legacy chart.js path.
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
    return true
}

/** Apply the {@link MAX_SERIES} cap, warning once (outside dashboards) when it bites. */
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

export function buildSeries(yData: SqlLineYSeries[], visualizationType: ChartDisplayType): Series[] {
    return yData.map((series, index) => {
        const settings = series.settings
        // quill places the default axis on the left and the next distinct axis on the right, so
        // left-axis series stay unset (see `orderedAxisPositions`).
        const yAxisId = settings?.display?.yAxisPosition === 'right' ? 'right' : undefined

        return {
            key: getSeriesKey(series, index),
            label: getSeriesLabel(series),
            // null -> NaN so quill draws a gap rather than a zero.
            data: series.data.map((value) => (value == null ? NaN : value)),
            color: settings?.display?.color ?? getSeriesColor(index),
            ...(yAxisId ? { yAxisId } : {}),
            ...(isAreaSeries(visualizationType, settings) ? { fill: { opacity: 0.5 } } : {}),
        }
    })
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
