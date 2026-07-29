import { ChartSettings, GoalLine } from '~/queries/schema/schema-general'
import { ChartDisplayType } from '~/types'

import { AxisSeries } from '../../dataVisualizationLogic'
import { AxisBreakdownSeries } from '../seriesBreakdownLogic'
import { SqlBarGraph } from './SqlBarGraph'
import { SqlComboGraph } from './SqlComboGraph'
import { SqlLineGraph } from './SqlLineGraph'
import { canRenderSqlBarGraph, canRenderSqlComboGraph } from './sqlLineGraphAdapter'

export type SqlChartProps = {
    xData: AxisSeries<string> | null
    yData: AxisSeries<number | null>[] | AxisBreakdownSeries<number | null>[]
    visualizationType: ChartDisplayType
    chartSettings: ChartSettings
    presetChartHeight?: boolean
    dashboardId?: string
    goalLines?: GoalLine[]
    className?: string
    /** Called when the user clicks a data point. Receives the series key, x-axis index, and label.
     *  When provided, the SQL chart shows a "click to inspect" hint in the tooltip. */
    onPointClick?: (seriesKey: string, dataIndex: number, label: string) => void
}

/**
 * Picks the @posthog/quill-charts renderer for a SQL insight: combo for mixed bar + line/area
 * series, bar for bar-only, line/area otherwise. (Pie has its own wrapper — see PieChart.)
 */
export function sqlChartComponentFor(props: SqlChartProps): (props: SqlChartProps) => JSX.Element {
    if (canRenderSqlComboGraph(props)) {
        return SqlComboGraph
    }
    if (canRenderSqlBarGraph(props)) {
        return SqlBarGraph
    }
    return SqlLineGraph
}

/** Entry point for rendering a non-pie SQL (DataVisualization) chart: dispatches line, area, bar,
 *  stacked-bar, and combo series to the matching @posthog/quill-charts renderer. */
export const SqlChart = (props: SqlChartProps): JSX.Element => {
    const Component = sqlChartComponentFor(props)
    return <Component {...props} />
}
