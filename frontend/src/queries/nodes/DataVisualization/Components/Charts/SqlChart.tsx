import { ChartSettings, GoalLine } from '~/queries/schema/schema-general'
import { ChartDisplayType } from '~/types'

import { AxisSeries } from '../../dataVisualizationLogic'
import { AxisBreakdownSeries } from '../seriesBreakdownLogic'
import { SqlBarGraph } from './SqlBarGraph'
import { SqlComboGraph } from './SqlComboGraph'
import { SqlLineGraph } from './SqlLineGraph'
import { sqlChartKind } from './sqlLineGraphAdapter'

const SQL_CHART_VISUALIZATION_TYPES: ChartDisplayType[] = [
    ChartDisplayType.ActionsLineGraph,
    ChartDisplayType.ActionsBar,
    ChartDisplayType.ActionsBarValue,
    ChartDisplayType.ActionsAreaGraph,
    ChartDisplayType.ActionsStackedBar,
]

export const isSqlChartVisualizationType = (visualizationType: ChartDisplayType): boolean =>
    SQL_CHART_VISUALIZATION_TYPES.includes(visualizationType)

export type SqlChartProps = {
    xData: AxisSeries<string> | null
    yData: AxisSeries<number | null>[] | AxisBreakdownSeries<number | null>[]
    visualizationType: ChartDisplayType
    chartSettings: ChartSettings
    presetChartHeight?: boolean
    dashboardId?: string
    goalLines?: GoalLine[]
    insightNumericId?: number | 'new'
    showAnnotations?: boolean
    embedded?: boolean
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
    switch (sqlChartKind(props)) {
        case 'combo':
            return SqlComboGraph
        case 'bar':
            return SqlBarGraph
        case 'line':
            return SqlLineGraph
    }
}

/** Entry point for rendering a non-pie SQL (DataVisualization) chart: dispatches line, area, bar,
 *  stacked-bar, and combo series to the matching @posthog/quill-charts renderer. */
export const SqlChart = (props: SqlChartProps): JSX.Element => {
    const Component = sqlChartComponentFor(props)
    return <Component {...props} />
}
