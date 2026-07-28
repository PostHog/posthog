import { lemonToast } from '@posthog/lemon-ui'

import { MAX_SERIES } from 'lib/charts/timeSeriesChartAdapter'

import { AxisSeries } from '../../dataVisualizationLogic'
import { AxisBreakdownSeries } from '../seriesBreakdownLogic'
import { LineGraphProps } from './LineGraph'

/**
 * The SQL insight face of the generic time-series adapter in `lib/charts/timeSeriesChartAdapter` —
 * everything chart-shaped is re-exported from there under this module's established names; only
 * the SQL-editor concerns (the too-many-series toast and its dashboard gate) live here.
 */

export {
    AREA_FILL_OPACITY,
    MAX_SERIES,
    barLayoutForDisplay,
    buildBarChartConfig,
    buildComboChartConfig,
    buildLineChartConfig,
    buildTrendLineConfigs,
    capYSeriesData,
    comboBarLayoutForDisplay,
    hasAxisTickFormatting,
    hasMixedSeriesTypes,
    isAreaSeries,
    seriesDisplayType,
} from 'lib/charts/timeSeriesChartAdapter'
export {
    buildChartSeries as buildSeries,
    buildTooltipConfig as buildSqlTooltipConfig,
    canRenderTimeSeriesBarChart as canRenderSqlBarGraph,
    canRenderTimeSeriesComboChart as canRenderSqlComboGraph,
    canRenderTimeSeriesLineChart as canRenderSqlLineGraph,
    formatSeriesValue as formatSqlSeriesValue,
} from 'lib/charts/timeSeriesChartAdapter'
export type { BuildBarConfigArgs, ChartSeriesMeta as SqlLineSeriesMeta } from 'lib/charts/timeSeriesChartAdapter'

export type SqlLineYSeries = AxisSeries<number | null> | AxisBreakdownSeries<number | null>

/** Returns true when {@link MAX_SERIES} is exceeded and the user should be warned (not on dashboards). */
export function exceedsMaxSeries(yData: LineGraphProps['yData'], dashboardId: LineGraphProps['dashboardId']): boolean {
    return !!yData && yData.length > MAX_SERIES && !dashboardId
}

export function warnTooManySeries(count: number): void {
    lemonToast.warning(
        `This breakdown has too many series (${count}). Only showing top ${MAX_SERIES} series in the chart. All series are still available in the table below.`
    )
}
