import { ChartSettings, GoalLine } from '~/queries/schema/schema-general'
import { ChartDisplayType } from '~/types'

import { AxisSeries } from '../../dataVisualizationLogic'
import { AxisBreakdownSeries } from '../seriesBreakdownLogic'
import { SqlBarGraph } from './SqlBarGraph'
import { SqlComboGraph } from './SqlComboGraph'
import { SqlLineGraph } from './SqlLineGraph'
import { sqlChartKind } from './sqlLineGraphAdapter'

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
    /** Numeric id of the saved insight backing this chart. When set (and the x-axis is a run of
     *  daily dates), the quill SQL charts render the shared annotations overlay. Leave unset for
     *  unsaved/ad-hoc queries, since annotations attach to a persisted insight. */
    insightNumericId?: number | 'new'
    /** Toggles the annotations overlay on the quill SQL charts. Defaults to on. */
    showAnnotations?: boolean
    /** True on shared/exported surfaces (public dashboards, image exports); hides the annotations
     *  overlay there, matching the trends charts. */
    inSharedMode?: boolean
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
